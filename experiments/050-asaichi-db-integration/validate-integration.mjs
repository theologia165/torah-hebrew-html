import fs from 'node:fs/promises';

const API='https://dtworks-hebrew-search.nishiharat.workers.dev';
const ROOT=new URL('./', import.meta.url);
const read=p=>fs.readFile(new URL(p,ROOT),'utf8');
const fail=m=>{throw new Error(m)};
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));

async function fetchJson(url,label,{attempts=18,delay=5000,predicate=()=>true}={}){
  let last='';
  for(let i=1;i<=attempts;i++){
    try{
      const res=await fetch(url,{cache:'no-store'});
      if(!res.ok){last=`HTTP ${res.status}`;}
      else{
        const data=await res.json();
        if(predicate(data))return data;
        last='response contract not deployed yet';
      }
    }catch(error){last=error.message}
    if(i<attempts){console.log(`${label}: attempt ${i}/${attempts} not ready (${last}); retrying...`);await sleep(delay)}
  }
  fail(`${label}: ${last}`);
}

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
const lexemeAttrs=[...html.matchAll(/data-lexeme-key="([^"]+)"/g)].map(m=>m[1]);
if(lemmaAttrs.length!==11||lemmaAttrs.some(v=>!/[\u0590-\u05FF]/.test(v))) fail('Hebrew lemma fallback is incomplete');
if(lexemeAttrs.length!==11||lexemeAttrs.some(v=>!v)) fail('lexeme-key fallback is incomplete');
if(html.includes('data-strong=')) fail('Strong must not be a UI fallback attribute');

if(!js.includes('レーマ検索')||!js.includes('フォーム検索')) fail('hover search buttons missing');
if(js.includes("['Strong'")||js.includes('["Strong"')) fail('Strong must not be rendered in hover');
if(!js.includes("p.set('lexeme',String(key))")) fail('lemma search must use lexeme key');
if(js.includes("p.set('strong'")) fail('050 UI must not use Strong search');
if(js.includes('oncontextmenu=e=>')) fail('right-click search handler must be removed');
if(!js.includes("el('hover').addEventListener('mouseenter',cancelHide)")) fail('interactive hover persistence missing');
if(!html.includes('Qal形のみ')||!html.includes('同じ活用のみ')||!html.includes('検索の幅')) fail('search refinement controls missing');
if(!css.includes('pointer-events:auto')) fail('hover must accept pointer interaction');

// Cloudflare deploy can lag a GitHub push by several seconds. Retry until the
// version-2 lexeme contract is live instead of racing the deployment.
const health=await fetchJson(`${API}/health`,'/health',{
  predicate:d=>d.status==='ok'&&Number(d.lexemes)===1812&&Number(d.labeled_lexemes)===1812
});
if(Number(health.tokens)!==20629) fail(`Genesis token count=${health.tokens}, expected 20629`);
if(Number(health.linked_lexical_tokens)!==20159) fail(`linked lexical tokens=${health.linked_lexical_tokens}, expected 20159`);

const passage=await fetchJson(`${API}/passage?source=morphhb-wlc&ref=Gen.32.4`,'/passage lexeme contract',{
  predicate:d=>d.version==='2'&&d?.verses?.[0]?.tokens?.[0]?.lexeme?.lemma==='שָׁלַח'
});
const tokens=passage?.verses?.[0]?.tokens??[];
if(tokens.length!==11) fail(`/passage token count=${tokens.length}, expected 11`);
if(tokens[0]?.surface!=='וַיִּשְׁלַ֨ח') fail('first token mismatch');
if(tokens[10]?.surface!=='אֱדֽוֹם') fail('last token mismatch');
if(tokens[0]?.lexeme?.key!=='7971'||tokens[0]?.lexeme?.lemma!=='שָׁלַח') fail('first token lexeme mismatch');
if(tokens.some(t=>!t?.lexeme?.key||!/[\u0590-\u05FF]/.test(t?.lexeme?.lemma??''))) fail('one or more Gen.32.4 tokens lack DB lexeme data');

const lemmaSearch=await fetchJson(`${API}/search?lexeme=7971&books=Gen&limit=100`,'/search lexeme');
if(Number(lemmaSearch.total)!==66) fail(`lemma search total=${lemmaSearch.total}, expected 66`);
if(!(lemmaSearch.results??[]).some(r=>r.osis_wlc==='Gen.32.4')) fail('lemma search does not include Gen.32.4');
if((lemmaSearch.results??[]).some(r=>r.lexeme_key!=='7971')) fail('lexeme search returned a different lexeme key');

const formParams=new URLSearchParams({form:tokens[0].surface,books:'Gen',limit:'100'});
const formSearch=await fetchJson(`${API}/search?${formParams}`,'/search form');
if(Number(formSearch.total)<1) fail('form search returned no results');
if(!(formSearch.results??[]).some(r=>r.osis_wlc==='Gen.32.4')) fail('form search does not include Gen.32.4');

const benchmark=await fetchJson(`${API}/search?lexeme=7971&stem=q&conjugation=w&books=Gen&limit=100`,'/search lexeme benchmark');
if(Number(benchmark.total)!==15) fail(`benchmark total=${benchmark.total}, expected 15`);

// Legacy API compatibility can remain while the 050 UI is lexeme-native.
const legacy=await fetchJson(`${API}/search?strong=7971&stem=q&conjugation=w&books=Gen&limit=100`,'/search legacy Strong');
if(Number(legacy.total)!==15) fail(`legacy benchmark total=${legacy.total}, expected 15`);

console.log(JSON.stringify({
  ok:true,
  health_tokens:health.tokens,
  lexemes:health.lexemes,
  labeled_lexemes:health.labeled_lexemes,
  linked_lexical_tokens:health.linked_lexical_tokens,
  passage_tokens:tokens.length,
  db_lemma:tokens[0].lexeme.lemma,
  lexeme_search:lemmaSearch.total,
  form_search:formSearch.total,
  benchmark:benchmark.total,
  fallback_tokens:fallbackCount,
  hebrew_lemmas:lemmaAttrs.length,
  hover_search_contract:'lexeme-native-pass'
},null,2));
