"""Immutable versions of a published loadout and field evidence for one version."""
import hashlib
import json
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from backend.security import now


class Trial(BaseModel):
    outcome: Literal["成功", "异常", "未启动"]
    note: str = Field(min_length=1, max_length=500)
    evidence_post_id: int | None = None


def packed_draft(draft):
    keys = ("mods", "locks", "origin", "pins", "messages")
    return {k: draft[k] for k in keys if k in draft}


def with_diff(draft):
    source = draft.get("origin", {}).get("mods", ["fabric-api", "sodium"])
    return {**draft, "diff": {"added": [k for k in draft["mods"] if k not in source],
                               "removed": [k for k in source if k not in draft["mods"]]}}


def publish(c, pid, draft, catalog):
    keys = draft["mods"]
    if not keys:
        raise HTTPException(422, "草稿为空，不能发布整包")
    mods = {k: draft.get("pins", {}).get(k, catalog[k]) for k in keys}
    raw = json.dumps(mods, ensure_ascii=False, sort_keys=True)
    sig = hashlib.sha256(raw.encode()).hexdigest()
    last = c.execute("SELECT id,digest FROM pack_versions WHERE pid=? ORDER BY id DESC LIMIT 1",(pid,)).fetchone()
    if last and last["digest"] == sig:
        return last["id"]
    revision = c.execute("SELECT coalesce(max(rev),0)+1 FROM pack_versions WHERE pid=?", (pid,)).fetchone()[0]
    return c.execute("INSERT INTO pack_versions(pid,rev,digest,pins,stamp) VALUES(?,?,?,?,?)",
                     (pid,revision,sig,raw,now())).lastrowid


def summary(c, pid):
    v = c.execute("SELECT id,rev,pins FROM pack_versions WHERE pid=? ORDER BY rev DESC LIMIT 1",(pid,)).fetchone()
    return None if not v else {"id":v["id"],"revision":v["rev"],"count":len(json.loads(v["pins"]))}


def seed_examples(c, catalog):
    """Only attach to authored demo fixtures, never to arbitrary user posts."""
    for row in c.execute("""SELECT p.id,l.slug FROM posts p JOIN links l ON p.id=l.pid JOIN users u ON u.id=p.user_id
                WHERE (u.username='bob' AND p.content LIKE '林场日志｜一斧伐倒整棵树%')
                   OR (u.username='carol' AND p.content LIKE '工作台旁的配方手册%')"""):
        if row["slug"] in catalog and not summary(c,row["id"]):
            publish(c,row["id"],{"mods":list(dict.fromkeys(["fabric-api","sodium",row["slug"]]))},catalog)


def install(app, db, current, get_post, catalog, draft):
    with db.connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS pack_versions (
            id INTEGER PRIMARY KEY,pid INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
            rev INTEGER NOT NULL,digest TEXT NOT NULL,pins TEXT NOT NULL,stamp TEXT NOT NULL,UNIQUE(pid,rev));
        CREATE TABLE IF NOT EXISTS pack_trials (
            vid INTEGER REFERENCES pack_versions(id) ON DELETE CASCADE,uid INTEGER REFERENCES users(id) ON DELETE CASCADE,
            outcome TEXT NOT NULL,note TEXT NOT NULL,evidence_pid INTEGER REFERENCES posts(id) ON DELETE SET NULL,
            stamp TEXT NOT NULL, PRIMARY KEY(vid,uid));
        """)
        seed_examples(c,catalog(c))

    def version(c,pid,vid,u):
        post=get_post(c,pid,u)
        v=c.execute("SELECT * FROM pack_versions WHERE pid=? AND id=?",(pid,vid)).fetchone()
        if not v: raise HTTPException(404,"此整包版本不存在")
        return post,v

    @app.get('/api/posts/{pid}/packs/{vid}')
    def details(pid:int,vid:int,u=Depends(current)):
        with db.connect() as c:
            post,v=version(c,pid,vid,u)
            versions=[dict(x) for x in c.execute("SELECT id,rev,stamp FROM pack_versions WHERE pid=? ORDER BY rev DESC",(pid,))]
            trials=[]
            for r in c.execute("""SELECT t.*,u.nickname FROM pack_trials t JOIN users u ON u.id=t.uid
                                  WHERE vid=? ORDER BY stamp DESC LIMIT 60""",(vid,)):
                evidence=None
                if r["evidence_pid"]:
                    try:
                        linked=get_post(c,r["evidence_pid"],u)
                        if linked["visibility"]=="public" and not linked["hidden"]:
                            files=[dict(id=m[0],kind=m[1],url=f"/api/media/{m[0]}") for m in c.execute("SELECT id,kind FROM media WHERE post_id=? ORDER BY id LIMIT 3",(linked["id"],))]
                            if files:evidence={"post_id":linked["id"],"media":files}
                    except HTTPException:
                        pass
                trials.append({"nickname":r["nickname"],"outcome":r["outcome"],"note":r["note"],"stamp":r["stamp"],"evidence":evidence})
            totals=dict(c.execute("SELECT outcome,count(*) FROM pack_trials WHERE vid=? GROUP BY outcome",(vid,)).fetchall())
            return {"id":vid,"revision":v["rev"],"versions":versions,"mods":[{"slug":k,"title":m["title"],"version":m["version"]} for k,m in json.loads(v["pins"]).items()],
                    "totals":totals,"trials":trials,"title":post["content"].splitlines()[0][:60] if post["content"] else "整合包"}

    @app.post('/api/posts/{pid}/packs/{vid}/derive')
    def derive(pid:int,vid:int,u=Depends(current)):
        with db.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            post,v=version(c,pid,vid,u);old=draft(c,u);pins=json.loads(v["pins"])
            label=(post["content"].splitlines()[0][:48] if post["content"] else "整合包")+f" · v{v['rev']}"
            s={"mods":list(pins),"locks":[],"pins":pins,"history":[packed_draft(old)],"messages":[],
               "origin":{"label":label,"post_id":pid,"version_id":vid,"mods":list(pins)},"last":"已派生："+label}
            c.execute("INSERT OR REPLACE INTO drafts VALUES(?,?)",(u["id"],json.dumps(s)))
            return with_diff(s)

    @app.post('/api/posts/{pid}/packs/{vid}/trials')
    def submit_trial(pid:int,vid:int,b:Trial,u=Depends(current)):
        with db.connect() as c:
            version(c,pid,vid,u)
            note=b.note.strip()
            if not note:raise HTTPException(422,"请填写实测环境或现象")
            for w, in c.execute("SELECT word FROM sensitive_words"):note=note.replace(w,"*"*len(w))
            if b.evidence_post_id:
                p=get_post(c,b.evidence_post_id,u)
                if p["user_id"]!=u["id"] or p["visibility"]!="public" or p["hidden"] or not c.execute("SELECT 1 FROM media WHERE post_id=?",(p["id"],)).fetchone():
                    raise HTTPException(422,"证据必须是自己的公开、未下架图文或视频帖子")
            c.execute("INSERT OR REPLACE INTO pack_trials VALUES(?,?,?,?,?,?)",(vid,u["id"],b.outcome,note,b.evidence_post_id,now()))
            return {"ok":True}

