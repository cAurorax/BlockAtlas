"""Isolated AI settings verification: no provider requests or paid credentials."""
import io
import json
import os
import secrets
import tempfile
from unittest.mock import patch
from fastapi.testclient import TestClient

with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {k:'' for k in ('ATLAS_VISION_URL','ATLAS_VISION_MODEL','ATLAS_VISION_KEY','DEEPSEEK_API_KEY','DEEPSEEK_MODEL')}):
    os.environ['ATLAS_DATA']=folder
    from atlas.seed import app, seed
    from atlas import ai_settings
    seed()
    admin,player=TestClient(app),TestClient(app)
    for client,usr,pw in [(admin,'admin','Admin123!'),(player,'alice','Alice123!')]:
        assert client.post('/api/auth/login',json={'username':usr,'password':pw}).is_success
    base='/api/admin/ai'
    def read(r):
        assert r.is_success,r.status_code
        return r.json()
    assert player.get(base).status_code==403
    assert player.delete(base+'/text').status_code==403
    assert admin.post(base+'/vision/test').status_code==409
    key=secrets.token_urlsafe(24)
    settings={'enabled':True,'model':'fixture-model','url':ai_settings.DEFAULT_TEXT,'key':key}
    if os.name!='nt':
        assert admin.post(base+'/text',json=settings).status_code==422
        os.environ.update(DEEPSEEK_API_KEY=key,DEEPSEEK_MODEL='fixture-model')
        settings['key']=''
    with patch.object(ai_settings.urllib.request.OpenerDirector,'open',side_effect=AssertionError('Saving must never contact a provider')):
        saved=read(admin.post(base+'/text',json=settings))
        assert saved['enabled'] and saved['has_key'] and key not in str(saved)
    db=app.state.db
    with db.connect() as c:
        blob=c.execute("SELECT secret FROM ai_settings WHERE kind='text'").fetchone()[0]
        if os.name=='nt':assert blob and key.encode() not in blob
    assert read(player.get('/api/ai/status'))['text']=={'enabled':True,'model':'fixture-model'}
    assert read(player.get('/api/pack'))['online']
    assert key not in admin.get(base).text and key not in admin.get('/api/admin/audit').text
    assert admin.post(base+'/text',json={**settings,'url':'https://api.openai.com/v1/chat/completions','key':''}).status_code==422
    read(admin.post(base+'/text',json={**settings,'model':'fixture-renamed','key':''}))
    calls=[]
    def fixture(req,timeout):
        body=json.loads(req.data);assert req.get_header('Authorization')=='Bearer '+key
        calls.append(body)
        if body['messages'][0]['role']=='system':reply=json.dumps({'ops':[['add','jei']]})
        elif isinstance(body['messages'][0]['content'],list):reply='red'
        else:reply='{"ok":true}'
        return io.BytesIO(json.dumps({'choices':[{'message':{'content':reply}}]}).encode())
    with patch.object(ai_settings.urllib.request.OpenerDirector,'open',side_effect=fixture):
        read(admin.post(base+'/text/test'))
        state=read(player.post('/api/pack/action',json={'op':'chat','value':'添加配方查询'}))
        assert 'jei' in state['mods'] and calls[-1]['model']=='fixture-renamed'
        if os.name=='nt':
            read(admin.post(base+'/vision',json=settings));read(admin.post(base+'/vision/test'))
            assert calls[-1]['messages'][0]['content'][1]['type']=='image_url'
    read(admin.post(base+'/text',json={**settings,'enabled':False,'key':''}))
    assert not read(player.get('/api/pack'))['online']
    assert read(admin.delete(base+'/text'))['source'] in ('env','none')
    print('PASS role boundaries, encrypted save, no provider call on save, hot settings, redaction, credential rotation guard, independent probes, real pack route with fixture transport, disable/reset.')
