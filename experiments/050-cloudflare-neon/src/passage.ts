import { ApiInputError } from "./search";

const OSIS_VERSE = /^([1-3]?[A-Za-z]+)\.(\d+)\.(\d+)$/;

// The API contract is source-aware from the beginning. At this stage only the
// MorphHB/WLC Genesis corpus is loaded, but adding LXX/Peshitta later should be
// a data/configuration extension rather than a new endpoint shape.
const SOURCE_CAPABILITIES = new Map([
  ["morphhb-wlc", { referenceSystem: "WLC", books: new Set(["Gen"]) }]
]);

export interface VerseRef {
  book: string;
  chapter: number;
  verse: number;
  osis: string;
}

export interface PassageCriteria {
  source: string;
  start: VerseRef;
  end: VerseRef;
}

export interface QuerySpec {
  text: string;
  params: unknown[];
}

export function parseVerseRef(raw: string, name: string): VerseRef {
  const value = raw.trim();
  const match = OSIS_VERSE.exec(value);
  if (!match) {
    throw new ApiInputError(422, `${name} must be an OSIS verse reference such as Gen.32.4`);
  }
  const chapter = Number(match[2]);
  const verse = Number(match[3]);
  if (!Number.isSafeInteger(chapter) || chapter < 1 || !Number.isSafeInteger(verse) || verse < 1) {
    throw new ApiInputError(422, `${name} contains an invalid chapter or verse`);
  }
  return { book: match[1], chapter, verse, osis: `${match[1]}.${chapter}.${verse}` };
}

function compareRef(a: VerseRef, b: VerseRef): number {
  if (a.book !== b.book) return a.book.localeCompare(b.book);
  if (a.chapter !== b.chapter) return a.chapter - b.chapter;
  return a.verse - b.verse;
}

export function parsePassageUrl(url: URL): PassageCriteria {
  const p = url.searchParams;
  const source = (p.get("source") ?? "morphhb-wlc").trim();
  const capability = SOURCE_CAPABILITIES.get(source);
  if (!capability) {
    throw new ApiInputError(422, "source is not available; currently supported: morphhb-wlc");
  }

  const ref = p.get("ref");
  const startRaw = p.get("start");
  const endRaw = p.get("end");

  if (ref !== null && (startRaw !== null || endRaw !== null)) {
    throw new ApiInputError(400, "Use either ref or start/end, not both.");
  }

  let start: VerseRef;
  let end: VerseRef;
  if (ref !== null) {
    start = parseVerseRef(ref, "ref");
    end = start;
  } else {
    if (startRaw === null) throw new ApiInputError(400, "Specify ref or start.");
    start = parseVerseRef(startRaw, "start");
    end = endRaw === null ? start : parseVerseRef(endRaw, "end");
  }

  if (start.book !== end.book) {
    throw new ApiInputError(422, "A passage range must currently stay within one book.");
  }
  if (!capability.books.has(start.book)) {
    throw new ApiInputError(422, "This source currently contains Genesis only.");
  }
  if (compareRef(start, end) > 0) {
    throw new ApiInputError(422, "start must not come after end.");
  }

  return { source, start, end };
}

export function buildPassageQuery(criteria: PassageCriteria): QuerySpec {
  // source_passages is the stable bridge from a corpus source to the common
  // reference layer. Lexeme joins are optional LEFT JOINs so the passage text
  // remains readable even when a future token has no lexical identity.
  return {
    text: `
      SELECT
        cs.code AS source_code,
        cs.label AS source_label,
        cs.language_code AS source_language,
        cs.source_version,
        rs.code AS reference_system,
        rp.id AS reference_passage_id,
        rp.osis_ref,
        rp.book_osis,
        rp.chapter,
        rp.verse,
        v.id AS verse_id,
        t.id AS token_id,
        t.token_index,
        t.surface,
        t.form_search,
        t.form_consonantal,
        t.lemma_raw,
        t.primary_strong,
        t.lemma_display,
        t.morph_raw,
        t.language_code,
        t.main_pos_code,
        t.main_stem_code,
        t.main_conjugation_code,
        t.person_code,
        t.gender_code,
        t.number_code,
        t.state_code,
        lx.source_lexeme_key AS lexeme_key,
        lx.lemma_text AS lexeme_lemma,
        lx.lemma_search AS lexeme_search,
        lx.transliteration AS lexeme_transliteration,
        lx.pos_code AS lexeme_pos_code,
        lxs.code AS lexicon_source_code,
        COALESCE((
          SELECT jsonb_agg(
                   jsonb_build_object(
                     'system', linked_rs.code,
                     'osis', linked_rp.osis_ref,
                     'relation', rl.relation_type
                   ) ORDER BY linked_rs.code, linked_rp.osis_ref
                 )
            FROM core.reference_links rl
            JOIN core.reference_passages linked_rp ON linked_rp.id = rl.linked_passage_id
            JOIN core.reference_systems linked_rs ON linked_rs.id = linked_rp.reference_system_id
           WHERE rl.passage_id = rp.id
        ), '[]'::jsonb) AS mappings
      FROM core.corpus_sources cs
      JOIN core.reference_systems rs ON rs.id = cs.reference_system_id
      JOIN core.source_passages sp ON sp.corpus_source_id = cs.id
      JOIN core.reference_passages rp ON rp.id = sp.reference_passage_id
      JOIN dtworks.verses v ON v.osis_wlc = sp.source_key
      JOIN dtworks.tokens t ON t.verse_id = v.id
      LEFT JOIN core.lexemes lx ON lx.id = t.primary_lexeme_id
      LEFT JOIN core.lexicon_sources lxs ON lxs.id = lx.lexicon_source_id
      WHERE cs.code = $1
        AND rp.book_osis = $2
        AND (rp.chapter, rp.verse) >= ($3, $4)
        AND (rp.chapter, rp.verse) <= ($5, $6)
      ORDER BY rp.chapter, rp.verse, t.token_index
      LIMIT 20000
    `,
    params: [
      criteria.source,
      criteria.start.book,
      criteria.start.chapter,
      criteria.start.verse,
      criteria.end.chapter,
      criteria.end.verse
    ]
  };
}
