#!/usr/bin/env node
// DTWorks 2 -> Asaichi Torah prompt reducer.
// Fetches the public /passage API and strips DB-only fields before the payload
// is handed to ChatGPT. This keeps AI input small while preserving token_index.

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
  schema_version: 1,
  source: passage.source?.code ?? passage.source ?? source,
  reference_system: verse.reference_system ?? passage.reference_system ?? 'WLC',
  ref: verse.osis_ref ?? verse.ref ?? ref,
  mapped_refs: mappings.map((m) => ({
    system: m.system ?? m.reference_system ?? null,
    ref: m.ref ?? m.osis ?? m.osis_ref ?? null,
    relation: m.relation ?? m.relation_type ?? null
  })),
  tokens: verse.tokens.map((t) => ({
    i: Number(t.token_index ?? t.i),
    surface: t.surface,
    strong: t.primary_strong ?? t.strong ?? null,
    lemma: t.lemma_raw ?? t.lemma ?? null,
    morph: t.morph_raw ?? t.morph ?? null
  }))
};

await writeFile(out, JSON.stringify(compact, null, 2) + '\n', 'utf8');
console.log(`Wrote ${out}: ${compact.ref}, ${compact.tokens.length} tokens`);
