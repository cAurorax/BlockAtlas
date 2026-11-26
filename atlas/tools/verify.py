"""Run with python -m atlas.tools.verify; uses an isolated SQLite database."""
import io,json,os,tempfile,zipfile
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
with tempfile.TemporaryDirectory() as directory:
    os.environ['ATLAS_DATA']=directory
    from atlas.seed import app,seed
    seed()
    def client(name,password):
        c=TestClient(app);r=c.post('/api/auth/login',json={'username':name,'password':password});assert r.status_code==200;return c
    a=client('alice','Alice123!');b=client('bob','Bob12345!');m=client('admin','Admin123!')
    assert a.get('/api/admin/reports').status_code==403
    def ok(resp):assert resp.is_success,resp.text;return resp.json()
    resources=ok(a.get('/api/library'))
    fabric=next(x for x in resources if x['slug']=='fabric-api')
    with patch('atlas.resources.remote',side_effect=AssertionError('Existing resources should not require Modrinth')):
        for link in (fabric['source'],'https://modrinth.com/mod/fabric-api','fabric-api'):
            assert ok(a.post('/api/library/preview',json={'link':link}))==fabric
            assert ok(a.post('/api/library/import',json={'link':link}))==fabric
        wrong_version=fabric['source'].rsplit('/',1)[0]+'/Other123'
        for operation in ('preview','import'):
            response=a.post('/api/library/'+operation,json={'link':wrong_version})
            assert response.status_code==422 and fabric['version'] in response.json()['detail']
    assert ok(a.get('/api/library'))==resources
    post=ok(b.post('/api/posts',json=dict(content='私有实测',mod_slug='jei',visibility='private')))
    assert a.post(f"/api/posts/{post['id']}/report",json={'reason':'test'}).status_code==404
    p=ok(b.put(f"/api/posts/{post['id']}",json=dict(content='好友实测',mod_slug='jei',visibility='friends')));assert p['mod_slug']=='jei'
    ok(a.post(f"/api/posts/{p['id']}/report",json={'reason':'核实信息'}));r=ok(m.get('/api/admin/reports'))[0];ok(m.post(f"/api/admin/reports/{r['id']}/close"));assert ok(m.get('/api/admin/reports'))[0]['done']
    v=next(x for x in ok(a.get('/api/library')) if x['slug']=='jei')
    ok(a.put('/api/library/jei/bookmark'));assert ok(a.get('/api/bookmarks'))==['jei'] and ok(b.get('/api/bookmarks'))==[]
    ok(b.post('/api/library/jei/notes',json=dict(result='成功',note='测试环境 Java 17',version=v['version'])));assert ok(a.get('/api/library/jei/notes'))['notes'][0]['nickname']=='林地巡游者'
    ok(a.post('/api/pack/action',json=dict(op='chat',value='加上配方查询，锁定性能优化')))
    assert a.post('/api/pack/action',json=dict(op='remove',value='fabric-api')).status_code==422
    assert 'jei' not in ok(b.get('/api/pack'))['mods']
    code=ok(a.post('/api/pack/export'))['url'];ok(a.post('/api/pack/action',json=dict(op='undo')))
    with zipfile.ZipFile(io.BytesIO(TestClient(app).get(code).content)) as z:
        manifest=json.loads(z.read('modrinth.index.json'));assert len(manifest['files'])==3 and manifest['files'][2]['hashes']==v['file']['hashes']
    ok(a.put('/api/auth/password',json=dict(old_password='Alice123!',new_password='NewAlice123!')));assert a.get('/api/pack').status_code==401
    client('alice','NewAlice123!')
    print('PASS: private and friends-only posts, author markers, report moderation, bookmarks, version field tests, isolated drafts, dependency rollback, export snapshot, session revocation.')

