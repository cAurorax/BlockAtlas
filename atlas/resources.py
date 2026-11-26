"""Version-pinned catalog. Only the Modrinth provider is enabled in this demo."""
import json
import re
import urllib.parse
import urllib.request
from fastapi import HTTPException

PAT = re.compile(r"[A-Za-z0-9_-]{1,80}")
PROJECT_LINK = re.compile(
    r"https://(?:www\.)?modrinth\.com/mod/([A-Za-z0-9_-]{1,80})"
    r"(?:/version/([A-Za-z0-9_-]{1,80}))?/?"
)
def remote(path):
    req=urllib.request.Request("https://api.modrinth.com/v2/"+path,headers={"User-Agent":"BlockAtlas-CourseDemo/2.0"})
    try:
        with urllib.request.urlopen(req,timeout=12) as response:return json.load(response)
    except Exception as e:raise HTTPException(422,"Modrinth 项目不存在或服务暂不可用，请稍后重试") from e

def preview(value, existing):
    value = value.strip()
    match = PROJECT_LINK.fullmatch(value)
    if match:
        key, version_id = match.groups()
    else:
        key, version_id = value.removesuffix('/'), None
        if not PAT.fullmatch(key):
            raise HTTPException(422, "请输入 Modrinth 的 Mod 项目链接、版本链接或项目标识")

    slug = key
    if slug not in existing:
        p = remote("project/" + key)
        slug = p["slug"]
    if slug in existing:
        resource = existing[slug]
        if version_id and version_id != resource["id"]:
            raise HTTPException(422, f"该 Mod 已入库，固定版本为 {resource['version']}。请使用该版本的来源链接。")
        return resource
    if p["project_type"]!="mod" or p["client_side"]=="unsupported":raise HTTPException(422,"仅支持客户端可用的 Minecraft Mod")
    vs=remote("project/"+key+"/version?"+urllib.parse.urlencode({"game_versions":'["1.20.1"]',"loaders":'["fabric"]'}))
    v = next((v for v in vs if v["version_type"] == "release" and (not version_id or v["id"] == version_id)), None)
    if not v and version_id:
        raise HTTPException(422, "链接指定的版本不属于该项目，或不是适配 1.20.1 / Fabric 的正式版")
    if not v:raise HTTPException(422,"没有适配 1.20.1 / Fabric 的正式版")
    required=[];conflicts=[]
    for d in v["dependencies"]:
        if d["dependency_type"] not in ("required","incompatible"):continue
        ref=d.get("project_id")
        if not ref:raise HTTPException(422,"此项目含未解析的依赖，请先人工核对")
        dep=remote("project/"+ref)["slug"]
        if d["dependency_type"]=="incompatible":conflicts.append(dep);continue
        if dep not in existing:raise HTTPException(422,"请先导入必需依赖："+dep)
        if d.get("version_id") and d["version_id"]!=existing[dep]["id"]:raise HTTPException(422,"库内依赖版本不匹配："+dep)
        required.append(dep)
    f=next((f for f in v["files"] if f["primary"]),v["files"][0])
    if not re.fullmatch(r"[\w.+() -]+\.jar",f["filename"]) or not f["url"].startswith("https://cdn.modrinth.com/"):raise HTTPException(422,"该发布文件暂不支持导出")
    return dict(slug=slug,title=p["title"],description=p["description"],icon=p["icon_url"],version=v["version_number"],id=v["id"],source=f"https://modrinth.com/mod/{slug}/version/{v['id']}",required=required,conflicts=conflicts,file={"path":"mods/"+f["filename"],"hashes":{k:f["hashes"][k] for k in ("sha1","sha512")},"downloads":[f["url"]],"fileSize":f["size"],"env":{"client":"required","server":p["server_side"]}})

