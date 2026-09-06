import { neon } from "@neondatabase/serverless";
import { ApiInputError, buildSearchPlan, parseSearchUrl } from "./search";
import { buildPassageQuery, parsePassageUrl } from "./passage";

const MORPHHB_COMMIT = "3d15126fb1ef74867fc1434be1942e837932691f";

interface SecretStoreBinding {
  get(): Promise<string>;
}

interface Env {
  DATABASE_URL?: string | SecretStoreBinding;
  CORS_ORIGINS?: string;
}

type JsonObject = Record<string, unknown>;

async function resolveDatabaseUrl(env: Env): Promise<string | null> {
  const binding = env.DATABASE_URL;
  if (!binding) return null;
  if (typeof binding === "string") return binding;
  if (typeof binding.get === "function") return await binding.get();
  return null;
}

function corsOrigin(request: Request, env: Env): string | null {
  const configured = (env.CORS_ORIGINS ?? "*")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  if (configured.includes("*")) return "*";
  const origin = request.headers.get("Origin");
  return origin && configured.includes(origin) ? origin : null;
}

function responseHeaders(request: Request, env: Env): Headers {
  const headers = new Headers({
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store"
  });
  const origin = corsOrigin(request, env);
  if (origin) headers.set("access-control-allow-origin", origin);
  headers.set("access-control-allow-methods", "GET, OPTIONS");
  headers.set("access-control-allow-headers", "Content-Type");
  headers.set("vary", "Origin");
  return headers;
}

function json(request: Request, env: Env, body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: responseHeaders(request, env)
  });
}

function asRows(value: unknown): JsonObject[] {
  return Array.isArray(value) ? (value as JsonObject[]) : [];
}

function asMappings(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }
  return [];
}

async function handleHealth(request: Request, env: Env, databaseUrl: string): Promise<Response> {
  const sql = neon(databaseUrl);
  const result = await sql.query(`
    SELECT
      (SELECT count(*)::text FROM dtworks.search_tokens) AS tokens,
      (SELECT source_commit
         FROM dtworks.source_versions
        ORDER BY imported_at DESC
        LIMIT 1) AS source_commit
  `, []);
  const row = asRows(result)[0] ?? {};
  return json(request, env, {
    status: "ok",
    database: "neon-postgresql",
    runtime: "cloudflare-workers",
    tokens: Number(row.tokens ?? 0),
    source_commit: row.source_commit ?? null,
    expected_morphhb_commit: MORPHHB_COMMIT
  });
}

async function handleBooks(request: Request, env: Env, databaseUrl: string): Promise<Response> {
  const sql = neon(databaseUrl);
  const rows = await sql.query(`
    SELECT osis_code AS book, english_name, japanese_name,
           tanakh_group, canonical_order
      FROM dtworks.books
     ORDER BY canonical_order
  `, []);
  return json(request, env, { books: rows });
}

async function handleSearch(request: Request, env: Env, url: URL, databaseUrl: string): Promise<Response> {
  const criteria = parseSearchUrl(url);
  const plan = buildSearchPlan(criteria);
  const sql = neon(databaseUrl);

  const [countResult, rowResult] = await Promise.all([
    sql.query(plan.count.text, plan.count.params),
    sql.query(plan.rows.text, plan.rows.params)
  ]);

  const countRows = asRows(countResult);
  const rows = asRows(rowResult);
  const total = Number(countRows[0]?.total ?? 0);
  const results = rows.map((row) => ({
    ...row,
    wlc_ref: row.osis_wlc ?? null,
    kjv_ref: row.osis_kjv ?? null,
    display_ref:
      criteria.versification === "kjv" && row.osis_kjv
        ? row.osis_kjv
        : row.osis_wlc
  }));

  return json(request, env, {
    query: criteria,
    total,
    limit: criteria.limit,
    offset: criteria.offset,
    results
  });
}

