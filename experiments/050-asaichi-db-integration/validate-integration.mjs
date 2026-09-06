import fs from 'node:fs/promises';

const API='https://dtworks-hebrew-search.nishiharat.workers.dev';
const ROOT=new URL('./', import.meta.url);
const read=p=>fs.readFile(new URL(p,ROOT),'utf8');
const fail=m=>{throw new Error(m)};

const [html,js,css,editorialText]=await Promise.all([read('index.html'),read('app.js'),read('style.css'),read('editorial.json')]);
const editorial=JSON.parse(editorialText);
const literal=editorial.literal_translation??[];
if(literal.length!==11) fail(`editorial literal count=${literal.length}, expected 11`);
for(let i=1;i<=11;i++) if(Number(literal[i-1]?.token_index)!==i) fail(`editorial token_index mismatch at ${i}`);

const fallbackCount=(html.match(/class="token"/g)||[]).length;
if(fallbackCount!==11) fail(`static fallback token count=${fallbackCount}, expected 11`);
if(!html.includes('וַיִּשְׁלַ֨ח')||!html.includes('אֱדֽוֹם')) fail('static Hebrew fallback is incomplete');
if(!html.includes('data-fallback="true"')) fail('static fallback marker missing');
const lemmaAttrs=[...html.matchAll(/data-lemma="([^"]+)"/g)].map(m=>m[1]);
if(lemmaAttrs.length!==11||lemmaAttrs.some(v=>!/[\u0590-\u05FF]/.test(v))) fail('Hebrew lemma fallback is incomplete');

if(!js.includes('レーマ検索')||!js.includes('フォーム検索')) fail('hover search buttons missing');
if(js.includes("['Strong'")||js.includes('["Strong"')) fail('Strong must not be rendered in hover');
if(js.includes('oncontextmenu=e=>')) fail('right-click search handler must be removed');
if(!js.includes("el('hover').addEventListener('mouseenter',cancelHide)")) fail('interactive hover persistence missing');
if(!html.includes('Qal形のみ')||!html.includes('同じ活用のみ')||!html.includes('検索の幅')) fail('search refinement controls missing');
if(!css.includes('pointer-events:auto')) fail('hover must accept pointer interaction');

const health=await fetch(`${API}/health`).then(r=>{if(!r.ok)fail(`/health ${r.status}`);return r.json()});
if(health.status!=='ok') fail('/health status is not ok');
if(Number(health.tokens)!==20629) fail(`Genesis token count=${health.tokens}, expected 20629`);

const passage=await fetch(`${API}/passage?source=morphhb-wlc&ref=Gen.32.4`).then(r=>{if(!r.ok)fail(`/passage ${r.status}`);return r.json()});
const tokens=passage?.verses?.[0]?.tokens??[];
if(tokens.length!==11) fail(`/passage token count=${tokens.length}, expected 11`);
if(tokens[0]?.surface!=='וַיִּשְׁלַ֨ח') fail('first token mismatch');
if(tokens[10]?.surface!=='אֱדֽוֹם') fail('last token mismatch');
if(Number(tokens[0]?.primary_strong)!==7971) fail('first token lemma key mismatch');

const lemmaSearch=await fetch(`${API}/search?strong=7971&books=Gen&limit=100`).then(r=>{if(!r.ok)fail(`/lemma search ${r.status}`);return r.json()});
if(Number(lemmaSearch.total)<15) fail(`lemma search total=${lemmaSearch.total}, expected at least 15`);
if(!(lemmaSearch.results??[]).some(r=>r.osis_wlc==='Gen.32.4')) fail('lemma search does not include Gen.32.4');

const formParams=new URLSearchParams({form:tokens[0].surface,books:'Gen',limit:'100'});
const formSearch=await fetch(`${API}/search?${formParams}`).then(r=>{if(!r.ok)fail(`/form search ${r.status}`);return r.json()});
if(Number(formSearch.total)<1) fail('form search returned no results');
if(!(formSearch.results??[]).some(r=>r.osis_wlc==='Gen.32.4')) fail('form search does not include Gen.32.4');

const benchmark=await fetch(`${API}/search?strong=7971&stem=q&conjugation=w&books=Gen&limit=100`).then(r=>{if(!r.ok)fail(`/search ${r.status}`);return r.json()});
if(Number(benchmark.total)!==15) fail(`benchmark total=${benchmark.total}, expected 15`);

console.log(JSON.stringify({
  ok:true,
  health_tokens:health.tokens,
  passage_tokens:tokens.length,
  lemma_search:lemmaSearch.total,
  form_search:formSearch.total,
  benchmark:benchmark.total,
  fallback_tokens:fallbackCount,
  hebrew_lemmas:lemmaAttrs.length,
  hover_search_contract:'pass'
},null,2));
