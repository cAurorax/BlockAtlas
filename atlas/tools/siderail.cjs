const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = (() => {
  try { return require('playwright'); } catch {
    return require(path.join(require('node:os').homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
  }
})();
const base = process.env.BASE_URL || 'http://127.0.0.1:18182';
const out = path.resolve(__dirname, '../evidence');
const views = ['feed','library','ai','bench','friends'];
const sizes = [[1440,960],[1000,768],[768,900],[390,844],[320,650],[720,400]];

async function dimensions(page, view, width) {
  const metrics = await page.evaluate(() => {
    const nav = document.querySelector('.sidebar .nav');
    const root = document.documentElement;
    const bad = [document.querySelector('main'),document.querySelector('#content'),nav]
      .filter(el => el.scrollWidth > el.clientWidth + 1)
      .map(el => [el.className || el.id || el.tagName, el.scrollWidth, el.clientWidth]);
    const buttons = [...nav.querySelectorAll('[data-view]')].map(el => el.getBoundingClientRect()).filter(b=>b.width>0);
    return {
      over: Math.max(root.scrollWidth-innerWidth, document.body.scrollWidth-innerWidth),
      bad,
      side: buttons.every((b,i) => !i || (Math.abs(b.left-buttons[0].left) < 3 && b.top > buttons[i-1].top)),
      offenders: [...document.querySelectorAll('main *')].filter(el => el.getBoundingClientRect().right > innerWidth+1)
        .slice(0,8).map(el => [el.tagName, el.className || el.id,Math.round(el.getBoundingClientRect().right)])
    };
  });
  assert(metrics.side, width+'px navigation should form a single vertical column: '+view);
  assert(metrics.over <= 1 && !metrics.bad.length, width+'px overflow on '+view+': '+JSON.stringify(metrics));
}

async function main() {
  fs.mkdirSync(out,{recursive:true});
  const browser = await chromium.launch({executablePath:process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:960},reducedMotion:'reduce'});
    page.setDefaultTimeout(9000);
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(base);
    await page.locator('.demo-options summary').click();await page.locator('[data-demo=alice]').click();
    await page.locator('#login-form button[type=submit]').click();
    await page.locator('#content h1').waitFor();
    for(const [width,height] of sizes){
      await page.setViewportSize({width,height});const narrow=width<=900;
      const rail = page.locator('.sidebar .nav');
      assert.equal(await rail.locator('[data-view]').count(),views.length);
      for(const view of views){
        if(narrow){
          await page.locator('#rail-toggle').click();await page.locator('body.rail-open').waitFor();
        }
        const dest=rail.locator('[data-view="'+view+'"]');await dest.click();
        await page.locator('#content h1').waitFor();
        if(view==='vision') await page.locator('#lens-go').waitFor();
        if(narrow) await page.locator('body:not(.rail-open)').waitFor();
        await dimensions(page,view,width);
        if(view==='feed'&&(width===1440||width===390)){
          await page.evaluate(()=>window.scrollTo(0,0));
          await page.screenshot({path:path.join(out,'rail-'+(width===1440?'desktop':'mobile')+'.png')});
        }
        if(view==='feed'&&width===390){
          await page.locator('#rail-toggle').click();await page.locator('body.rail-open').waitFor();
          const drawer=await page.locator('.sidebar').boundingBox();
          assert(drawer.width>=190 && drawer.width<width-20,'open drawer must expand and leave an accessible scrim');
          const labels=await rail.locator('.nav-label').evaluateAll(els=>els.map(e=>({text:e.textContent,w:e.clientWidth,r:e.getBoundingClientRect().right})));
          assert.equal(labels.length,views.length);
          assert(labels.every(x=>x.w>20 && x.r<=drawer.x+drawer.width),'all drawer labels must be visible within the drawer');
          await page.screenshot({path:path.join(out,'rail-drawer.png')});
          await page.keyboard.press('Escape');await page.locator('body:not(.rail-open)').waitFor();
          await page.locator('#rail-toggle').click();await page.locator('body.rail-open').waitFor();
          const mask=await page.locator('#rail-scrim').boundingBox();assert(mask);
          await page.locator('#rail-scrim').click({position:{x:Math.floor(mask.width-4),y:Math.floor(mask.height/2)}});
          await page.locator('body:not(.rail-open)').waitFor();
        }
      }
      console.log('PASS',width+' x '+height,'all five main routes, vertical navigation, content widths');
    }
    assert.deepEqual(errors,[]);
  } finally {await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
