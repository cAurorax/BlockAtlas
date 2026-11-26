"""Friend chat: plain messages, whole-draft sharing, and co-op invites.

Only accepted friends can talk. Sharing a draft stores a snapshot of the sender's
mod list, so the receiver can merge it later without depending on the sender's
current workspace.
"""
import json
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from backend.security import now

SCHEMA = """
CREATE TABLE IF NOT EXISTS chat(
 id INTEGER PRIMARY KEY,
 sender INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 receiver INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 kind TEXT NOT NULL,
 body TEXT NOT NULL DEFAULT '',
 payload TEXT NOT NULL DEFAULT '{}',
 status TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL,
 read_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_chat_pair ON chat(sender,receiver,id);
CREATE INDEX IF NOT EXISTS idx_chat_inbox ON chat(receiver,read_at);
CREATE TABLE IF NOT EXISTS rooms(
 id INTEGER PRIMARY KEY,
 name TEXT NOT NULL,
 owner INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS room_members(
 room INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
 uid INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 joined_at TEXT NOT NULL,
 PRIMARY KEY(room,uid)
);
CREATE TABLE IF NOT EXISTS room_messages(
 id INTEGER PRIMARY KEY,
 room INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
 sender INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 kind TEXT NOT NULL,
 body TEXT NOT NULL DEFAULT '',
 payload TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_room_msg ON room_messages(room,id);
CREATE TABLE IF NOT EXISTS room_reads(
 room INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
 uid INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 last_read INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(room,uid)
);
"""


class Text(BaseModel):
    body: str = Field(min_length=1, max_length=1000)


class Invite(BaseModel):
    address: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=200)


class Reply(BaseModel):
    action: Literal["accept", "decline"]


class Fill(BaseModel):
    slugs: list[str] = Field(default_factory=list, max_length=100)


