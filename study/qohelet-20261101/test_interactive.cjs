const fs=require('fs');
const path=require('path');
const {chromium}=require('playwright');
const root=__dirname;
const data=JSON.parse(fs.readFileSync(path.join(root,'json1.json'),'utf8'));
const base='https://theologia165.github.io/torah-hebrew-html/study-public/qohelet-20261101/';
const assert=(x,m)=>{if(!x)throw new Error(m)};
(async()=>{
  const browser=await chromium.launch({headless:true});
  const page=await browser.newPage({viewport:{width:960,height:720}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  let tokens=0;
  for(const verse of data.verses){
    const url=base+verse.ref.replaceAll('.','-').toLowerCase()+'.html';
    await page.goto(url);
    assert(await page.locator('.token').count()===verse.tokens.length,'token count '+verse.ref);
    const counts=await page.evaluate(()=>JSON.parse(document.querySelector('#verse-data').textContent).tokens.map(t=>({id:t.id,segments:t.morph_segments.length,rows:hoverRows(t).filter(r=>r[0].startsWith('分解 ')).length})));
    counts.forEach(c=>assert(c.segments===c.rows,'morph segments '+c.id));tokens+=counts.length;
    await page.locator('.token').first().hover();
    assert(await page.locator('#hover').isVisible(),'hover '+verse.ref);
    await page.locator('#hover [data-search-mode=form]').click();
    assert(await page.locator('#resultsCard').isVisible(),'form panel '+verse.ref);
  }
  await page.goto(base+'eccl-9-17.html');
  await page.locator('.token').first().hover();
  await page.locator('#hover [data-search-mode=lemma]').click();
  for(const scope of ['current','torah','former','latter','writings','tanakh','custom']){
    await page.selectOption('#scopeSelect',scope);
    await page.click('#runSearch');
    await page.waitForFunction(()=>document.querySelector('#runSearch').disabled===false);
    const text=await page.locator('#resultsMeta').innerText();
    assert(!text.includes('エラー')&&/\d+件/.test(text),'live lemma '+scope+': '+text);
    assert(await page.locator('#results .result').count()>0,'empty lemma '+scope);
  }
  await page.goto(base+'eccl-10-4.html');
  await page.locator('.token').nth(4).hover();
  await page.screenshot({path:path.join(root,'qa-hover.png'),fullPage:true});
  await page.locator('#hover [data-search-mode=form]').click();
  await page.click('#runSearch');
  await page.waitForFunction(()=>document.querySelector('#runSearch').disabled===false);
  assert(!(await page.locator('#resultsMeta').innerText()).includes('エラー'),'live form search');
  await page.screenshot({path:path.join(root,'qa-search.png'),fullPage:true});
  // One of the five prepositions has morphology and form search, with the unsupported lemma control disabled.
  await page.goto(base+'eccl-10-8.html');await page.locator('.token').nth(2).hover();
  assert(await page.locator('#hover [data-search-mode=lemma]').isDisabled(),'unindexed prefix');
  assert(await page.locator('#hover [data-search-mode=form]').isEnabled(),'prefix form');
  await page.setViewportSize({width:390,height:650});await page.goto(base+'eccl-10-20.html');
  await page.locator('.token').first().click();
  const box=await page.locator('#hover').boundingBox();assert(box.x>=0&&box.x+box.width<=390,'mobile popup width');
  assert(errors.length===0,'browser errors: '+errors.join(';'));
  fs.writeFileSync(path.join(root,'interactive-audit.json'),JSON.stringify({status:'PASS',verses:22,tokens,live_lemma_scopes:7,live_form_search:true,mobile_popup:true,console_errors:errors},null,2));
  await browser.close();console.log('PASS: 22 browser-loaded pages, 215 segmented tokens, hover/form/lemma, 7 live corpus scopes, mobile popup');
})().catch(e=>{console.error(e);process.exit(1)});
