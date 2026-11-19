"""拾光圈 REST API and static Web clients. Run: uvicorn backend.main:app."""

import io
import os
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError

from .db import Database
from .models import (
    CommentInput,
    Credentials,
    FriendDecision,
    FriendInput,
    PasswordChange,
    PostInput,
    RatingInput,
    Registration,
    ToggleInput,
    WordInput,
)
from .security import (
    can_view_post,
    expires,
    hash_password,
    now,
    token_hash,
    verify_password,
)

ROOT = Path(__file__).resolve().parent.parent
MAX_UPLOAD = 50 * 1024 * 1024


def public_user(user):
    return {
        key: user[key]
        for key in (
            "id",
            "username",
            "nickname",
            "role",
            "disabled",
            "created_at",
            "last_active",
        )
    }


def create_app(data_dir=None, extension=None):
    data = Path(data_dir or os.getenv("SHIGUANG_DATA_DIR", ROOT / "data"))
    uploads = data / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    db = Database(data / "shiguang.db")
    db.initialize()
    app = FastAPI(
        title="拾光圈 API", version="1.0.0", description="多媒体分享与管理系统"
    )
    app.state.db = db
    app.state.uploads = uploads
    cookie_name = "atlas_session" if extension else "session"
    attempts = defaultdict(deque)
    login_lock = threading.Lock()

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(sqlite3.IntegrityError)
    async def conflict(request, exc):
        return JSONResponse(
            status_code=409, content={"detail": "数据冲突，请刷新后重试"}
        )

    def current_user(request: Request):
        auth = request.headers.get("Authorization", "")
        token = (
            auth[7:]
            if auth.startswith("Bearer ")
            else request.cookies.get(cookie_name, "")
        )
        # Native media components cannot attach headers; the revocable session token is accepted for media only.
        if request.url.path.startswith("/api/media/") and request.query_params.get("token") and not auth and (extension or not token):
            token = request.query_params.get("token", "")
        with db.connect() as con:
            user = con.execute(
                "SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token_hash=? AND s.expires_at>?",
                (token_hash(token), now()),
            ).fetchone()
            if not user or user["disabled"]:
                raise HTTPException(401, "请先登录，或账号已被停用")
            con.execute(
                "UPDATE users SET last_active=? WHERE id=?", (now(), user["id"])
            )
            return dict(user)

    def admin(user=Depends(current_user)):
        if user["role"] != "admin":
            raise HTTPException(403, "需要管理员权限")
        return user

    def audit(con, user, action, target):
        con.execute(
            "INSERT INTO audit_logs(actor_id,action,target,created_at) VALUES(?,?,?,?)",
            (user["id"], action, str(target), now()),
        )

    def filter_text(con, text):
        for row in con.execute(
            "SELECT word FROM sensitive_words ORDER BY length(word) DESC"
        ):
            text = text.replace(row[0], "*" * len(row[0]))
        return text

    def friends(con, a, b):
        return (
            con.execute(
                "SELECT 1 FROM friends WHERE status='accepted' AND ((requester=? AND receiver=?) OR (requester=? AND receiver=?))",
                (a, b, b, a),
            ).fetchone()
            is not None
        )

    def visible(con, post, user):
        return can_view_post(post, user, friends(con, post["user_id"], user["id"]))

    def get_post(con, post_id, user, owner=False):
        post = con.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
        if not post or not visible(con, post, user):
            raise HTTPException(404, "动态不存在或无权查看")
        if owner and post["user_id"] != user["id"]:
            raise HTTPException(403, "只能修改自己的动态")
        return post

    def serialize(con, post, user):
        result = dict(post)
        if extension: result.update(app.state.link_read(con,post["id"]))
        author = con.execute(
            "SELECT nickname,username FROM users WHERE id=?", (post["user_id"],)
        ).fetchone()
        result.update(dict(author))
        result["tags"] = [
            r[0]
            for r in con.execute(
                "SELECT name FROM tags WHERE post_id=? ORDER BY name", (post["id"],)
            )
        ]
        result["media"] = [
            dict(r) | {"url": f"/api/media/{r['id']}"}
            for r in con.execute(
                "SELECT id,kind,mime,size FROM media WHERE post_id=? ORDER BY id",
                (post["id"],),
            )
        ]
        score = con.execute(
            "SELECT count(*),coalesce(avg(score),0) FROM ratings WHERE post_id=?",
            (post["id"],),
        ).fetchone()
        result["rating_count"], result["rating_avg"] = score[0], round(score[1], 1)
        mine = con.execute(
            "SELECT score FROM ratings WHERE post_id=? AND user_id=?",
            (post["id"], user["id"]),
        ).fetchone()
        result["my_rating"] = mine[0] if mine else 0
        result["comment_count"] = con.execute(
            "SELECT count(*) FROM comments WHERE post_id=?", (post["id"],)
        ).fetchone()[0]
        return result

    def save_post(con, body, user, post_id=None):
        if not body.content.strip() and not body.media_ids:
            raise HTTPException(422, "文字和媒体至少填写一项")
        if len(set(body.media_ids)) != len(body.media_ids):
            raise HTTPException(422, "不能重复添加同一媒体")
        for media_id in body.media_ids:
            media = con.execute(
                "SELECT * FROM media WHERE id=?", (media_id,)
            ).fetchone()
            if (
                not media
                or media["user_id"] != user["id"]
                or media["post_id"] not in (None, post_id)
            ):
                raise HTTPException(403, "媒体不存在、不属于本人或已被其他动态使用")
        content = filter_text(con, body.content.strip())
        if post_id is None:
            post_id = con.execute(
                "INSERT INTO posts(user_id,content,visibility,created_at,updated_at) VALUES(?,?,?,?,?)",
                (user["id"], content, body.visibility, now(), now()),
            ).lastrowid
        else:
            con.execute(
                "UPDATE posts SET content=?,visibility=?,updated_at=? WHERE id=?",
                (content, body.visibility, now(), post_id),
            )
            con.execute("DELETE FROM tags WHERE post_id=?", (post_id,))
            con.execute("UPDATE media SET post_id=NULL WHERE post_id=?", (post_id,))
        con.executemany(
            "INSERT INTO tags VALUES(?,?)",
            [
                (post_id, tag)
                for tag in dict.fromkeys(filter_text(con, t) for t in body.tags)
            ],
        )
        con.executemany(
            "UPDATE media SET post_id=? WHERE id=?",
            [(post_id, mid) for mid in body.media_ids],
        )
        if extension: app.state.link_save(con,post_id,body)
        return serialize(con, get_post(con, post_id, user), user)

    def remove_files(filenames):
        for name in filenames:
            (uploads / name).unlink(missing_ok=True)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "1.0.0"}

    @app.post("/api/auth/register", status_code=201)
    def register(body: Registration):
        with db.connect() as con:
            if con.execute(
                "SELECT 1 FROM users WHERE username=?", (body.username,)
            ).fetchone():
                raise HTTPException(409, "用户名已存在")
            uid = con.execute(
                "INSERT INTO users(username,nickname,password,created_at,last_active) VALUES(?,?,?,?,?)",
                (
                    body.username,
                    filter_text(con, body.nickname),
                    hash_password(body.password),
                    now(),
                    now(),
                ),
            ).lastrowid
            return public_user(
                con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            )

    @app.post("/api/auth/login")
    def login(body: Credentials, request: Request):
        key = request.client.host if request.client else "local"
        with login_lock:
            queue = attempts[key]
            while queue and queue[0] < time.monotonic() - 60:
                queue.popleft()
            if len(queue) >= 20:
                raise HTTPException(429, "尝试过于频繁，请一分钟后重试")
            queue.append(time.monotonic())
        with db.connect() as con:
            user = con.execute(
                "SELECT * FROM users WHERE username=?", (body.username,)
            ).fetchone()
            if (
                not user
                or not verify_password(body.password, user["password"])
                or user["disabled"]
            ):
                raise HTTPException(401, "用户名、密码错误或账号已停用")
            token = secrets.token_urlsafe(32)
            con.execute("DELETE FROM sessions WHERE expires_at<=?", (now(),))
            con.execute(
                "INSERT INTO sessions VALUES(?,?,?)",
                (token_hash(token), user["id"], expires()),
            )
            con.execute(
                "UPDATE users SET last_active=? WHERE id=?", (now(), user["id"])
            )
            response = JSONResponse({"token": token, "user": public_user(user)})
            response.set_cookie(
                cookie_name,
                token,
                httponly=True,
                samesite="strict",
                secure=request.url.scheme == "https",
                max_age=604800,
            )
            return response

    @app.get("/api/auth/me")
    def me(user=Depends(current_user)):
        return public_user(user)

    @app.post("/api/auth/logout")
    def logout(request: Request, user=Depends(current_user)):
        token = request.headers.get("Authorization", "").removeprefix(
            "Bearer "
        ) or request.cookies.get(cookie_name, "")
        with db.connect() as con:
            con.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),))
        response = JSONResponse({"ok": True})
        response.delete_cookie(cookie_name)
        return response

    @app.put("/api/auth/password")
    def change_password(body: PasswordChange, user=Depends(current_user)):
        if not verify_password(body.old_password, user["password"]):
            raise HTTPException(400, "原密码错误")
        with db.connect() as con:
            con.execute(
                "UPDATE users SET password=? WHERE id=?",
                (hash_password(body.new_password), user["id"]),
            )
            con.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
        return {"ok": True, "message": "密码已更新，请重新登录"}

    @app.post("/api/media", status_code=201)
    async def upload(file: UploadFile, user=Depends(current_user)):
        content = bytearray()
        while chunk := await file.read(1024 * 1024):
            content.extend(chunk)
            if len(content) > MAX_UPLOAD:
                raise HTTPException(413, "文件不能超过 50 MB")
        raw = bytes(content)
        if (
            raw[4:8] == b"ftyp"
            and len(raw) >= 24
            and raw[8:12]
            in (b"isom", b"iso2", b"mp41", b"mp42", b"avc1", b"M4V ", b"MSNV", b"dash")
        ):
            kind, mime, suffix = "video", "video/mp4", ".mp4"
        else:
            try:
                with Image.open(io.BytesIO(raw)) as picture:
                    if picture.width * picture.height > 25000000:
                        raise HTTPException(413, "图片不能超过 2500 万像素")
                    fmt = picture.format
                    picture.verify()
                formats = {
                    "JPEG": ("image/jpeg", ".jpg"),
                    "PNG": ("image/png", ".png"),
                    "WEBP": ("image/webp", ".webp"),
                    "GIF": ("image/gif", ".gif"),
                }
                if fmt not in formats:
                    raise ValueError()
                mime, suffix = formats[fmt]
                kind = "image"
            except (
                UnidentifiedImageError,
                OSError,
                ValueError,
                Image.DecompressionBombError,
            ):
                raise HTTPException(415, "只支持 JPG、PNG、WebP、GIF 图片或 MP4 视频")
        filename = secrets.token_hex(20) + suffix
        target = uploads / filename
        target.write_bytes(raw)
        try:
            with db.connect() as con:
                mid = con.execute(
                    "INSERT INTO media(user_id,filename,kind,mime,size,created_at) VALUES(?,?,?,?,?,?)",
                    (user["id"], filename, kind, mime, len(raw), now()),
                ).lastrowid
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return {"id": mid, "kind": kind, "url": f"/api/media/{mid}", "size": len(raw)}

    @app.get("/api/media/{media_id}")
    def read_media(media_id: int, user=Depends(current_user)):
        with db.connect() as con:
            media = con.execute(
                "SELECT * FROM media WHERE id=?", (media_id,)
            ).fetchone()
            if not media:
                raise HTTPException(404, "媒体不存在")
            if media["post_id"]:
                get_post(con, media["post_id"], user)
            elif media["user_id"] != user["id"] and user["role"] != "admin":
                raise HTTPException(404, "媒体不存在")
            path = uploads / media["filename"]
            if not path.exists():
                raise HTTPException(404, "媒体文件缺失")
            return FileResponse(
                path,
                media_type=media["mime"],
                headers={"Cache-Control": "private, no-store"},
            )

    @app.get("/api/posts")
    def list_posts(
        q: str = "",
        tag: str = "",
        start: date | None = None,
        end: date | None = None,
        scope: str = Query("all", pattern="^(all|mine|friends)$"),
        author_id: int | None = Query(None, ge=1),
        page: int = Query(1, ge=1),
        page_size: int = Query(12, ge=1, le=50),
        user=Depends(current_user),
    ):
        if start and end and start > end:
            raise HTTPException(422, "开始日期不能晚于结束日期")
        clauses, params = ["1=1"], []
        if q:
            clauses.append("p.content LIKE ?")
            params.append(f"%{q}%")
        if tag:
            clauses.append(
                "EXISTS(SELECT 1 FROM tags t WHERE t.post_id=p.id AND t.name=?)"
            )
            params.append(tag)
        # Dates in the UI are Asia/Shanghai dates; timestamps are stored as UTC.
        for value, op, offset in ((start, ">=", 0), (end, "<", 1)):
            if value:
                local = datetime.combine(
                    value + timedelta(days=offset),
                    datetime.min.time(),
                    timezone(timedelta(hours=8)),
                )
                clauses.append(f"p.created_at {op} ?")
                params.append(
                    local.astimezone(timezone.utc).isoformat(timespec="seconds")
                )
        if author_id is not None:
            clauses.append("p.user_id=?")
            params.append(author_id)
        if scope == "mine":
            clauses.append("p.user_id=?")
            params.append(user["id"])
        with db.connect() as con:
            rows = con.execute(
                "SELECT p.* FROM posts p WHERE "
                + " AND ".join(clauses)
                + " ORDER BY p.created_at DESC,p.id DESC",
                params,
            ).fetchall()
            rows = [
                p
                for p in rows
                if visible(con, p, user)
                and (scope != "friends" or friends(con, p["user_id"], user["id"]))
            ]
            return {
                "items": [
                    serialize(con, p, user)
                    for p in rows[(page - 1) * page_size : page * page_size]
                ],
                "total": len(rows),
                "page": page,
                "page_size": page_size,
            }

    @app.get("/api/posts/{post_id}")
    def post_detail(post_id: int, user=Depends(current_user)):
        with db.connect() as con:
            return serialize(con, get_post(con, post_id, user), user)

    @app.post("/api/posts", status_code=201)
    def create_post(body: PostInput, user=Depends(current_user)):
        with db.connect() as con:
            return save_post(con, body, user)

    @app.put("/api/posts/{post_id}")
    def update_post(post_id: int, body: PostInput, user=Depends(current_user)):
        with db.connect() as con:
            get_post(con, post_id, user, owner=True)
            return save_post(con, body, user, post_id)

    @app.delete("/api/posts/{post_id}")
    def delete_post(post_id: int, user=Depends(current_user)):
        with db.connect() as con:
            get_post(con, post_id, user, owner=user["role"] != "admin")
            files = [
                r[0]
                for r in con.execute(
                    "SELECT filename FROM media WHERE post_id=?", (post_id,)
                )
            ]
            con.execute("DELETE FROM posts WHERE id=?", (post_id,))
            audit(con, user, "delete_post", post_id)
        remove_files(files)
        return {"ok": True}

    @app.get("/api/posts/{post_id}/comments")
    def comments(post_id: int, user=Depends(current_user)):
        with db.connect() as con:
            get_post(con, post_id, user)
            return [
                dict(r)
                for r in con.execute(
                    "SELECT c.*,u.nickname FROM comments c JOIN users u ON c.user_id=u.id WHERE post_id=? ORDER BY c.id",
                    (post_id,),
                )
            ]

    @app.post("/api/posts/{post_id}/comments", status_code=201)
    def add_comment(post_id: int, body: CommentInput, user=Depends(current_user)):
        with db.connect() as con:
            post = get_post(con, post_id, user)
            if post["hidden"]:
                raise HTTPException(403, "已下架动态不能评论")
            if not body.content.strip():
                raise HTTPException(422, "评论不能为空")
            if (
                body.parent_id
                and not con.execute(
                    "SELECT 1 FROM comments WHERE id=? AND post_id=?",
                    (body.parent_id, post_id),
                ).fetchone()
            ):
                raise HTTPException(422, "回复目标不属于此动态")
            cid = con.execute(
                "INSERT INTO comments(post_id,user_id,content,parent_id,created_at) VALUES(?,?,?,?,?)",
                (
                    post_id,
                    user["id"],
                    filter_text(con, body.content.strip()),
                    body.parent_id,
                    now(),
                ),
            ).lastrowid
            return {"id": cid}

    @app.delete("/api/comments/{comment_id}")
    def delete_comment(comment_id: int, user=Depends(current_user)):
        with db.connect() as con:
            row = con.execute(
                "SELECT * FROM comments WHERE id=?", (comment_id,)
            ).fetchone()
            if not row:
                raise HTTPException(404, "评论不存在")
            post = get_post(con, row["post_id"], user)
            if user["role"] != "admin" and user["id"] not in (
                row["user_id"],
                post["user_id"],
            ):
                raise HTTPException(403, "不能删除此评论")
            con.execute("DELETE FROM comments WHERE id=?", (comment_id,))
            return {"ok": True}

    @app.put("/api/posts/{post_id}/rating")
    def rate(post_id: int, body: RatingInput, user=Depends(current_user)):
        with db.connect() as con:
            post = get_post(con, post_id, user)
            if post["user_id"] == user["id"] or post["hidden"]:
                raise HTTPException(403, "不能评价自己或已下架的动态")
            con.execute(
                "INSERT INTO ratings VALUES(?,?,?) ON CONFLICT(post_id,user_id) DO UPDATE SET score=excluded.score",
                (post_id, user["id"], body.score),
            )
            return serialize(con, post, user)

    @app.get("/api/users/search")
    def search_users(q: str = Query("", max_length=30), user=Depends(current_user)):
        with db.connect() as con:
            return [
                dict(r)
                for r in con.execute(
                    "SELECT id,username,nickname FROM users WHERE disabled=0 AND role='user' AND id!=? AND (username LIKE ? OR nickname LIKE ?) LIMIT 30",
                    (user["id"], f"%{q}%", f"%{q}%"),
                )
            ]

    @app.get("/api/players/{uid}")
    def player_home(uid: int, user=Depends(current_user)):
        with db.connect() as con:
            player = con.execute("SELECT id,nickname,username FROM users WHERE id=? AND role='user' AND disabled=0", (uid,)).fetchone()
            if player is None:
                raise HTTPException(404, "玩家不存在或已停用")
            row = con.execute("SELECT id,requester,status FROM friends WHERE (requester=? AND receiver=?) OR (requester=? AND receiver=?)",
                              (user["id"],uid,uid,user["id"])).fetchone()
            relationship = ("self" if uid == user["id"] else "none" if not row else
                            "accepted" if row["status"] == "accepted" else
                            "outgoing" if row["requester"] == user["id"] else "incoming")
            return dict(player) | {"relationship":relationship,"friend_id":row["id"] if row else None}

    @app.get("/api/friends")
    def list_friends(user=Depends(current_user)):
        with db.connect() as con:
            return [
                dict(r)
                for r in con.execute(
                    "SELECT f.*,u.id AS other_id,u.nickname,u.username FROM friends f JOIN users u ON u.id=CASE WHEN f.requester=? THEN f.receiver ELSE f.requester END WHERE f.requester=? OR f.receiver=? ORDER BY f.id DESC",
                    (user["id"], user["id"], user["id"]),
                )
            ]

    @app.post("/api/friends", status_code=201)
    def request_friend(body: FriendInput, user=Depends(current_user)):
        if body.user_id == user["id"]:
            raise HTTPException(422, "不能添加自己")
        with db.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            if not con.execute(
                "SELECT 1 FROM users WHERE id=? AND disabled=0 AND role='user'",
                (body.user_id,),
            ).fetchone():
                raise HTTPException(404, "用户不存在")
            existing = con.execute(
                "SELECT 1 FROM friends WHERE (requester=? AND receiver=?) OR (requester=? AND receiver=?)",
                (user["id"], body.user_id, body.user_id, user["id"]),
            ).fetchone()
            if existing:
                raise HTTPException(409, "已是好友或已有待处理申请")
            fid = con.execute(
                "INSERT INTO friends(requester,receiver,created_at) VALUES(?,?,?)",
                (user["id"], body.user_id, now()),
            ).lastrowid
            return {"id": fid}

    @app.put("/api/friends/{friend_id}")
    def decide_friend(friend_id: int, body: FriendDecision, user=Depends(current_user)):
        with db.connect() as con:
            row = con.execute(
                "SELECT * FROM friends WHERE id=?", (friend_id,)
            ).fetchone()
            if not row or row["receiver"] != user["id"] or row["status"] != "pending":
                raise HTTPException(403, "只能处理自己收到的待确认申请")
            if body.action == "accept":
                con.execute(
                    "UPDATE friends SET status='accepted' WHERE id=?", (friend_id,)
                )
            else:
                con.execute("DELETE FROM friends WHERE id=?", (friend_id,))
            return {"ok": True}

    @app.delete("/api/friends/{friend_id}")
    def remove_friend(friend_id: int, user=Depends(current_user)):
        with db.connect() as con:
            row = con.execute(
                "SELECT * FROM friends WHERE id=?", (friend_id,)
            ).fetchone()
            if not row or user["id"] not in (row["requester"], row["receiver"]):
                raise HTTPException(404, "好友关系不存在")
            con.execute("DELETE FROM friends WHERE id=?", (friend_id,))
            return {"ok": True}

    @app.get("/api/admin/users")
    def admin_users(q: str = "", page: int = Query(1, ge=1), user=Depends(admin)):
        with db.connect() as con:
            rows = con.execute(
                "SELECT * FROM users WHERE username LIKE ? OR nickname LIKE ? ORDER BY id",
                (f"%{q}%", f"%{q}%"),
            ).fetchall()
            return {
                "items": [public_user(r) for r in rows[(page - 1) * 20 : page * 20]],
                "total": len(rows),
                "page": page,
            }

    @app.put("/api/admin/users/{uid}/status")
    def toggle_user(uid: int, body: ToggleInput, user=Depends(admin)):
        with db.connect() as con:
            target = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            if not target:
                raise HTTPException(404, "用户不存在")
            if target["role"] == "admin":
                raise HTTPException(403, "管理员账号不可停用")
            con.execute(
                "UPDATE users SET disabled=? WHERE id=?", (int(not body.enabled), uid)
            )
            if not body.enabled:
                con.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
            audit(con, user, "enable_user" if body.enabled else "disable_user", uid)
            return {"ok": True}

    @app.delete("/api/admin/users/{uid}")
    def delete_user(uid: int, user=Depends(admin)):
        with db.connect() as con:
            target = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            if not target:
                raise HTTPException(404, "用户不存在")
            if target["role"] == "admin":
                raise HTTPException(403, "不可删除管理员")
            files = [
                r[0]
                for r in con.execute(
                    "SELECT filename FROM media WHERE user_id=?", (uid,)
                )
            ]
            con.execute("DELETE FROM users WHERE id=?", (uid,))
            audit(con, user, "delete_user", uid)
        remove_files(files)
        return {"ok": True}

    @app.put("/api/admin/posts/{post_id}/status")
    def toggle_post(post_id: int, body: ToggleInput, user=Depends(admin)):
        with db.connect() as con:
            get_post(con, post_id, user)
            con.execute(
                "UPDATE posts SET hidden=? WHERE id=?", (int(not body.enabled), post_id)
            )
            audit(con, user, "restore_post" if body.enabled else "hide_post", post_id)
            return {"ok": True}

    @app.get("/api/admin/words")
    def words(user=Depends(admin)):
        with db.connect() as con:
            return [
                r[0]
                for r in con.execute("SELECT word FROM sensitive_words ORDER BY word")
            ]

    @app.post("/api/admin/words", status_code=201)
    def add_word(body: WordInput, user=Depends(admin)):
        word = body.word.strip()
        if not word:
            raise HTTPException(422, "敏感词不能为空")
        with db.connect() as con:
            con.execute("INSERT OR IGNORE INTO sensitive_words VALUES(?)", (word,))
            audit(con, user, "add_word", word)
        return {"ok": True}

    @app.delete("/api/admin/words")
    def delete_word(word: str, user=Depends(admin)):
        with db.connect() as con:
            con.execute("DELETE FROM sensitive_words WHERE word=?", (word,))
            audit(con, user, "delete_word", word)
        return {"ok": True}

    @app.get("/api/admin/audit")
    def logs(user=Depends(admin)):
        with db.connect() as con:
            return [
                dict(r)
                for r in con.execute(
                    "SELECT a.*,coalesce(u.nickname,'已删除用户') AS actor FROM audit_logs a LEFT JOIN users u ON u.id=a.actor_id ORDER BY a.id DESC LIMIT 100"
                )
            ]

    @app.get("/api/admin/stats")
    def stats(user=Depends(admin)):
        with db.connect() as con:
            counts = {
                t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                for t in ("users", "posts", "comments", "ratings")
            }
            counts["active_7d"] = con.execute(
                "SELECT count(*) FROM users WHERE last_active>=? AND role='user'",
                ((datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),),
            ).fetchone()[0]
            counts["hidden"] = con.execute(
                "SELECT count(*) FROM posts WHERE hidden=1"
            ).fetchone()[0]
            today = datetime.now(timezone(timedelta(hours=8))).date()
            trend = []
            for offset in range(6, -1, -1):
                day = str(today - timedelta(days=offset))
                trend.append(
                    {
                        "date": day,
                        "posts": con.execute(
                            "SELECT count(*) FROM posts WHERE date(created_at,'+8 hours')=?",
                            (day,),
                        ).fetchone()[0],
                        "users": con.execute(
                            "SELECT count(*) FROM users WHERE date(created_at,'+8 hours')=?",
                            (day,),
                        ).fetchone()[0],
                    }
                )
            kinds = [
                dict(r)
                for r in con.execute(
                    "SELECT CASE WHEN EXISTS(SELECT 1 FROM media m WHERE m.post_id=p.id AND kind='video') THEN 'video' WHEN EXISTS(SELECT 1 FROM media m WHERE m.post_id=p.id) THEN 'image' ELSE 'text' END AS kind,count(*) AS count FROM posts p GROUP BY kind"
                )
            ]
            tags = [
                dict(r)
                for r in con.execute(
                    "SELECT name,count(*) AS count FROM tags GROUP BY name ORDER BY count DESC,name LIMIT 8"
                )
            ]
            return {"counts": counts, "trend": trend, "kinds": kinds, "tags": tags}

    if extension:
        extension(app, db, current_user, admin, get_post)
        return app

    app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")

    @app.get("/", include_in_schema=False)
    @app.get("/admin", include_in_schema=False)
    def index():
        return FileResponse(ROOT / "web" / "index.html")

    return app


if os.getenv("ATLAS_SERVICE_ONLY") != "1" and (ROOT / "web").exists():
    app = create_app()
