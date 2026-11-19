"""Exercise private model settings and the actual user/vision/moderation paths without network access."""
import io
import json
import os
import secrets
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image


def run():
    shared_text=secrets.token_urlsafe(24)
    private_text=secrets.token_urlsafe(24)
    private_vision=secrets.token_urlsafe(24)
    env={'DEEPSEEK_API_KEY':shared_text,'DEEPSEEK_MODEL':'community-model','ATLAS_VISION_MODEL':'','ATLAS_VISION_KEY':'','ATLAS_VISION_URL':''}
    with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{**env,'ATLAS_DATA':folder}):
        from atlas.seed import app,seed
        from atlas import ai_settings
        seed()
        def account(name,password):
            client=TestClient(app)
            assert client.post('/api/auth/login',json={'username':name,'password':password}).is_success
            return client
        def ok(response):
            assert response.is_success,response.status_code
            return response.json()
        admin=account('admin','Admin123!')
        alice=account('alice','Alice123!')
        bob=account('bob','Bob12345!')
        base='/api/me/ai'
        adminbase='/api/admin/ai'
        personal={'model':'alice-model','url':ai_settings.DEFAULT_TEXT,'enabled':True,'key':private_text}
        alice_id=ok(alice.get('/api/auth/me'))['id']
        assert TestClient(app).get(base).status_code==401
        assert alice.get(adminbase).status_code==403
        community=ok(alice.get(base))['text']
        assert community==dict(enabled=True,model='community-model',source='community',url='',has_key=False,has_personal=False)
        assert alice.post(base+'/text/test').status_code==409
        assert alice.post(base+'/text',json={**personal,'key':''}).status_code==422
        # Fail closed on platforms without Windows current-user DPAPI.
        if os.name!='nt':
            assert alice.post(base+'/text',json=personal).status_code==422
            return
        with patch.object(ai_settings,'request_chat',side_effect=AssertionError('saving never probes')):
            status=ok(alice.post(base+'/text',json=personal))
        assert status['source']=='personal' and status['has_personal'] and status['has_key'] and private_text not in str(status)
        with app.state.db.connect() as c:
            blob=c.execute('SELECT secret FROM player_ai_settings WHERE uid=?',(alice_id,)).fetchone()[0]
            assert blob and private_text.encode() not in blob
        assert ok(bob.get(base))['text']==community
        # Spoofed uid parameters do not choose a different account.
        assert bob.post(base+'/text/test?uid='+str(alice_id)).status_code==409
        assert alice.post(base+'/text',json={**personal,'url':'https://api.openai.com/v1/chat/completions','key':''}).status_code==422
        ok(alice.post(base+'/text',json={**personal,'model':'alice-renamed','key':''}))
        ok(alice.post(base+'/vision',json={**personal,'model':'alice-vision','key':private_vision}))
        assert not ok(bob.get('/api/vision/status'))['online']
        assert ok(alice.get('/api/vision/status'))['online']
        log=[]
        def transport(cfg,payload,timeout=30):
            log.append((cfg.model,cfg.key))
            msgs=payload['messages']
            if len(msgs)==1:
                return 'red' if isinstance(msgs[0]['content'],list) else '{"ok":true}'
            if isinstance(msgs[-1]['content'],list):
                return json.dumps({'observation':'配方','matches':[{'slug':'jei','reason':'物品界面'}]})
            if 'check' in msgs[0]['content']:return json.dumps({'summary':'核对举报原文','check':'人工复核'})
            return json.dumps({'ops':[['add','jei']]})
        with patch.object(ai_settings,'request_chat',side_effect=transport):
            ok(alice.post(base+'/text/test'));assert log[-1]==('alice-renamed',private_text)
            ok(alice.post(base+'/vision/test'));assert log[-1]==('alice-vision',private_vision)
            ok(alice.post('/api/pack/action',json={'op':'chat','value':'增加 JEI'}));assert log[-1]==('alice-renamed',private_text)
            ok(bob.post('/api/pack/action',json={'op':'chat','value':'增加 JEI'}));assert log[-1]==('community-model',shared_text)
            f=io.BytesIO();Image.new('RGB',(32,32),'blue').save(f,'PNG')
            ok(alice.post('/api/vision/search',files={'image':('sample.png',f.getvalue(),'image/png')},data={'online':'true'}));assert log[-1]==('alice-vision',private_vision)
            pid=ok(bob.post('/api/posts',json={'content':'社区帖子'}))['id']
            ok(alice.post(f'/api/posts/{pid}/report',json={'reason':'请复核'}))
            rid=ok(admin.get('/api/admin/reports'))[0]['id']
            ok(admin.post(f'/api/admin/reports/{rid}/summary'));assert log[-1]==('community-model',shared_text)
        ok(alice.post(base+'/text',json={**personal,'enabled':False,'key':''}))
        assert not ok(alice.get('/api/pack'))['online'] and ok(bob.get('/api/pack'))['online']
        assert alice.post(base+'/text/test').status_code==409
        assert ok(alice.delete(base+'/text'))==community
        assert ok(alice.get('/api/vision/status'))['online']
        ok(admin.delete('/api/admin/users/'+str(alice_id)))
        with app.state.db.connect() as c:
            assert c.execute('SELECT count(*) FROM player_ai_settings WHERE uid=?',(alice_id,)).fetchone()[0]==0
        print('PASS: inheritance, account isolation, DPAPI ciphertext, key retention and endpoint guard, private text/vision providers, independent moderation, local-only override, reset and account deletion cascade.')
if __name__=='__main__':run()
