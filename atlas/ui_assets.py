"""Give each served UI build a fresh module and stylesheet URL, including JS imports."""
import hashlib
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import HTMLResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles

def install(app, web: Path):
    files = {p.name: p.read_bytes() for p in sorted(web.iterdir())
             if p.is_file() and p.suffix in (".js", ".css", ".html")}
    digest = hashlib.sha256()
    for name, data in files.items():
        digest.update(name.encode()+b"\0"+data+b"\0")
    rev = digest.hexdigest()[:16]
    prefix = f"/ui/{rev}/"
    entries = {}
    for name in ("index.html", "admin.html"):
        html = files[name].decode("utf-8-sig")
        for asset in files:
            if asset.endswith((".css", ".js")):
                html = html.replace('"/static/'+asset+'"', '"'+prefix+asset+'"')
        entries[name] = html
    def page(name):
        return HTMLResponse(entries[name], headers={"Cache-Control":"no-store"})
    @app.get("/",include_in_schema=False)
    def home():return page("index.html")
    @app.get("/admin",include_in_schema=False)
    def admin_ui():return page("admin.html")
    @app.get("/ui/{build}/{name}",include_in_schema=False)
    def asset(build:str,name:str):
        if name not in files or not name.endswith((".css",".js")):
            raise HTTPException(404)
        if build!=rev:
            return RedirectResponse(prefix+name, headers={"Cache-Control":"no-store"})
        mime="text/css" if name.endswith(".css") else "text/javascript"
        return Response(files[name],media_type=mime,headers={"Cache-Control":"public,max-age=31536000,immutable"})
    app.mount("/static",StaticFiles(directory=web),name="atlas-ui")
