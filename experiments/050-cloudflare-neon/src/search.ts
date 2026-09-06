const HEBREW_CANTILLATION = /[\u0591-\u05AF]/g;
const HEBREW_METEG = /\u05BD/g;

const BOOK_CODES = new Set([
  "Gen", "Exod", "Lev", "Num", "Deut",
  "Josh", "Judg", "1Sam", "2Sam", "1Kgs", "2Kgs",
  "Isa", "Jer", "Ezek", "Hos", "Joel", "Amos", "Obad", "Jonah", "Mic", "Nah", "Hab", "Zeph", "Hag", "Zech", "Mal",
  "Ps", "Job", "Prov", "Ruth", "Song", "Eccl", "Lam", "Esth", "Dan", "Ezra", "Neh", "1Chr", "2Chr"
]);

const GROUPS = new Set(["torah", "former", "latter", "writings"]);
const VERSIFICATIONS = new Set(["wlc", "kjv"]);
const LEXICON_SOURCE = "oshb-hebrew-lexicon";

export class ApiInputError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "ApiInputError";
  }
}

export interface SearchCriteria {
  lexeme?: string;
  // Backward-compatible Strong lookup. New UI/search clients should use lexeme.
  strong?: number;
  form?: string;
  stem?: string;
  conjugation?: string;
  group?: "torah" | "former" | "latter" | "writings";
  books: string[];
  limit: number;
  offset: number;
  versification: "wlc" | "kjv";
}

export interface QuerySpec {
  text: string;
  params: unknown[];
}

export interface SearchPlan {
  count: QuerySpec;
  rows: QuerySpec;
}

export function normalizeForm(value: string): string {
  return value
    .replaceAll("/", "")
    .normalize("NFD")
    .replace(HEBREW_CANTILLATION, "")
    .replace(HEBREW_METEG, "")
    .replace(/[\u200E\u200F]/g, "");
}

function readInteger(value: string | null, name: string, minimum: number, maximum: number, fallback?: number): number | undefined {
  if (value === null) return fallback;
  if (!/^\d+$/.test(value)) throw new ApiInputError(422, `${name} must be an integer`);
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw new ApiInputError(422, `${name} must be between ${minimum} and ${maximum}`);
  }
  return parsed;
}

function readLexeme(value: string | null): string | undefined {
  if (value === null) return undefined;
  const trimmed = value.trim();
  // Source keys are bound SQL parameters. Keep the public contract deliberately
  // conservative while allowing OSHB augmented keys such as 8165a/7704b.
  if (!/^[A-Za-z0-9._:-]{1,40}$/.test(trimmed)) {
    throw new ApiInputError(422, "lexeme must be a valid source lexeme key");
  }
  return trimmed;
}

function readOneLetter(value: string | null, name: string): string | undefined {
  if (value === null) return undefined;
  if (!/^[A-Za-z]$/.test(value)) throw new ApiInputError(422, `${name} must be one ASCII letter`);
  return value;
}

function readBooks(value: string | null): string[] {
  if (value === null || value.trim() === "") return [];
  const books = [...new Set(value.split(",").map((book) => book.trim()).filter(Boolean))];
  if (books.length === 0 || books.some((book) => !BOOK_CODES.has(book))) {
    throw new ApiInputError(422, "books must contain only supported OSIS book codes");
  }
  return books;
}

export function parseSearchUrl(url: URL): SearchCriteria {
  const p = url.searchParams;
  const lexeme = readLexeme(p.get("lexeme"));
  const strong = readInteger(p.get("strong"), "strong", 1, 99999);
  const rawForm = p.get("form");
  const form = rawForm === null ? undefined : normalizeForm(rawForm.trim());
  if (rawForm !== null && (form === "" || rawForm.length > 80)) {
    throw new ApiInputError(422, "form must be between 1 and 80 characters");
  }

  const stem = readOneLetter(p.get("stem"), "stem");
  const conjugation = readOneLetter(p.get("conjugation"), "conjugation");

  const rawGroup = p.get("group");
  if (rawGroup !== null && !GROUPS.has(rawGroup)) {
    throw new ApiInputError(422, "group must be torah, former, latter, or writings");
  }
  const group = rawGroup as SearchCriteria["group"] | null;

  const rawVersification = p.get("versification") ?? "wlc";
  if (!VERSIFICATIONS.has(rawVersification)) {
    throw new ApiInputError(422, "versification must be wlc or kjv");
  }

  const books = readBooks(p.get("books"));
  const limit = readInteger(p.get("limit"), "limit", 1, 500, 100)!;
  const offset = readInteger(p.get("offset"), "offset", 0, 1000000, 0)!;

  if (lexeme === undefined && strong === undefined && form === undefined && stem === undefined && conjugation === undefined) {
    throw new ApiInputError(400, "Specify at least one of lexeme, strong, form, stem, or conjugation.");
  }

  return {
    lexeme,
    strong,
    form,
    stem,
    conjugation,
    group: group ?? undefined,
    books,
    limit,
    offset,
    versification: rawVersification as SearchCriteria["versification"]
  };
}

export function buildSearchPlan(criteria: SearchCriteria): SearchPlan {
  const clauses: string[] = [];
  const params: unknown[] = [];

  const add = (sqlFragment: string, value: unknown) => {
    params.push(value);
    clauses.push(sqlFragment.replace("?", `$${params.length}`));
  };

  if (criteria.lexeme !== undefined) {
    add(`primary_lexeme_id = (
      SELECT lx.id
      FROM core.lexemes lx
      JOIN core.lexicon_sources lxs ON lxs.id = lx.lexicon_source_id
      WHERE lxs.code = '${LEXICON_SOURCE}' AND lx.source_lexeme_key = ?
    )`, criteria.lexeme);
  }
  if (criteria.strong !== undefined) add("primary_strong = ?", criteria.strong);
  if (criteria.form !== undefined) add("form_search = ?", criteria.form);
  if (criteria.stem !== undefined) add("main_stem_code = ?", criteria.stem);
  if (criteria.conjugation !== undefined) add("main_conjugation_code = ?", criteria.conjugation);
  if (criteria.group !== undefined) add("tanakh_group = ?", criteria.group);
  if (criteria.books.length > 0) add("book = ANY(string_to_array(?, ','))", criteria.books.join(","));

  const where = clauses.join(" AND ");
  const count: QuerySpec = {
    text: `SELECT count(*)::text AS total FROM dtworks.search_tokens WHERE ${where}`,
    params: [...params]
  };

  const rowParams = [...params, criteria.limit, criteria.offset];
  const limitParam = `$${params.length + 1}`;
  const offsetParam = `$${params.length + 2}`;

  const rows: QuerySpec = {
    text: `
      SELECT book, english_name, japanese_name, tanakh_group, canonical_order,
             chapter_wlc, verse_wlc, osis_wlc,
             chapter_kjv, verse_kjv, osis_kjv,
             token_index, surface, form_search, form_consonantal,
             lemma_raw, primary_strong, lemma_display,
             morph_raw, language_code, main_pos_code,
             main_stem_code, main_conjugation_code,
             person_code, gender_code, number_code, state_code,
             lexeme_key, lexeme_lemma, lexeme_search,
             lexeme_transliteration, lexeme_pos_code, lexicon_source_code
      FROM dtworks.search_tokens
      WHERE ${where}
      ORDER BY canonical_order, chapter_wlc, verse_wlc, token_index
      LIMIT ${limitParam} OFFSET ${offsetParam}
    `,
    params: rowParams
  };

  return { count, rows };
}