async function handlePassage(request: Request, env: Env, url: URL, databaseUrl: string): Promise<Response> {
  const criteria = parsePassageUrl(url);
  const plan = buildPassageQuery(criteria);
  const sql = neon(databaseUrl);
  const rows = asRows(await sql.query(plan.text, plan.params));

  if (rows.length === 0) {
    return json(request, env, { detail: "Passage not found in the selected source." }, 404);
  }

  const verseMap = new Map<string, {
    reference: { system: unknown; osis: string; reference_passage_id: unknown };
    mappings: unknown[];
    text: string;
    text_reconstruction: string;
    tokens: JsonObject[];
  }>();

  for (const row of rows) {
    const osis = String(row.osis_ref ?? "");
    let verse = verseMap.get(osis);
    if (!verse) {
      verse = {
        reference: {
          system: row.reference_system ?? null,
          osis,
          reference_passage_id: row.reference_passage_id ?? null
        },
        mappings: asMappings(row.mappings),
        text: "",
        text_reconstruction: "joined-from-MorphHB-word-tokens",
        tokens: []
      };
      verseMap.set(osis, verse);
    }

    verse.tokens.push({
      token_id: row.token_id,
      index: row.token_index,
      surface: row.surface,
      form_search: row.form_search,
      form_consonantal: row.form_consonantal,
      lemma_raw: row.lemma_raw,
      primary_strong: row.primary_strong,
      lemma_display: row.lemma_display,
      morph_raw: row.morph_raw,
      language_code: row.language_code,
      pos: row.main_pos_code,
      stem: row.main_stem_code,
      conjugation: row.main_conjugation_code,
      person: row.person_code,
      gender: row.gender_code,
      number: row.number_code,
      state: row.state_code
    });
  }

  const verses = [...verseMap.values()];
  for (const verse of verses) {
    verse.text = verse.tokens.map((token) => String(token.surface ?? "")).join(" ");
  }

  const firstRef = verses[0]?.reference.osis;
  const lastRef = verses[verses.length - 1]?.reference.osis;
  if (firstRef !== criteria.start.osis || lastRef !== criteria.end.osis) {
    return json(request, env, {
      detail: "One or both passage endpoints do not exist in the selected source.",
      requested: { start: criteria.start.osis, end: criteria.end.osis },
      resolved: { start: firstRef ?? null, end: lastRef ?? null }
    }, 404);
  }

  const first = rows[0] ?? {};
  return json(request, env, {
    api: "passage",
    version: "1",
    source: {
      code: first.source_code ?? criteria.source,
      label: first.source_label ?? null,
      language: first.source_language ?? null,
      version: first.source_version ?? null,
      reference_system: first.reference_system ?? null
    },
    requested: {
      start: criteria.start.osis,
      end: criteria.end.osis
    },
    passage_count: verses.length,
    verses
  });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: responseHeaders(request, env) });
    }
    if (request.method !== "GET") {
      return json(request, env, { detail: "Method not allowed" }, 405);
    }

    const databaseUrl = await resolveDatabaseUrl(env);
    if (!databaseUrl) {
      return json(request, env, { detail: "DATABASE_URL is not configured" }, 503);
    }

    const url = new URL(request.url);

    try {
      if (url.pathname === "/" || url.pathname === "") {
        return json(request, env, {
          service: "DTWorks 2 Biblical Corpus API",
          runtime: "Cloudflare Workers",
          database: "Neon PostgreSQL",
          version: "0.2.0",
          endpoints: ["/health", "/books", "/search", "/passage"],
          passage_examples: [
            "/passage?source=morphhb-wlc&ref=Gen.32.4",
            "/passage?source=morphhb-wlc&start=Gen.32.4&end=Gen.32.8"
          ]
        });
      }
      if (url.pathname === "/health") return await handleHealth(request, env, databaseUrl);
      if (url.pathname === "/books") return await handleBooks(request, env, databaseUrl);
      if (url.pathname === "/search") return await handleSearch(request, env, url, databaseUrl);
      if (url.pathname === "/passage") return await handlePassage(request, env, url, databaseUrl);
      return json(request, env, { detail: "Not found" }, 404);
    } catch (error) {
      if (error instanceof ApiInputError) {
        return json(request, env, { detail: error.message }, error.status);
      }
      console.error("DTWorks Worker error", error);
      return json(request, env, { detail: "database query failed" }, 503);
    }
  }
};
