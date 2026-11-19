"""Runtime configuration for the two AI capabilities. Credentials never leave the server."""
from __future__ import annotations

import base64
import ctypes
import io
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException
from PIL import Image
from pydantic import BaseModel, SecretStr
from backend.security import now

Kind = Literal["text", "vision"]
DEFAULT_TEXT = "https://api.deepseek.com/chat/completions"
HOSTS = {"api.deepseek.com", "api.openai.com", "dashscope.aliyuncs.com",
         "dashscope-intl.aliyuncs.com", "dashscope-us.aliyuncs.com"}
PATHS = {"/chat/completions", "/v1/chat/completions", "/compatible-mode/v1/chat/completions"}
KINDS = ("text", "vision")


class SettingsInput(BaseModel):
    url: str
    model: str
    key: SecretStr = SecretStr("")
    enabled: bool


@dataclass(repr=False)
class Config:
    model: str
    url: str
    key: str = field(repr=False)
    enabled: bool
    source: str

    def public(self, admin=False):
        result = {"enabled": self.enabled, "model": self.model}
        if admin:
            result.update(url=self.url, has_key=bool(self.key), source=self.source)
        return result


def environment(kind):
    if kind == "vision":
        model, url, key = (os.getenv("ATLAS_VISION_"+n, "").strip() for n in ("MODEL", "URL", "KEY"))
    else:
        model = os.getenv("DEEPSEEK_MODEL", "").strip()
        key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        url = DEFAULT_TEXT
    return Config(model, url, key, bool(model and key and url), "env" if (model or key or (kind=="vision" and url)) else "none")


class Blob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint32), ("ptr", ctypes.c_void_p)]


def key_blob(raw, decrypt=False):
    """Current-user Windows DPAPI; refuse insecure plaintext persistence elsewhere."""
    if not raw:
        return b""
    if os.name != "nt":
        raise HTTPException(422, "此系统请通过服务端环境变量提供密钥；不会明文保存密钥。")
    data = ctypes.create_string_buffer(raw)
    src = Blob(len(raw), ctypes.cast(data, ctypes.c_void_p))
    dst = Blob()
    crypt = ctypes.windll.crypt32
    fun = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    if not fun(ctypes.byref(src), None, None, None, None, 1, ctypes.byref(dst)):
        raise HTTPException(503, "本机密钥保护不可用，请使用运行服务的 Windows 账号重新保存密钥。")
    try:
        return ctypes.string_at(dst.ptr, dst.size)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.c_void_p(dst.ptr))


def validate_url(url, kind, allow_server_endpoint=True):
    # Only server operators (not API callers) may opt in to another HTTPS deployment URL.
    trusted = environment(kind).url
    try:
        u = urlsplit(url)
        region = re.fullmatch(r"[a-z0-9-]+\.(cn-beijing|ap-southeast-1|us-east-1)\.maas\.aliyuncs\.com", u.hostname or "")
        basic = u.scheme == "https" and u.hostname and not (u.username or u.password or u.query or u.fragment) and u.port in (None, 443)
        if basic and ((u.hostname in HOSTS or region) and u.path in PATHS or allow_server_endpoint and url == trusted):
            return url
    except ValueError:
        pass
    raise HTTPException(422, "请输入支持平台的完整 HTTPS Chat Completions 地址。")


def resolved(row, kind):
    env = environment(kind)
    if not row:
        return env
    # An environment reference remains bound to its explicitly configured endpoint.
    key = (env.key if row["url"] == env.url else "") if row["inherit"] else key_blob(row["secret"], True).decode()
    return Config(row["model"], row["url"], key, bool(row["onoff"] and row["model"] and row["url"] and key), "local")


def config(db, kind):
    with db.connect() as con:
        return resolved(con.execute("SELECT * FROM ai_settings WHERE kind=?", (kind,)).fetchone(), kind)


def personal_row(con, kind, uid):
    return con.execute("SELECT * FROM player_ai_settings WHERE uid=? AND kind=?", (uid,kind)).fetchone()


def own_config(row):
    key = key_blob(row["secret"], True).decode() if row["secret"] else ""
    return Config(row["model"], row["url"], key, bool(row["onoff"] and key and row["model"] and row["url"]), "personal")


