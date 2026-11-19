"""Block Atlas full-stack course demo."""
import io, json, os, re, secrets, time, zipfile, urllib.request
from pathlib import Path
from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .resources import preview
from . import postpacks, ai_settings
ROOT=Path(__file__).resolve().parent
BASE=ROOT.parent
os.environ.setdefault("ATLAS_SERVICE_ONLY", "1")
from backend.main import create_app
from backend.security import hash_password, now
from typing import Literal
class Import(BaseModel):
    link:str=Field(min_length=1,max_length=250)
class Action(BaseModel):
    op:Literal["add","remove","lock","unlock","undo","chat"]
    value:str=Field(default="",max_length=400)
def fail(msg):raise HTTPException(422,msg)

def install(app, db, current, admin, get_post):
    with db.connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS resources(slug TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS drafts(uid INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS bundles(code TEXT PRIMARY KEY,data TEXT NOT NULL,until INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS links(pid INTEGER PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,slug TEXT,sec INTEGER);
        """)
        catalog=json.loads((BASE/'mc-demo/catalog.js').read_text('utf-8-sig').split(' = ',1)[1].strip().rstrip(';'))
        info=json.loads((ROOT/'sources.json').read_text('utf-8-sig'))
        for k,v in catalog.items():
            v.update(slug=k,**info[k]);c.execute('INSERT OR IGNORE INTO resources VALUES(?,?)',(k,json.dumps(v)))
    from .feedback import install as feedback
    feedback(app,db,current,admin,get_post)
    from .vision import install as vision
    from .admin_extra import install as moderation
    ai_settings.install(app,db,current,admin)
    vision(app,db,current); moderation(app,db,admin)
    def allmods(c):return {k:json.loads(v) for k,v in c.execute("SELECT slug,data FROM resources")}
    def draft(c,u):
        r=c.execute("SELECT data FROM drafts WHERE uid=?",(u['id'],)).fetchone()
        return json.loads(r[0]) if r else dict(mods=['fabric-api','sodium'],locks=[],history=[],last='初始轻量生存包',messages=[])
    postpacks.install(app,db,current,get_post,allmods,draft)
    def link_save(c,p,b):
        if b.mod_slug and not c.execute("SELECT 1 FROM resources WHERE slug=?",(b.mod_slug,)).fetchone():fail('关联的资源不存在')
        c.execute("INSERT OR REPLACE INTO links VALUES(?,?,?)",(p,b.mod_slug,b.effect_second))
        if b.attach_pack:
            uid=c.execute("SELECT user_id FROM posts WHERE id=?",(p,)).fetchone()[0]
            postpacks.publish(c,p,draft(c,{"id":uid}),allmods(c))
    def link_read(c,p):
        r=c.execute("SELECT slug,sec FROM links WHERE pid=?",(p,)).fetchone()
        return {"mod_slug":r[0] if r else "", "effect_second":r[1] if r else 0, "pack":postpacks.summary(c,p)}
    app.state.link_read=link_read;app.state.link_save=link_save
    @app.get('/api/library')
    def library(u=Depends(current)):
        with db.connect() as c:return list(allmods(c).values())
    @app.post('/api/library/preview')
    def peek(b:Import,u=Depends(current)):
        with db.connect() as c:return preview(b.link,allmods(c))
    @app.post('/api/library/import')
    def add(b:Import,u=Depends(current)):
        with db.connect() as c:
            v=preview(b.link,allmods(c));c.execute("INSERT OR IGNORE INTO resources VALUES(?,?)",(v['slug'],json.dumps(v)));return v
    @app.get('/api/pack')
    def pack(u=Depends(current)):
        with db.connect() as c:return postpacks.with_diff(draft(c,u))|{'online':ai_settings.player_config(db,'text',u['id']).enabled}
    @app.post('/api/pack/action')
    def action(b:Action,u=Depends(current)):
        with db.connect() as c:
            s=draft(c,u);cat={**allmods(c),**s.get('pins',{})};before=json.dumps(s);ops=[(b.op,b.value)]
        if b.op=='chat':ops=interpret(b.value,cat,s,ai_settings.player_config(db,'text',u['id']))
        changes=[];mods=s['mods'].copy();locks=s['locks'].copy()
        if ops==[('undo','')] or b.op=='undo':
            if not s['history']:fail('没有可撤销的修改')
            previous=s['history'].pop()
            if isinstance(previous,dict):
                for key in ('origin','pins'):s.pop(key,None)
                s.update(previous);mods,locks=s['mods'],s['locks']
            else:
                mods,locks=previous
            changes=['已撤销上一轮']
        else:
            for op,k in ops:
                if k not in cat or op not in ('lock','unlock','remove','add'):fail('未识别资源或操作，草稿未变更')
                if op=='lock' and k not in mods:fail('只能锁定包内资源')
                if op=='remove' and k in locks:fail(cat[k]['title']+' 已锁定，请先解锁')
                seq=mods if op in ('add','remove') else locks
                if op in ('add','lock') and k not in seq:seq.append(k);changes.append({'add':'加入 ','lock':'锁定 '}[op]+cat[k]['title'])
                if op in ('remove','unlock') and k in seq:seq.remove(k);changes.append({'remove':'移除 ','unlock':'解锁 '}[op]+cat[k]['title'])
            for k in mods:
                for dep in cat[k]['required']:
                    if dep not in mods:
                        if ('remove',dep) in ops:fail(cat[k]['title']+' 仍需要 '+dep)
                        mods.append(dep);changes.append('补齐依赖 '+dep)
                if set(cat[k].get('conflicts',[]))&set(mods):fail(cat[k]['title']+' 有已声明的冲突')
            if changes:s['history']=(s['history']+[[s['mods'],s['locks']]])[-30:]
        s.update(mods=mods,locks=locks,last='；'.join(changes) or '已符合要求')
        if b.op=='chat':s['messages']=(s['messages']+[[b.value,s['last']]])[-10:]
        with db.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            if json.dumps(draft(c,u))!=before:raise HTTPException(409,'另一端刚刚修改了草稿，请刷新重试')
            c.execute("INSERT OR REPLACE INTO drafts VALUES(?,?)",(u['id'],json.dumps(s)));return s
    @app.post('/api/pack/export')
    def export(u=Depends(current)):
        with db.connect() as c:
            s=draft(c,u);cat={**allmods(c),**s.get('pins',{})}
            if not s['mods']:fail('当前整合包为空')
            m=dict(formatVersion=1,game='minecraft',name='Block Atlas Survival',versionId='1.0',dependencies={'minecraft':'1.20.1','fabric-loader':'0.19.4'},files=[cat[k]['file'] for k in s['mods']]);code=secrets.token_urlsafe(12)
            c.execute("DELETE FROM bundles WHERE until<?",(int(time.time()),));c.execute("INSERT INTO bundles VALUES(?,?,?)",(code,json.dumps(m),int(time.time())+86400));return {'code':code,'url':'/download/'+code}
    @app.get('/download/{code}')
    def download(code:str):
        with db.connect() as c:r=c.execute('SELECT data FROM bundles WHERE code=? AND until>?',(code,int(time.time()))).fetchone()
        if not r:raise HTTPException(404,'取包码无效或已过期')
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('modrinth.index.json',r[0])
        return Response(buf.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="BlockAtlas.mrpack"'})
    @app.get('/pickup')
    def pickup():
        from fastapi.responses import HTMLResponse
        return HTMLResponse('<meta charset=utf-8><meta name=viewport content="width=device-width"><title>方块工坊 · 取包</title><main style="max-width:420px;margin:12vh auto;font:18px system-ui"><h1>领取你的整合包</h1><p>输入手机上生成的取包码。24 小时内有效。</p><form onsubmit="location.href=\'/download/\'+encodeURIComponent(this.code.value.trim());return false"><input name="code" required placeholder="取包码"><button>下载 .mrpack</button></form></main>')
    from .ui_assets import install as install_ui
    install_ui(app, ROOT/'web')

def interpret(text,cat,s,cfg):
    if cfg.enabled:
        prompt='只返回JSON {"ops":[["add/remove/lock/unlock","slug"]]}。撤销用 [["undo",""]]。不确定或咨询返回空数组。结合当前包、前文与项目名理解中文，不虚构资源。'
        data={'messages':[{'role':'system','content':prompt},{'role':'user','content':json.dumps([text,s['mods'],s['locks'],s['messages'],{k:v['title'] for k,v in cat.items()}],ensure_ascii=False)}],'response_format':{'type':'json_object'}}
        try:
            o=json.loads(ai_settings.request_chat(cfg,data,timeout=25))['ops']
            if not isinstance(o,list) or len(o)>24 or not all(isinstance(x,list) and len(x)==2 and all(isinstance(y,str) for y in x) for x in o):raise ValueError()
            if not o:fail('无法确定修改意图，请指定资源和操作')
            return [tuple(x) for x in o]
        except HTTPException:raise
        except Exception:raise HTTPException(502,'模型不可用，本轮未改动')
    if re.fullmatch('撤销(上一步|上一轮)?',text.strip()):return [('undo','')]
    aliases={'sodium':'性能优化','appleskin':'食物信息','jei':'配方查询','fabric-api':'基础依赖','fallingtree':'伐木'}
    ops=[]
    for part in re.split('[，,；;]|然后|并且',text.lower().strip('。 ')):
        m=re.fullmatch(r'\s*(加上|加入|添加|移除|删除|去掉|解锁|锁定|保留)\s*(.+?)\s*',part)
        if not m:fail('离线指令示例：加上配方查询，锁定性能优化')
        key=next((k for k,v in cat.items() if m[2] in [k,v['title'].lower(),aliases.get(k)]),None)
        if not key:fail('资源未入库或名称不明确：'+m[2])
        ops.append(({'加上':'add','加入':'add','添加':'add','移除':'remove','删除':'remove','去掉':'remove','解锁':'unlock','锁定':'lock','保留':'lock'}[m[1]],key))
    return ops

app=create_app(os.environ.get('ATLAS_DATA',ROOT/'data'),extension=install)

