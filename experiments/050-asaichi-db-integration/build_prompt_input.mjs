#!/usr/bin/env node
// DTWorks 2 -> Asaichi Torah deterministic Neon snapshot.
// GitHub Actions fetches the public /passage API (Cloudflare -> Neon) and
// reduces it to the stable fields used beside ChatGPT-authored editorial.json.

import { writeFile } from 'node:fs/promises';

const api = process.env.DTWORKS_API ?? 'https://dtworks-hebrew-search.nishiharat.workers.dev';
const source = process.argv[2] ?? 'morphhb-wlc';
const ref = process.argv[3] ?? 'Gen.32.4';
const out = process.argv[4] ?? 'json1-prompt.json';

const response = await fetch(`${api}/passage?source=${encodeURIComponent(source)}&ref=${encodeURIComponent(ref)}`);
if (!response.ok) throw new Error(`/passage failed: ${response.status} ${await response.text()}`);
const passage = await response.json();
const verse = Array.isArray(passage.verses) ? passage.verses[0] : (passage.verse ?? passage);
if (!verse || !Array.isArray(verse.tokens)) throw new Error('Unexpected /passage response: verse.tokens missing');

const mappings = verse.mappings ?? verse.mapped_refs ?? passage.mappings ?? passage.mapped_refs ?? [];
const compact = {
  schema_version: 2,
  generated_by: 'github-actions-via-dtworks-api',
  source: passage.source?.code ?? passage.source ?? source,
  source_version: passage.source?.version ?? null,
  lexicon: passage.source?.lexicon ?? null,
  reference_system: verse.reference?.system ?? verse.reference_system ?? passage.reference_system ?? 'WLC',
  ref: verse.reference?.osis ?? verse.osis_ref ?? verse.ref ?? ref,
  mapped_refs: mappings.map((m) => ({
    system: m.system ?? m.reference_system ?? null,
    ref: m.ref ?? m.osis ?? m.osis_ref ?? null,
    relation: m.relation ?? m.relation_type ?? null
  })),
  tokens: verse.tokens.map((t) => ({
    i: Number(t.token_index ?? t.index ?? t.i),
    surface: t.surface,
    form_search: t.form_search ?? null,
    form_consonantal: t.form_consonantal ?? null,
    lemma_raw: t.lemma_raw ?? null,
    morph_raw: t.morph_raw ?? null,
    language_code: t.language_code ?? null,
    pos: t.pos ?? t.main_pos_code ?? null,
    stem: t.stem ?? t.main_stem_code ?? null,
    conjugation: t.conjugation ?? t.main_conjugation_code ?? null,
    person: t.person ?? t.person_code ?? null,
    gender: t.gender ?? t.gender_code ?? null,
    number: t.number ?? t.number_code ?? null,
    state: t.state ?? t.state_code ?? null,
    lexeme: t.lexeme ? {
      key: t.lexeme.key ?? null,
      lemma: t.lexeme.lemma ?? null,
      search: t.lexeme.search ?? null,
      transliteration: t.lexeme.transliteration ?? null,
      pos: t.lexeme.pos ?? null,
      source: t.lexeme.source ?? null
    } : null
  }))
};

await writeFile(out, JSON.stringify(compact, null, 2) + '\n', 'utf8');
console.log(`Wrote ${out}: ${compact.ref}, ${compact.tokens.length} tokens`);
