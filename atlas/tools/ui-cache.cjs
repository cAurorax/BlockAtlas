const http=require('node:http'),fs=require('node:fs'),assert=require('node:assert/strict'),path=require('node:path');
const {chromium}=(()=>{try{return require('playwright')}catch{return require(path.join(require('os').homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'))}})();
const origin=process.env.BASE_URL||'http://127.0.0.1:18182', web=path.join(__dirname,'../web');
(async()=>{let warm=true,hits=0;
const proxy=http.createServer(async(req,res)=>{try{
 if(warm && req.url==='/'){res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'});res.end(fs.readFileSync(path.join(web,'index.html')));return}
 // Previous client used a native auto popover with all its layout in quiet.css.
 if(warm && req.url==='/static/avatar-dock.js'){let js=fs.readFileSync(path.join(web,'avatar-dock.js'),'utf8');js=js.slice(0,js.indexOf('// Use the avatar')).replace('id="account-home"','popovertarget="player-pouch" id="account-home"').replace('id="player-pouch" hidden','id="player-pouch" popover="auto"');res.writeHead(200,{'Content-Type':'text/javascript','Cache-Control':'public,max-age=86400'});res.end(js+'export function bindAvatar(){}');return}
 if(req.url==='/static/quiet.css'){hits++;res.writeHead(200,{'Content-Type':'text/css','Cache-Control':'public,max-age=86400'});res.end(fs.readFileSync(path.join(web,'quiet.css'),'utf8').split('.player-dock{')[0]);return}
 const body=[];for await(const c of req)body.push(c);const headers={};for(const k of ['cookie','content-type','authorization'])if(req.headers[k])headers[k]=req.headers[k];
 const upstream=await fetch(origin+req.url,{method:req.method,headers,body:body.length?Buffer.concat(body):undefined});res.statusCode=upstream.status;
 for(const k of ['set-cookie','content-type','cache-control'])if(upstream.headers.has(k))res.setHeader(k,upstream.headers.get(k));res.end(Buffer.from(await upstream.arrayBuffer()));
}catch(e){res.writeHead(502);res.end(e.message)}});
await new Promise(r=>proxy.listen(0,'127.0.0.1',r));const url='http://127.0.0.1:'+proxy.address().port;
let b;try{b=await chromium.launch({executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'});const p=await b.newPage({viewport:{width:1150,height:760},reducedMotion:'reduce'});
 await p.goto(url);await p.locator('.demo-options summary').click();await p.locator('[data-demo=alice]').click();await p.locator('#login-form button').click();const avatar=p.locator('#account-home'),menu=p.locator('#player-pouch');
 await avatar.click();const coords=()=>menu.locator('button').evaluateAll(xs=>xs.map(x=>({top:x.offsetTop,left:x.offsetLeft})));
 const old=await coords();assert.equal(old[0].top,old[1].top,'stale CSS reproduced a horizontal menu');const count=hits;
 warm=false;await p.goto(url+'/?ui=player-pouch');await avatar.click();const fixed=await coords();assert(fixed.every((r,i)=>!i||r.top>fixed[i-1].top&&r.left===fixed[0].left));const a=await avatar.boundingBox(),m=await menu.boundingBox();assert(a.y>620&&a.x<30&&m.y+m.height<a.y);assert.equal(hits,count);assert(await p.locator('link[href^="/ui/"][href$="quiet.css"]').count());console.log('PASS: warm old CSS produced horizontal buttons; same browser and session opened the new URL and got a bottom-left avatar and vertically anchored menu without clearing cache.');
 }finally{if(b)await b.close();proxy.closeAllConnections();proxy.close()}})().catch(e=>{console.error(e);process.exit(1)});
