const assert=require('node:assert/strict');
const {chromium}=(()=>{try{return require('playwright')}catch{return require(require('path').join(require('os').homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'))}})();
(async()=>{const b=await chromium.launch({executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'});try{
 for(const width of [1440,390]){const p=await b.newPage({viewport:{width,height:840}});await p.goto(process.env.BASE_URL||'http://127.0.0.1:18182/');
 await p.locator('.demo-options summary').click();await p.locator('[data-demo=alice]').click();await p.locator('#login-form button').click();await p.locator('.journal').waitFor();
 assert.equal(await p.locator('#quick,.more-pages').count(),0);assert(!await p.locator('#logout').isVisible());await p.keyboard.press('Control+k');assert.equal(await p.locator('#quick-q').count(),0);
 await p.locator('[data-view=friends]').click();await p.locator('[data-section=friendsFeed]').click();await p.locator('[data-section=friends]').click();await p.locator('#find-friend').waitFor();
 const avatar=p.locator('#account-home'),menu=p.locator('#player-pouch');
 const anchor=await avatar.boundingBox();assert(anchor.x<30&&anchor.y>700);
 await avatar.click();await p.locator('#player-pouch:not([hidden])').waitFor();assert.equal(await menu.locator('button').count(),3);await p.getByRole('heading',{name:'好友',exact:true}).waitFor();
 const box=await menu.boundingBox();assert(box.y+box.height<=anchor.y+1&&box.x>=0);
 if(width===1440)await p.screenshot({path:'atlas/evidence/player-pouch.png',clip:{x:0,y:anchor.y-220,width:295,height:Math.min(280,840-anchor.y+220)},animations:'disabled'});
 await p.keyboard.press('Escape');assert(!await menu.isVisible());await avatar.click();await p.getByRole('heading',{name:'好友',exact:true}).click();assert(!await menu.isVisible());
 await avatar.click();await p.locator('[data-section=mine]').click();await p.getByRole('heading',{name:'我的发布'}).waitFor();await avatar.click();await p.locator('[data-section=settings]').click();await p.locator('#password-form').waitFor();await avatar.click();await p.locator('#logout').click();await p.locator('#login-form').waitFor();await p.close();}
 console.log('PASS: no More/quick jump, grouped friend routes, avatar -> own posts/settings/logout in desktop and mobile widths.');}finally{await b.close()}})().catch(e=>{console.error(e);process.exit(1)});
