const {chromium}=(()=>{try{return require('playwright')}catch{return require(require('path').join(require('os').homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'))}})();
const assert=require('node:assert/strict');
const url=process.env.BASE_URL||'http://127.0.0.1:18182';
(async()=>{const b=await chromium.launch({executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'});try{
 const ctx=await b.newContext({viewport:{width:1440,height:960}});const page=await ctx.newPage();
 await page.goto(url+'/#ai');await page.locator('.demo-options summary').click();await page.locator('[data-demo=alice]').click();await page.locator('#login-form button').click();
 await page.getByRole('heading',{name:'AI 工坊',exact:true}).waitFor();
 await page.screenshot({animations:'disabled',path:'atlas/evidence/ai-workshop.png'});
 await page.locator('#my-model-settings').click();await page.locator('#personal-model-dialog').waitFor();
 const textKey=page.locator('[data-personal-form=text] input[name=key]');assert.equal(await textKey.getAttribute('type'),'password');assert.equal(await textKey.inputValue(),'');
 await page.screenshot({animations:'disabled',path:'atlas/evidence/personal-models.png'});
 await page.locator('[data-model-tab=vision]').click();await page.locator('[data-personal-form=vision] input[name=key]').waitFor();
 assert.equal(await page.locator('[data-personal-form=vision] input[name=key]').inputValue(),'');await page.keyboard.press('Escape');
 const adm=await ctx.newPage();await adm.goto(url+'/admin#ai');
 await adm.locator('[data-demo=admin]').click();await adm.locator('#login button[type=submit]').click();await adm.locator('[data-ai-form=text]').waitFor();await adm.locator('[data-ai-form=vision]').waitFor();assert.equal(new URL(adm.url()).hash,'#ai');
 for(const key of ['text','vision']) {const field=adm.locator('[data-ai-form='+key+'] input[name=key]');assert.equal(await field.getAttribute('type'),'password');assert.equal(await field.inputValue(),'')}
 await adm.screenshot({animations:'disabled',path:'atlas/evidence/ai-settings.png'});
 await page.locator('[data-use=bench]').click();await page.locator('#adjust').waitFor();await page.getByRole('link',{name:/查看 AI 模型/}).click();await page.locator('[data-use=vision]').click();await page.locator('#lens-go').waitFor();console.log('PASS player/admin direct links, login returns to requested model setup, masked empty secret fields, both tools reachable.');}finally{await b.close()}})().catch(e=>{console.error(e);process.exit(1)});
