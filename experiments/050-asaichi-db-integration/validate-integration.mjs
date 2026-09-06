import fs from 'node:fs/promises';

const API='https://dtworks-hebrew-search.nishiharat.workers.dev';
const ROOT=new URL('./', import.meta.url);
const read=p=>fs.readFile(new URL(p,ROOT),'utf8');
const fail=m=>{throw new Error(m)};

const [html,editorialText]=await Promise.all([read('index.html'),read('editorial.json')]);
const editorial=JSON.parse(editorialText);
const literal=editorial.literal_translation??[];
if(literal.length!==11) fail(`editorial literal count=${literal.length}, expected 11`);
for(let i=1;i<=11;i++) if(Number(literal[i-1]?.token_index)!==i) fail(`editorial token_index mismatch at ${i}`);
const fallbackCount=(html.match(/class="token"/g)||[]).length;
if(fallbackCount!==11) fail(`static fallback token count=${fallbackCount}, expected 11`);
if(!html.includes('וַיִּשְׁלַ֨ח')||!html.includes('אֱדֽוֹם')) fail('static Hebrew fallback is incomplete');
if(!html.includes('data-fallback="true"')) fail('static fallback marker missing');

const health=await fetch(`${API}/health`).then(r=>{if(!r.ok)fail(`/health ${r.status}`);return r.json()});
if(health.status!=='ok') fail('/health status is not ok');
if(Number(health.tokens)!==20629) fail(`Genesis token count=${health.tokens}, expected 20629`);

const passage=await fetch(`${API}/passage?source=morphhb-wlc&ref=Gen.32.4`).then(r=>{if(!r.ok)fail(`/passage ${r.status}`);return r.json()});
const tokens=passage?.verses?.[0]?.tokens??[];
if(tokens.length!==11) fail(`/passage token count=${tokens.length}, expected 11`);
if(tokens[0]?.surface!=='וַיִּשְׁלַ֨ח') fail('first token mismatch');
if(tokens[10]?.surface!=='אֱדֽוֹם') fail('last token mismatch');
if(Number(tokens[0]?.primary_strong)!==7971) fail('first token Strong mismatch');

const benchmark=await fetch(`${API}/search?strong=7971&stem=q&conjugation=w&books=Gen&limit=100`).then(r=>{if(!r.ok)fail(`/search ${r.status}`);return r.json()});
if(Number(benchmark.total)!==15) fail(`benchmark total=${benchmark.total}, expected 15`);

console.log(JSON.stringify({ok:true,health_tokens:health.tokens,passage_tokens:tokens.length,benchmark:benchmark.total,fallback_tokens:fallbackCount},null,2));