def player_config(db, kind, uid, *, require_personal=False):
    with db.connect() as con:
        row = personal_row(con,kind,uid)
        if row is not None:
            return own_config(row)
        if require_personal:
            raise HTTPException(409, "请先保存并启用自己的模型，个人连接测试不会调用社区密钥。")
        return resolved(con.execute("SELECT * FROM ai_settings WHERE kind=?",(kind,)).fetchone(),kind)


def player_metadata(db, kind, uid):
    cfg = player_config(db,kind,uid)
    personal = cfg.source == "personal"
    return {**cfg.public(), "source":"personal" if personal else "community",
            "has_personal":personal, "has_key":bool(cfg.key) if personal else False,
            "url":cfg.url if personal else ""}


def checked_fields(b, kind, *, allow_server_endpoint):
    url=b.url.strip().rstrip("/"); model=b.model.strip(); entered=b.key.get_secret_value().strip()
    if len(url)>500 or len(model)>160 or not re.fullmatch(r"[A-Za-z0-9._:/-]*", model):
        raise HTTPException(422,"请填写有效的模型 ID 与地址。")
    if len(entered)>4096 or any(not 33<=ord(ch)<=126 for ch in entered):
        raise HTTPException(422,"密钥格式无效。")
    if url: validate_url(url,kind,allow_server_endpoint)
    return url,model,entered


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def request_chat(cfg, payload, timeout=30):
    if not cfg.enabled:
        raise HTTPException(409, "请先保存并启用此模型。")
    req = urllib.request.Request(cfg.url, data=json.dumps({**payload, "model":cfg.model}).encode(),
                                 headers={"Authorization":"Bearer "+cfg.key, "Content-Type":"application/json"})
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=timeout) as response:
            data = response.read(2_000_001)
        if len(data)>2_000_000:
            raise ValueError()
        text = json.loads(data)["choices"][0]["message"]["content"]
        if not isinstance(text, str) or not text.strip():
            raise ValueError()
        return text
    except urllib.error.HTTPError as e:
        reasons = {400:"请求格式或模型能力不匹配",401:"密钥未通过认证",403:"账号无权使用此模型",404:"地址或模型不存在",429:"额度不足或调用过于频繁"}
        raise HTTPException(502, f"服务商返回 {e.code}：{reasons.get(e.code,'未成功完成请求')}。") from None
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        raise HTTPException(502, "无法连接服务商或未收到有效模型回复，请检查配置与网络。") from None


def probe(cfg, kind):
    if kind == "vision":
        buf=io.BytesIO();Image.new("RGB",(96,96),"#ff0000").save(buf,"PNG")
        src="data:image/png;base64,"+base64.b64encode(buf.getvalue()).decode()
        content=[{"type":"text","text":"Describe the dominant color in this image. Answer with a single English color word."},
                 {"type":"image_url","image_url":{"url":src}}]
        reply=request_chat(cfg,{"messages":[{"role":"user","content":content}],"max_tokens":128})
        if not re.search(r"\bred\b|红",reply,re.I):
            raise HTTPException(502,"模型返回了文本，但未能确认测试图的颜色，请核对视觉模型能力。")
    else:
        reply=request_chat(cfg,{"messages":[{"role":"user","content":'Output JSON: {"ok":true}'}],
                                "response_format":{"type":"json_object"},"max_tokens":128})
        try:
            if json.loads(reply).get("ok") is not True:raise ValueError()
        except (ValueError,AttributeError):
            raise HTTPException(502,"模型有响应，但未通过 JSON 输出测试。") from None


