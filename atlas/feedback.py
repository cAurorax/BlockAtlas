"""Resource bookmarks, version-specific player field tests, and post reports."""
from fastapi import Depends,HTTPException
from pydantic import BaseModel,Field
from typing import Literal
from backend.security import now
class Evidence(BaseModel):
    result:Literal['成功','异常','未启动']
    note:str=Field(min_length=1,max_length=400)
    version:str=Field(min_length=1,max_length=100)
class Reason(BaseModel):
    reason:str=Field(min_length=1,max_length=250)
def install(app,db,current,admin,get_post):
    with db.connect() as c:c.executescript("""
    CREATE TABLE IF NOT EXISTS saved(uid INTEGER REFERENCES users(id) ON DELETE CASCADE,slug TEXT REFERENCES resources(slug),version TEXT NOT NULL,PRIMARY KEY(uid,slug));
    CREATE TABLE IF NOT EXISTS fieldtests(uid INTEGER REFERENCES users(id) ON DELETE CASCADE,slug TEXT REFERENCES resources(slug),version TEXT,result TEXT,note TEXT,stamp TEXT,PRIMARY KEY(uid,slug,version));
    CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY,pid INTEGER REFERENCES posts(id) ON DELETE CASCADE,uid INTEGER REFERENCES users(id) ON DELETE CASCADE,reason TEXT,stamp TEXT,done INTEGER DEFAULT 0,UNIQUE(pid,uid));
    """)
    import json
    def resource(c,k):
        r=c.execute('SELECT data FROM resources WHERE slug=?',(k,)).fetchone()
        if not r:raise HTTPException(404,'资源不存在')
        return json.loads(r[0])
    @app.get('/api/library/{slug}/notes')
    def notes(slug:str,u=Depends(current)):
        with db.connect() as c:
            v=resource(c,slug);star=c.execute('SELECT version FROM saved WHERE uid=? AND slug=?',(u['id'],slug)).fetchone()
            rows=c.execute('SELECT nickname,version,result,note,stamp FROM fieldtests JOIN users ON users.id=uid WHERE slug=? ORDER BY stamp DESC LIMIT 100',(slug,))
            return {'saved':bool(star),'changed':bool(star and star[0]!=v['id']),'notes':[dict(x) for x in rows]}
    @app.put('/api/library/{slug}/bookmark')
    def bookmark(slug:str,u=Depends(current)):
        newly=[]
        with db.connect() as c:
            row=c.execute('SELECT data FROM resources WHERE slug=?',(slug,)).fetchone()
            if row:
                v=json.loads(row[0])
            else:
                svc=getattr(app.state,'catalog_service',None)
                if not svc:raise HTTPException(404,'资源不存在')
                v,newly=svc.ensure_cached(c,slug)
        with db.connect() as c:
            if newly:app.state.catalog_service.save_entries(c,newly)
            r=c.execute('DELETE FROM saved WHERE uid=? AND slug=?',(u['id'],v['slug']))
            if not r.rowcount:c.execute('INSERT INTO saved VALUES(?,?,?)',(u['id'],v['slug'],v['id']))
            return {'saved':not bool(r.rowcount)}
    @app.get('/api/bookmarks')
    def bookmarks(u=Depends(current)):
        with db.connect() as c:return [x[0] for x in c.execute('SELECT slug FROM saved WHERE uid=?',(u['id'],))]
    @app.post('/api/library/{slug}/notes')
    def submit(slug:str,b:Evidence,u=Depends(current)):
        with db.connect() as c:
            v=resource(c,slug)
            if b.version!=v['version']:raise HTTPException(409,'资源版本已变，请刷新后提交')
            text=b.note.strip()
            if not text:raise HTTPException(422,'请填写实测条件')
            for w, in c.execute('SELECT word FROM sensitive_words'):text=text.replace(w,'*'*len(w))
            c.execute('INSERT OR REPLACE INTO fieldtests VALUES(?,?,?,?,?,?)',(u['id'],slug,b.version,b.result,text,now()))
            return {'ok':True}
    @app.post('/api/posts/{pid}/report')
    def report(pid:int,b:Reason,u=Depends(current)):
        with db.connect() as c:
            get_post(c,pid,u)
            c.execute('INSERT INTO reports(pid,uid,reason,stamp) VALUES(?,?,?,?) ON CONFLICT(pid,uid) DO UPDATE SET reason=excluded.reason,stamp=excluded.stamp,done=0',(pid,u['id'],b.reason,now()))
            return {'ok':True}
    @app.get('/api/admin/reports')
    def reports(u=Depends(admin)):
        with db.connect() as c:return [dict(r) for r in c.execute('SELECT reports.*,users.nickname,posts.content,posts.hidden FROM reports JOIN users ON users.id=uid JOIN posts ON posts.id=pid ORDER BY done,stamp DESC LIMIT 150')]
    @app.post('/api/admin/reports/{rid}/close')
    def close(rid:int,u=Depends(admin)):
        with db.connect() as c:
            if not c.execute('UPDATE reports SET done=1 WHERE id=?',(rid,)).rowcount:raise HTTPException(404,'举报不存在')
            c.execute('INSERT INTO audit_logs(actor_id,action,target,created_at) VALUES(?,?,?,?)',(u['id'],'处理举报',str(rid),now()))
            return {'ok':True}

