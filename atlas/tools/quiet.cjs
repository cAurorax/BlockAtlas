const {chromium}=(()=>{try{return require('playwright')}catch{return require(require('path').join(require('os').homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'))}})();
const assert=require('node:assert/strict');
(async()=>{const b=await chromium.launch({executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'});try{
 const page=await b.newPage({viewport:{width:1380,height:900},reducedMotion:'no-preference'});
 await page.goto(process.env.BASE_URL||'http://127.0.0.1:18182/');
 await page.getByText('使用演示账号',{exact:true}).click();await page.locator('[data-demo=alice]').click();await page.locator('#login-form button').click();
 await page.waitForSelector('#content[data-arrive] .journal');const nav=page.locator('.primary-pages button');assert.equal(await nav.count(),5);
 assert(!await page.locator('#filter-panel').isVisible());await page.locator('#filter-toggle').click();
 assert.equal(await page.locator('#filter-panel').evaluate(el=>getComputedStyle(el).animationName),'arrive');await page.locator('#filter-toggle').click();
 await page.emulateMedia({reducedMotion:'reduce'});await page.locator('#filter-toggle').click();
 assert.equal(await page.locator('#filter-panel').evaluate(el=>getComputedStyle(el).animationName),'none');
 const menu=page.locator('.post-options').first();await menu.locator('summary').click();await page.keyboard.press('Escape');assert(!await menu.evaluate(el=>el.open));
 await page.locator('#filter-toggle').click();await page.screenshot({path:'atlas/evidence/quiet-feed.png',animations:'disabled'});
 console.log('PASS: 5 primary destinations, on-demand filters, opening transition, reduced-motion preference, Escape dismissal.');
 }finally{await b.close()}})().catch(e=>{console.error(e);process.exit(1)});