class Room(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    members: list[int] = Field(default_factory=list, max_length=20)


class RoomAdd(BaseModel):
    uid: int


def install(app, db, current, all_mods, draft_of, merge_shared):
    with db.connect() as con:
        con.executescript(SCHEMA)

    def are_friends(con, a, b):
        return (
            con.execute(
                "SELECT 1 FROM friends WHERE status='accepted' AND "
                "((requester=? AND receiver=?) OR (requester=? AND receiver=?))",
                (a, b, b, a),
            ).fetchone()
            is not None
        )

    def peer(con, uid):
        row = con.execute("SELECT id,nickname,username FROM users WHERE id=?", (uid,)).fetchone()
        if not row:
            raise HTTPException(404, "玩家不存在")
        return dict(row)

    def guard(con, user, uid):
        if uid == user["id"]:
            raise HTTPException(422, "不能和自己聊天")
        other = peer(con, uid)
        if not are_friends(con, user["id"], uid):
            raise HTTPException(403, "只有好友之间可以聊天")
        return other

    def row_out(row, me):
        message = dict(row)
        message["payload"] = json.loads(message.get("payload") or "{}")
        message["mine"] = message["sender"] == me
        message["unread"] = message["receiver"] == me and not message["read_at"]
        return message

    def insert(con, sender, receiver, kind, body="", payload=None, status=""):
        con.execute(
            "INSERT INTO chat(sender,receiver,kind,body,payload,status,created_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (sender, receiver, kind, body, json.dumps(payload or {}, ensure_ascii=False), status, now()),
        )
        return con.execute("SELECT * FROM chat WHERE id=last_insert_rowid()").fetchone()

    def pack_diff(con, user, payload):
        """Compare a shared pack snapshot with my current draft."""
        from .conflicts import build as build_graph

        catalog = all_mods(con)
        draft = draft_of(con, user)
        mine_slugs = list(draft["mods"])
        mine = set(mine_slugs)
        theirs = [m for m in (payload.get("mods") or []) if m.get("slug")]
        theirs_by = {m["slug"]: m for m in theirs}

        def describe(slug, theirs_mod=None):
            src = theirs_mod or catalog.get(slug) or {}
            return {
                "slug": slug,
                "title": src.get("title") or catalog.get(slug, {}).get("title") or slug,
                "version": src.get("version") or "",
                "icon": src.get("icon") or "",
            }

        only_theirs = [
            {**describe(m["slug"], m), "in_library": m["slug"] in catalog}
            for m in theirs
            if m["slug"] not in mine
        ]
        only_mine = [describe(s) for s in mine_slugs if s not in theirs_by]
        version_diff = [
            {
                **describe(s),
                "theirs_version": theirs_by[s].get("version") or "",
                "mine_version": (catalog.get(s) or {}).get("version") or "",
            }
            for s in mine_slugs
            if s in theirs_by
            and theirs_by[s].get("version")
            and (catalog.get(s) or {}).get("version")
            and theirs_by[s]["version"] != catalog[s]["version"]
        ]
        different = {item["slug"] for item in version_diff}
        same = sorted((mine & theirs_by.keys()) - different)

        # Would filling every missing mod create a declared conflict?
        candidate = list(dict.fromkeys(mine_slugs + [m["slug"] for m in only_theirs]))
        risks = build_graph(catalog, candidate)["draft_conflicts"]
        return {
            "label": payload.get("label") or "分享包",
            "mine_count": len(mine_slugs),
            "theirs_count": len(theirs),
            "only_theirs": only_theirs,
            "only_mine": only_mine,
            "version_diff": version_diff,
            "same": same,
            "risks": [
                {"a": e["a"], "b": e["b"], "a_title": e["a_title"], "b_title": e["b_title"]}
                for e in risks
            ],
        }

    def fill_pick(con, user, payload, slugs, label):
        """Merge only the picked mods from a shared pack (defaults to all)."""
        theirs = {m["slug"] for m in (payload.get("mods") or []) if m.get("slug")}
        picked = [s for s in dict.fromkeys(slugs or theirs) if s in theirs]
        if not picked:
            raise HTTPException(422, "没有可补齐的组件")
        return merge_shared(con, user, picked, label)

    @app.get("/api/chat/threads")
    def threads(user=Depends(current)):
        with db.connect() as con:
            rows = con.execute(
                "SELECT id,requester,receiver FROM friends WHERE status='accepted'"
                " AND (requester=? OR receiver=?)",
                (user["id"], user["id"]),
            ).fetchall()
            out = []
            for row in rows[:50]:
                uid = row["receiver"] if row["requester"] == user["id"] else row["requester"]
                info = con.execute("SELECT id,nickname,username FROM users WHERE id=?", (uid,)).fetchone()
                if not info:
                    continue
                last = con.execute(
                    "SELECT * FROM chat WHERE (sender=? AND receiver=?) OR (sender=? AND receiver=?)"
                    " ORDER BY id DESC LIMIT 1",
                    (user["id"], uid, uid, user["id"]),
                ).fetchone()
                unread = con.execute(
                    "SELECT count(*) FROM chat WHERE sender=? AND receiver=? AND read_at IS NULL",
                    (uid, user["id"]),
                ).fetchone()[0]
                out.append(
                    {
                        "user": dict(info),
                        "unread": unread,
                        "last": ({"kind": last["kind"], "body": last["body"], "created_at": last["created_at"]}
                                 if last else None),
                    }
                )
            out.sort(key=lambda t: (t["last"] or {}).get("created_at") or "", reverse=True)
            return out

    @app.get("/api/chat/{uid}")
    def history(uid: int, user=Depends(current)):
        with db.connect() as con:
            other = guard(con, user, uid)
            rows = con.execute(
                "SELECT * FROM chat WHERE (sender=? AND receiver=?) OR (sender=? AND receiver=?)"
                " ORDER BY id DESC LIMIT 80",
                (user["id"], uid, uid, user["id"]),
            ).fetchall()
            con.execute(
                "UPDATE chat SET read_at=? WHERE receiver=? AND sender=? AND read_at IS NULL",
                (now(), user["id"], uid),
            )
            return {"friend": other, "messages": [row_out(r, user["id"]) for r in reversed(rows)]}

    @app.post("/api/chat/{uid}")
    def send(uid: int, body: Text, user=Depends(current)):
        with db.connect() as con:
            guard(con, user, uid)
            return row_out(insert(con, user["id"], uid, "text", body.body.strip()), user["id"])

    @app.post("/api/chat/{uid}/pack")
    def share_pack(uid: int, user=Depends(current)):
        with db.connect() as con:
            guard(con, user, uid)
            row = insert(con, user["id"], uid, "pack", "分享了一个整合包", snapshot(con, user))
            return row_out(row, user["id"])

    @app.post("/api/chat/{uid}/invite")
    def invite(uid: int, body: Invite, user=Depends(current)):
        with db.connect() as con:
            guard(con, user, uid)
            payload = {"address": body.address.strip(), "note": body.note.strip()}
            row = insert(con, user["id"], uid, "invite", "邀请一起玩", payload, status="pending")
            return row_out(row, user["id"])

    @app.post("/api/chat/{uid}/invite/{mid}/respond")
    def respond(uid: int, mid: int, body: Reply, user=Depends(current)):
        with db.connect() as con:
            guard(con, user, uid)
            row = con.execute("SELECT * FROM chat WHERE id=?", (mid,)).fetchone()
            if not row or row["kind"] != "invite" or row["receiver"] != user["id"] or row["sender"] != uid:
                raise HTTPException(404, "邀请不存在")
            if row["status"] != "pending":
                raise HTTPException(409, "这条邀请已经处理过了")
            if body.action == "accept" and not are_friends(con, user["id"], uid):
                raise HTTPException(403, "只有好友之间可以加入")
            con.execute(
                "UPDATE chat SET status=?, read_at=coalesce(read_at,?) WHERE id=?",
                ("accepted" if body.action == "accept" else "declined", now(), mid),
            )
            return {"status": body.action}

    @app.post("/api/chat/{uid}/pack/{mid}/import")
    def import_pack(uid: int, mid: int, user=Depends(current)):
        with db.connect() as con:
            guard(con, user, uid)
            row = con.execute("SELECT * FROM chat WHERE id=?", (mid,)).fetchone()
            if not row or row["kind"] != "pack" or row["sender"] != uid or row["receiver"] != user["id"]:
                raise HTTPException(404, "这个整合包分享不存在")
            payload = json.loads(row["payload"] or "{}")
            slugs = [m["slug"] for m in payload.get("mods") or [] if m.get("slug")]
            return merge_shared(con, user, slugs, payload.get("label") or "好友分享")

    @app.get("/api/chat/{uid}/pack/{mid}/compare")
    def compare_pack(uid: int, mid: int, user=Depends(current)):
        with db.connect() as con:
            guard(con, user, uid)
            row = con.execute("SELECT * FROM chat WHERE id=?", (mid,)).fetchone()
            if not row or row["kind"] != "pack" or row["sender"] != uid or row["receiver"] != user["id"]:
                raise HTTPException(404, "这个整合包分享不存在")
            return pack_diff(con, user, json.loads(row["payload"] or "{}"))

    @app.post("/api/chat/{uid}/pack/{mid}/fill")
    def fill_pack(uid: int, mid: int, body: Fill, user=Depends(current)):
        with db.connect() as con:
            guard(con, user, uid)
            row = con.execute("SELECT * FROM chat WHERE id=?", (mid,)).fetchone()
            if not row or row["kind"] != "pack" or row["sender"] != uid or row["receiver"] != user["id"]:
                raise HTTPException(404, "这个整合包分享不存在")
            payload = json.loads(row["payload"] or "{}")
            return fill_pick(con, user, payload, body.slugs, payload.get("label") or "好友分享")

    # ---------------------------------------------------------------- 群聊
    def snapshot(con, user):
        draft = draft_of(con, user)
        if not draft["mods"]:
            raise HTTPException(422, "当前整合包是空的，没有可分享的内容")
        catalog = all_mods(con)
        return {
            "label": draft.get("origin", {}).get("label") or "我的整合包",
            "mods": [
                {
                    "slug": slug,
                    "title": catalog[slug]["title"] if slug in catalog else slug,
                    "version": catalog[slug]["version"] if slug in catalog else "",
                    "icon": (catalog[slug].get("icon") or "") if slug in catalog else "",
                }
                for slug in draft["mods"]
            ],
            "locks": list(draft.get("locks") or []),
        }

    def room_of(con, rid, uid, owner_only=False):
        room = con.execute("SELECT * FROM rooms WHERE id=?", (rid,)).fetchone()
        if not room:
            raise HTTPException(404, "群聊不存在")
        if not con.execute("SELECT 1 FROM room_members WHERE room=? AND uid=?", (rid, uid)).fetchone():
            raise HTTPException(403, "你不在这个群聊里")
        if owner_only and room["owner"] != uid:
            raise HTTPException(403, "只有群主可以操作")
        members = [
            dict(r)
            for r in con.execute(
                "SELECT u.id,u.nickname,u.username FROM room_members m JOIN users u ON u.id=m.uid"
                " WHERE m.room=? ORDER BY m.joined_at",
                (rid,),
            )
        ]
        return dict(room), members

    def room_say(con, rid, sender, kind, body="", payload=None):
        con.execute(
            "INSERT INTO room_messages(room,sender,kind,body,payload,created_at) VALUES(?,?,?,?,?,?)",
            (rid, sender, kind, body, json.dumps(payload or {}, ensure_ascii=False), now()),
        )
        return con.execute("SELECT * FROM room_messages WHERE id=last_insert_rowid()").fetchone()

    def out(row, me):
        message = dict(row)
        message["payload"] = json.loads(message.get("payload") or "{}")
        message["mine"] = message["sender"] == me
        return message

    def unread(con, rid, uid):
        return con.execute(
            "SELECT count(*) FROM room_messages WHERE room=? AND sender<>? AND id>coalesce("
            "(SELECT last_read FROM room_reads WHERE room=? AND uid=?),0)",
            (rid, uid, rid, uid),
        ).fetchone()[0]

    @app.post("/api/rooms", status_code=201)
    def create_room(body: Room, user=Depends(current)):
        name = body.name.strip()
        if not name:
            raise HTTPException(422, "请给群聊起个名字")
        with db.connect() as con:
            members = []
            for uid in dict.fromkeys(int(x) for x in body.members):
                if uid == user["id"] or uid in members:
                    continue
                peer(con, uid)
                if not are_friends(con, user["id"], uid):
                    raise HTTPException(403, "只能邀请好友加入群聊")
                members.append(uid)
            rid = con.execute(
                "INSERT INTO rooms(name,owner,created_at) VALUES(?,?,?)", (name, user["id"], now())
            ).lastrowid
            for uid in [user["id"]] + members:
                con.execute("INSERT INTO room_members(room,uid,joined_at) VALUES(?,?,?)", (rid, uid, now()))
            return {"id": rid, "name": name}

    @app.get("/api/rooms")
    def my_rooms(user=Depends(current)):
        with db.connect() as con:
            rows = con.execute(
                "SELECT r.* FROM rooms r JOIN room_members m ON m.room=r.id WHERE m.uid=?"
                " ORDER BY r.id DESC",
                (user["id"],),
            ).fetchall()
            out_rows = []
            for room in rows:
                _, members = room_of(con, room["id"], user["id"])
                last = con.execute(
                    "SELECT * FROM room_messages WHERE room=? ORDER BY id DESC LIMIT 1", (room["id"],)
                ).fetchone()
                out_rows.append(
                    {
                        "id": room["id"],
                        "name": room["name"],
                        "owner": room["owner"],
                        "members": members,
                        "unread": unread(con, room["id"], user["id"]),
                        "last": ({"kind": last["kind"], "body": last["body"], "created_at": last["created_at"]}
                                 if last else None),
                    }
                )
            return out_rows

    @app.get("/api/rooms/{rid}")
    def room_history(rid: int, user=Depends(current)):
        with db.connect() as con:
            room, members = room_of(con, rid, user["id"])
            rows = con.execute(
                "SELECT * FROM room_messages WHERE room=? ORDER BY id DESC LIMIT 80", (rid,)
            ).fetchall()
            newest = rows[0]["id"] if rows else 0
            con.execute(
                "INSERT INTO room_reads(room,uid,last_read) VALUES(?,?,?)"
                " ON CONFLICT(room,uid) DO UPDATE SET last_read=max(last_read,excluded.last_read)",
                (rid, user["id"], newest),
            )
            return {
                "room": {
                    "id": room["id"],
                    "name": room["name"],
                    "owner": room["owner"],
                    "members": members,
                },
                "messages": [out(r, user["id"]) for r in reversed(rows)],
            }

    @app.post("/api/rooms/{rid}")
    def room_send(rid: int, body: Text, user=Depends(current)):
        with db.connect() as con:
            room_of(con, rid, user["id"])
            return out(room_say(con, rid, user["id"], "text", body.body.strip()), user["id"])

    @app.post("/api/rooms/{rid}/pack")
    def room_share(rid: int, user=Depends(current)):
        with db.connect() as con:
            room_of(con, rid, user["id"])
            return out(room_say(con, rid, user["id"], "pack", "分享了一个整合包", snapshot(con, user)), user["id"])

    @app.post("/api/rooms/{rid}/invite")
    def room_invite(rid: int, body: Invite, user=Depends(current)):
        with db.connect() as con:
            room_of(con, rid, user["id"])
            payload = {"address": body.address.strip(), "note": body.note.strip()}
            return out(room_say(con, rid, user["id"], "invite", "邀请一起玩", payload), user["id"])

    @app.post("/api/rooms/{rid}/pack/{mid}/import")
    def room_import(rid: int, mid: int, user=Depends(current)):
        with db.connect() as con:
            room_of(con, rid, user["id"])
            row = con.execute("SELECT * FROM room_messages WHERE id=? AND room=?", (mid, rid)).fetchone()
            if not row or row["kind"] != "pack":
                raise HTTPException(404, "这个整合包分享不存在")
            payload = json.loads(row["payload"] or "{}")
            slugs = [m["slug"] for m in payload.get("mods") or [] if m.get("slug")]
            return merge_shared(con, user, slugs, payload.get("label") or "群聊分享")

    @app.get("/api/rooms/{rid}/pack/{mid}/compare")
    def room_compare(rid: int, mid: int, user=Depends(current)):
        with db.connect() as con:
            room_of(con, rid, user["id"])
            row = con.execute("SELECT * FROM room_messages WHERE id=? AND room=?", (mid, rid)).fetchone()
            if not row or row["kind"] != "pack":
                raise HTTPException(404, "这个整合包分享不存在")
            return pack_diff(con, user, json.loads(row["payload"] or "{}"))

    @app.post("/api/rooms/{rid}/pack/{mid}/fill")
    def room_fill(rid: int, mid: int, body: Fill, user=Depends(current)):
        with db.connect() as con:
            room_of(con, rid, user["id"])
            row = con.execute("SELECT * FROM room_messages WHERE id=? AND room=?", (mid, rid)).fetchone()
            if not row or row["kind"] != "pack":
                raise HTTPException(404, "这个整合包分享不存在")
            payload = json.loads(row["payload"] or "{}")
            return fill_pick(con, user, payload, body.slugs, payload.get("label") or "群聊分享")

    @app.post("/api/rooms/{rid}/members")
    def room_add(rid: int, body: RoomAdd, user=Depends(current)):
        with db.connect() as con:
            room_of(con, rid, user["id"], owner_only=True)
            peer(con, body.uid)
            if not are_friends(con, user["id"], body.uid):
                raise HTTPException(403, "只能邀请好友加入群聊")
            if con.execute("SELECT 1 FROM room_members WHERE room=? AND uid=?", (rid, body.uid)).fetchone():
                raise HTTPException(409, "对方已经在群里了")
            con.execute("INSERT INTO room_members(room,uid,joined_at) VALUES(?,?,?)", (rid, body.uid, now()))
            return {"ok": True}

    @app.post("/api/rooms/{rid}/leave")
    def room_leave(rid: int, user=Depends(current)):
        with db.connect() as con:
            room, _ = room_of(con, rid, user["id"])
            if room["owner"] == user["id"]:
                raise HTTPException(422, "群主不能直接退出，请先把群聊交给别人或等其他人退出")
            con.execute("DELETE FROM room_members WHERE room=? AND uid=?", (rid, user["id"]))
            return {"ok": True}
