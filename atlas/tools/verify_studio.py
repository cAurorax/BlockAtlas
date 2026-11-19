"""Use an isolated classroom database and a fixture transport, never a paid API."""
import base64
import io
import json
import os
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from PIL import Image

with tempfile.TemporaryDirectory() as tmp:
    os.environ["ATLAS_DATA"]=tmp
    from atlas.seed import app,seed
    from atlas import vision
    seed()
    def user(name,password):
        c=TestClient(app);assert c.post("/api/auth/login",json={"username":name,"password":password}).is_success;return c
    a=user('alice','Alice123!');b=user('bob','Bob12345!');m=user('admin','Admin123!')
    body=(vision.ART/'jei-scene.jpg').read_bytes()
    def search(client,data,raw=body):
        return client.post('/api/vision/search',files={'image':('test.jpg',raw,'image/jpeg')},data=data)
    assert search(TestClient(app),{}).status_code==401
    assert search(a,{'box':'[1,0,0,1]'}).status_code==422
    assert search(a,{},b'not an image').status_code==422
    assert search(a,{}).json()['matches'][0]['slug']=='jei'
    def remote(req,timeout):
        part=json.loads(req.data)['messages'][1]['content'][-1]['image_url']['url']
        crop=Image.open(io.BytesIO(base64.b64decode(part.split(',')[1])))
        with Image.open(io.BytesIO(body)) as source:assert crop.width==round(source.width/2) and crop.height==round(source.height/2)
        return io.BytesIO(json.dumps({'choices':[{'message':{'content':json.dumps({'observation':'配方界面','matches':[{'slug':'not-a-mod','reason':'invalid'},{'slug':'jei','reason':'物品配方网格'}]})}}]}).encode())
    with patch.dict(os.environ,{'ATLAS_VISION_KEY':'fixture','ATLAS_VISION_MODEL':'fixture','ATLAS_VISION_URL':'https://example.invalid/test'}),patch.object(vision.ai_settings.urllib.request.OpenerDirector,'open',side_effect=remote):
        r=search(a,{'box':'[0,0,0.5,0.5]','online':'true'});assert r.is_success and [x['slug'] for x in r.json()['matches']]==['jei']
    def ok(r):assert r.is_success,r.text;return r.json()
    post=ok(b.post('/api/posts',json={'content':'作者版本检查','attach_pack':True}));pid=post['id'];v=post['pack']['id']
    def path(v):return f'/api/posts/{pid}/packs/{v}'
    ok(a.post(path(v)+'/derive'));ok(a.post(path(v)+'/trials',json={'outcome':'异常','note':'实例打开时发生错误。'}))
    ok(b.post('/api/pack/action',json={'op':'add','value':'jei'}));v2=ok(b.put('/api/posts/'+str(pid),json={'content':'作者版本检查二','attach_pack':True}))['pack']['id'];assert v!=v2
    assert ok(a.get(path(v)))['totals']=={'异常':1} and ok(a.get(path(v2)))['totals']=={}
    downloaded=a.get(ok(a.post('/api/pack/export'))['url'])
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as z:assert len(json.loads(z.read('modrinth.index.json'))['files'])==2
    assert a.get('/api/admin/workspace').status_code==403
    ok(a.post('/api/posts/'+str(pid)+'/report',json={'reason':'要求核对版本'}));case=ok(m.get('/api/admin/reports'))[0];rid=case['id'];post=ok(m.get('/api/posts/'+str(pid)))
    with patch.dict(os.environ,{'DEEPSEEK_API_KEY':''}):assert ok(m.post(f'/api/admin/reports/{rid}/summary'))['mode']=='本地证据整理'
    assert not ok(a.get('/api/posts/'+str(pid)))['hidden']
    ok(m.post(f'/api/admin/reports/{rid}/decision',json={'action':'hide','note':'已核查原帖','observed':case['stamp']+'|'+post['updated_at']}));assert a.get(path(v)).status_code==404
    print('PASS crop validation, local visual search without query, fixture vision transport receives cropped pixels only, unknown slugs excluded, version-pinned fork, version-specific reports, manual moderation and visibility.')

