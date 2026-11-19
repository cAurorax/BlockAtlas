from .server import app,ROOT,BASE
from backend.security import hash_password, now
from datetime import datetime,timedelta,timezone
def seed():
    with app.state.db.connect() as c:
        if c.execute("SELECT count(*) FROM users").fetchone()[0]:return
        for name,nick,pwd in [('admin','工坊管理员','Admin123!'),('alice','北岸松林','Alice123!'),('bob','林地巡游者','Bob12345!'),('carol','红石档案员','Carol123!')]:
            c.execute('INSERT INTO users(username,nickname,password,role,created_at,last_active) VALUES(?,?,?,?,?,?)',(name,nick,hash_password(pwd),'admin' if name=='admin' else 'user',now(),now()))
        for i,(uid,txt,tag,slug,path) in enumerate([
            (3,'林场日志｜一斧伐倒整棵树\n示意短片的第 3 秒是连锁伐木。点作者标记就能把这个效果加进自己的包。','生存','fallingtree',BASE/'mc-demo/assets/tree.mp4'),
            (4,'工作台旁的配方手册\n这张图来自 JEI 的项目图库。做复杂机器时，可以留在游戏里核对每一步材料。','合成','jei',ROOT/'web/images/jei-scene.jpg'),
            (2,'水下光照对比\nSodium 作者图库展示了水下渲染差异。装之前建议先保存原来的实例。','性能','sodium',ROOT/'web/images/sodium-scene.jpg'),
            (4,'周末联机：出发前看看食物还能补多少饱食度。有没有人想一起去找村庄？','联机','appleskin',None)]):
            stamp=(datetime.now(timezone.utc)-timedelta(hours=i*5)).isoformat()
            pid=c.execute('INSERT INTO posts(user_id,content,visibility,created_at,updated_at) VALUES(?,?,?,?,?)',(uid,txt,'public',stamp,stamp)).lastrowid
            c.execute('INSERT INTO tags VALUES(?,?)',(pid,tag));c.execute('INSERT INTO links VALUES(?,?,?)',(pid,slug,3 if i==0 else 0))
            if path:
                raw=path.read_bytes();(app.state.uploads/path.name).write_bytes(raw);video=path.suffix=='.mp4'
                c.execute('INSERT INTO media(user_id,post_id,filename,kind,mime,size,created_at) VALUES(?,?,?,?,?,?,?)',(uid,pid,path.name,'video' if video else 'image','video/mp4' if video else 'image/jpeg',len(raw),stamp))
            other=2 if uid!=2 else 3;c.execute('INSERT INTO ratings VALUES(?,?,?)',(pid,other,5));c.execute('INSERT INTO comments(post_id,user_id,content,created_at) VALUES(?,?,?,?)',(pid,other,['已经加进我的生存包了。','这个配方界面找材料挺方便。','准备对比一下我的整合包。','周末可以一起！'][i],stamp))
        from .postpacks import seed_examples
        import json
        seed_examples(c,{k:json.loads(v) for k,v in c.execute('SELECT slug,data FROM resources')})
        c.execute("INSERT INTO friends(requester,receiver,status,created_at) VALUES(2,3,'accepted',?)",(now(),));c.execute("INSERT INTO friends(requester,receiver,status,created_at) VALUES(4,2,'pending',?)",(now(),))
if __name__=='__main__':seed()

