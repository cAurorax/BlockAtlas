const assert=require('node:assert/strict'),path=require('path');
const {chromium}=(()=>{try{return require('playwright')}catch{return require(path.join(require('os').homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'))}})();
const url=process.env.SOCIAL_TEST_URL;if(!url)throw Error('Run inside python -m atlas.tools.verify_social with an isolated database');
(async()=>{const b=await chromium.launch({executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'});try{
 async function login(n,pw){let c=await b.newContext({viewport:{width:1024,height:780}}),p=await c.newPage();await p.goto(url);await p.locator('#username').fill(n);await p.locator('#password').fill(pw);await p.locator('#login-form button').click();await p.locator('.journal').waitFor();return [c,p]}
 const [bob,p]=await login('bob','Bob12345!'),[carol,q]=await login('carol','Carol123!');
 for(const visibility of ['friends','private'])assert((await carol.request.post(url+'/api/posts',{data:{content:'qa-'+visibility,visibility}})).ok());
 const original=p.locator('.journal-card').filter({has:p.locator('.author-link[href="#player/4"]')}).first();
 await original.locator('.post-open').click();await p.getByRole('heading',{name:'帖子详情'}).waitFor();
 const detail=p.url();await p.locator('.author-face').click();await p.getByRole('button',{name:'申请好友'}).click();await p.getByText('已申请 · 等待确认').waitFor();assert.equal(await p.getByText('qa-friends',{exact:true}).count(),0);assert.equal((await bob.request.post(url+'/api/friends',{data:{user_id:4}})).status(),409);
 await q.locator('.author-face[href="#player/3"]').first().click();await q.getByRole('button',{name:'接受好友申请'}).click();await q.getByText('已是好友',{exact:true}).waitFor();
 await p.reload();await p.getByText('已是好友',{exact:true}).waitFor();await p.getByText('qa-friends',{exact:true}).waitFor();assert.equal(await p.getByText('qa-private',{exact:true}).count(),0);
 await p.locator('#social-back').click();await p.waitForURL(detail);await p.getByRole('heading',{name:'帖子详情'}).waitFor();
 await p.goto(url+'/#player/3');await p.getByText('这是你自己').waitFor();assert.equal(await p.locator('#player-request').count(),0);
 console.log('PASS post -> player home, apply/duplicate protection, incoming acceptance, self profile, feed visibility before and after acceptance, and return to the exact source post.');
 }finally{await b.close()}})().catch(err=>{console.error(err);process.exit(1)});
