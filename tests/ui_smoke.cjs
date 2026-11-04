// Run with NODE_PATH pointing to a Playwright installation; uses installed Edge.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const base = process.env.UI_TEST_URL || 'http://127.0.0.1:8017';
async function contrast(page) {
  return page.evaluate(() => {
    const rgb = s => (s.match(/[\d.]+/g) || []).map(Number);
    const lum = c => c.slice(0,3).map(v => { v/=255; return v<=.04045?v/12.92:((v+.055)/1.055)**2.4; }).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);
    const failures = [];
    for (const el of document.querySelectorAll('body *')) {
      if (!el.checkVisibility() || el.closest('svg, [disabled]') || ![...el.childNodes].some(n=>n.nodeType===3&&n.textContent.trim())) continue;
      const s = getComputedStyle(el);
      let bg, node = el;
      while(node) { const c=rgb(getComputedStyle(node).backgroundColor); if(c.length===3 || c[3]===1){bg=c;break;} node=node.parentElement; }
      if(!bg) continue;
      const a=lum(rgb(s.color)), b=lum(bg), ratio=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);
      const large=parseFloat(s.fontSize)>=24 || (parseFloat(s.fontSize)>=18.66&&parseInt(s.fontWeight)>=700);
      if(ratio < (large?3:4.5)) failures.push({text:el.textContent.trim().slice(0,60),ratio:+ratio.toFixed(2),color:s.color,bg});
    }
    return failures;
  });
}
(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const page=await browser.newPage({viewport:{width:1366,height:850}});
  const errors=[]; page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base); await page.locator('.feat').first().waitFor();
  for(const theme of ['light','dark']) {
    await page.evaluate(t=>{localStorage.setItem('vinamilk-theme',t);},theme); await page.reload();
    await page.locator('.feat').first().waitFor();
    assert.equal(await page.locator('html').getAttribute('data-theme'),theme);
    assert.deepEqual(await contrast(page),[],`${theme}: welcome contrast`);
    await page.locator('#new-chat').hover();
    assert.deepEqual(await contrast(page),[],`${theme}: hover contrast`);
    await page.locator('[data-view="lookup"]').click();
    await page.locator('#lookup-form button').click();
    await page.waitForFunction(()=>document.getElementById('lk-out').textContent.includes('16.') || document.getElementById('lk-out').textContent.includes('đồng'));
    assert.deepEqual(await contrast(page),[],`${theme}: lookup contrast`);
    await page.locator('[data-view="trends"]').click();
    await page.locator('#chart-form button').click(); await page.locator('.tbl').first().waitFor();
    await page.waitForFunction(()=>window.Chart && Object.keys(window.Chart.instances).length>0);
    assert.equal(await page.locator('.tbl tbody tr').count(),6);
    assert.deepEqual(await contrast(page),[],`${theme}: trends contrast`);
    await page.locator('#theme-toggle').click();
    assert.equal(await page.locator('html').getAttribute('data-theme'),theme==='dark'?'light':'dark');
    assert.equal(await page.evaluate(()=>Object.values(window.Chart.instances).filter(c=>c.canvas.isConnected).every(c=>c.data.datasets[0].borderColor===getComputedStyle(document.documentElement).getPropertyValue('--accent').trim())),true);
    await page.locator('#theme-toggle').click();
    for(const mode of ['growth','explain']) {
      await page.locator('#c-mode').selectOption(mode); await page.locator('#chart-form button').click();
      await page.locator('.tbl').first().waitFor();
      assert.deepEqual(await contrast(page),[],`${theme}: ${mode} contrast`);
    }
    await page.locator('[data-view="ratios"]').click(); await page.locator('.r-val').first().waitFor();
    await page.locator('.r-more summary').first().click();
    assert.deepEqual(await contrast(page),[],`${theme}: ratios contrast`);
    await page.locator('#rail').click(); await page.locator('#theme-toggle').click();
    await page.reload(); assert.equal(await page.locator('html').getAttribute('data-theme'),theme==='dark'?'light':'dark');
    await page.locator('#rail').click();
    // Exercise chat UI without spending a real model request.
    await page.route('**/api/ask', route=>route.fulfill({json:{answer:'Doanh thu **16.149 tỷ đồng**.',sources:[],notes:[],charts:[],warnings:['Kiểm tra báo cáo gốc.'],unsupported_numbers:[]}}));
    await page.locator('#new-chat').click();
    await page.locator('#q').fill('Doanh thu Q1/2026?'); await page.locator('#q').press('Enter');
    await page.locator('.md strong').waitFor();
    assert.deepEqual(await contrast(page),[],`${theme}: chat and warnings contrast`);
    await page.locator('.fb').first().click(); await page.waitForFunction(()=>document.querySelector('.thanks').textContent.length>0);
    await page.locator('button[title="Tạo lại câu trả lời"]').click(); await page.locator('.md strong').waitFor();
    await page.reload(); await page.locator('.md strong').waitFor();
    await page.locator('#search-btn').click(); await page.locator('#search-q').fill('doanh thu');
    assert.equal(await page.locator('.conv-title').count(),1);
    await page.locator('#search-q').fill('zzzz-no-match'); assert.equal(await page.locator('.conv-title').count(),0);
    await page.locator('#search-btn').click();
    await page.locator('button[title="Đổi tên"]').click();
    await page.locator('.conv input').fill('UI smoke'); await page.locator('.conv input').press('Enter');
    await page.locator('button[title="Xóa"]').click(); await page.locator('.conv-act.confirm').click();
    await page.unroute('**/api/ask');
    await page.route('**/api/ask', route=>route.fulfill({status:503,json:{detail:'Unavailable'}}));
    await page.locator('#q').fill('Doanh thu?'); await page.locator('#send').click();
    await page.locator('.errbox').waitFor(); assert.deepEqual(await contrast(page),[],`${theme}: error contrast`);
    await page.unroute('**/api/ask');
    await page.locator('button[title="Xóa"]').click(); await page.locator('.conv-act.confirm').click();
    await page.locator('#new-chat').click();
    console.log(`PASS ${theme}: lookup, trends, comparison, breakdown, ratios, rail, persistence, contrast`);
    console.log(`PASS ${theme}: chat rendering, regenerate, feedback, reload history, search, rename, delete, error state (mock model)`);
  }
  for(const viewport of [{width:390,height:844},{width:844,height:390}]) {
    await page.setViewportSize(viewport); await page.locator('#open-side').click();
    await page.locator('#theme-toggle').scrollIntoViewIfNeeded(); await page.locator('#theme-toggle').click();
    assert.equal(await page.locator('#theme-toggle').isVisible(),true);
    assert.deepEqual(await contrast(page),[],'mobile contrast');
    await page.locator('[data-view="lookup"]').click();
    assert.equal(await page.locator('#side').evaluate(el=>el.inert),true);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    console.log(`PASS mobile ${viewport.width}x${viewport.height}: toggle, drawer, no horizontal overflow`);
  }
  assert.deepEqual(errors,[],'browser errors');
  await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
