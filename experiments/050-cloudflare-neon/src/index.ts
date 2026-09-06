import { neon } from "@neondatabase/serverless";
import { ApiInputError, buildSearchPlan, parseSearchUrl } from "./search";

const MORPHHB_COMMIT = "3d15126fb1ef74867fc1434be1942e837932691f";

interface Env {
  DATABASE_URL: string;
  CORS_ORIGINS?: string;
}

type JsonObject = Record<string, unknown>;

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

async function handleHealth(request: Request, env: Env): Promise<Response> {
  const sql = neon(env.DATABASE_URL);
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

async function handleBooks(request: Request, env: Env): Promise<Response> {
  const sql = neon(env.DATABASE_URL);
  const rows = await sql.query(`
    SELECT osis_code AS book, english_name, japanese_name,
           tanakh_group, canonical_order
      FROM dtworks.books
     ORDER BY canonical_order
  `, []);
  return json(request, env, { books: rows });
}

async function handleSearch(request: Request, env: Env, url: URL): Promise<Response> {
  const criteria = parseSearchUrl(url);
  const plan = buildSearchPlan(criteria);
  const sql = neon(env.DATABASE_URL);

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

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: responseHeaders(request, env) });
    }
    if (request.method !== "GET") {
      return json(request, env, { detail: "Method not allowed" }, 405);
    }
    if (!env.DATABASE_URL) {
      return json(request, env, { detail: "DATABASE_URL is not configured" }, 503);
    }

    const url = new URL(request.url);

    try {
      if (url.pathname === "/" || url.pathname === "") {
        return json(request, env, {
          service: "DTWorks 2 Hebrew Search API",
          runtime: "Cloudflare Workers",
          database: "Neon PostgreSQL",
          version: "0.1.0-poc",
          endpoints: ["/health", "/books", "/search"]
        });
      }
      if (url.pathname === "/health") return await handleHealth(request, env);
      if (url.pathname === "/books") return await handleBooks(request, env);
      if (url.pathname === "/search") return await handleSearch(request, env, url);
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