def install(app, db, current, admin):
    with db.connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS ai_settings(
        kind TEXT PRIMARY KEY,model TEXT NOT NULL,url TEXT NOT NULL,
        onoff INTEGER NOT NULL,secret BLOB NOT NULL,inherit INTEGER NOT NULL DEFAULT 0)""")
        con.execute("""CREATE TABLE IF NOT EXISTS player_ai_settings(
        uid INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, kind TEXT NOT NULL,
        model TEXT NOT NULL,url TEXT NOT NULL,onoff INTEGER NOT NULL,secret BLOB NOT NULL,
        PRIMARY KEY(uid,kind))""")

    @app.get("/api/ai/status")
    def status(u=Depends(current)):
        return {k:player_config(db,k,u["id"]).public() for k in KINDS}

    @app.get("/api/me/ai")
    def my_settings(u=Depends(current)):
        return {k:player_metadata(db,k,u["id"]) for k in KINDS}

    @app.post("/api/me/ai/{kind}")
    def save_mine(kind:Kind,b:SettingsInput,u=Depends(current)):
        url,model,entered=checked_fields(b,kind,allow_server_endpoint=False)
        uid=u["id"]
        with db.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            old=personal_row(con,kind,uid)
            secret=old["secret"] if old else b""
            if entered:
                secret=key_blob(entered.encode())
            elif secret and old["url"]!=url:
                raise HTTPException(422, "切换地址时请重新输入你自己的密钥。")
            if b.enabled and not (secret and url and model):
                raise HTTPException(422, "启用个人模型需要服务地址、模型 ID 和自己的 API Key。")
            con.execute("INSERT OR REPLACE INTO player_ai_settings(uid,kind,model,url,onoff,secret) VALUES(?,?,?,?,?,?)",
                        (uid,kind,model,url,int(b.enabled),secret))
        return player_metadata(db,kind,uid)

    @app.delete("/api/me/ai/{kind}")
    def reset_mine(kind:Kind,u=Depends(current)):
        with db.connect() as con:
            con.execute("DELETE FROM player_ai_settings WHERE uid=? AND kind=?",(u["id"],kind))
        return player_metadata(db,kind,u["id"])

    @app.post("/api/me/ai/{kind}/test")
    def test_mine(kind:Kind,u=Depends(current)):
        probe(player_config(db,kind,u["id"],require_personal=True),kind)
        return {"message":"个人视觉模型已通过识图测试。" if kind=="vision" else "个人文本模型已通过 JSON 输出测试。"}

    @app.get("/api/admin/ai")
    def get_settings(u=Depends(admin)):
        return {k:config(db,k).public(True) for k in KINDS}

    @app.post("/api/admin/ai/{kind}")
    def save(kind:Kind, b:SettingsInput, u=Depends(admin)):
        url,model,entered=checked_fields(b,kind,allow_server_endpoint=True)
        with db.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row=con.execute("SELECT * FROM ai_settings WHERE kind=?", (kind,)).fetchone()
            env=environment(kind)
            # A supplied replacement can repair an inaccessible DPAPI blob as well.
            if entered:
                secret=key_blob(entered.encode()); inherit=False; has_key=True
            else:
                secret=row["secret"] if row else b""
                inherit=bool(row["inherit"]) if row else bool(env.key)
                old_url=row["url"] if row else env.url
                has_key=bool(secret) or bool(inherit and env.key and env.url==old_url)
                if has_key and old_url!=url:
                    raise HTTPException(422,"切换服务地址时请重新输入对应密钥。")
            if b.enabled and not (url and model and has_key):
                raise HTTPException(422,"启用模型需要完整地址、模型 ID 与密钥。")
            con.execute("INSERT OR REPLACE INTO ai_settings VALUES(?,?,?,?,?,?)",
                        (kind,model,url,int(b.enabled),secret,int(inherit)))
            con.execute("INSERT INTO audit_logs(actor_id,action,target,created_at) VALUES(?,?,?,?)",
                        (u["id"],"ai_config_saved",kind,now()))
        return config(db,kind).public(True)

    @app.delete("/api/admin/ai/{kind}")
    def reset(kind:Kind,u=Depends(admin)):
        with db.connect() as con:
            con.execute("DELETE FROM ai_settings WHERE kind=?",(kind,))
            con.execute("INSERT INTO audit_logs(actor_id,action,target,created_at) VALUES(?,?,?,?)",
                        (u["id"],"ai_config_reset",kind,now()))
        return config(db,kind).public(True)

    @app.post("/api/admin/ai/{kind}/test")
    def test(kind:Kind,u=Depends(admin)):
        probe(config(db,kind),kind)
        return {"message":"已通过视觉识图测试。" if kind=="vision" else "已通过文本生成与 JSON 输出测试。"}
