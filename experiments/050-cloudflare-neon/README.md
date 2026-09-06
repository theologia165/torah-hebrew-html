# DTWorks 2 Cloudflare Workers + Neon PostgreSQL POC — 050

## Goal

Replace the temporary FastAPI hosting layer with a zero-fixed-cost-friendly edge API while keeping PostgreSQL and the existing 050 HTTP contract.

```text
Notion / later WordPress
        ↓
JavaScript search UI
        ↓
Cloudflare Worker
        ↓
Neon PostgreSQL
        ↓
dtworks.search_tokens
```

The previous `experiments/050-postgresql/` FastAPI implementation remains in the branch history as the reference contract. This directory implements the same search boundary in TypeScript for Cloudflare Workers.

## Current status

The Worker code is implemented but is **not yet deployed** and is **not yet connected to a real Neon project**. CI validates the request parser, parameter-bound SQL plan, TypeScript compilation, and Wrangler Worker bundle without requiring Cloudflare or Neon credentials.

Existing Notion 050, main, and Ver.2 production remain unchanged.

## API contract

### `GET /health`

Returns runtime/database health, imported token count, and MorphHB source commit.

### `GET /books`

Returns the 39-book metadata from `dtworks.books`.

### `GET /search`

Supported parameters are intentionally aligned with the FastAPI POC:

- `strong=7971`
- `form=וַיִּשְׁלַח`
- `stem=q`
- `conjugation=w`
- `group=torah|former|latter|writings`
- `books=Gen,Exod`
- `limit=1..500`
- `offset=0..1000000`
- `versification=wlc|kjv`

At least one of `strong`, `form`, `stem`, or `conjugation` is required. A scope-only full-data request is rejected.

Example:

```text
GET /search?strong=7971&stem=q&conjugation=w&books=Gen&limit=100
```

## SQL safety

Search values are not concatenated into SQL values. `src/search.ts` constructs a fixed SQL shape using numbered PostgreSQL placeholders (`$1`, `$2`, ...), and `@neondatabase/serverless` sends the values separately through `sql.query(text, params)`.

Book codes are additionally restricted to the 39 supported OSIS identifiers before SQL construction.

## Neon connection secret

Never commit the Neon connection string. After a Worker and Neon project exist, configure it as a Cloudflare secret:

```bash
npx wrangler secret put DATABASE_URL
```

For local development only, `.dev.vars` may contain:

```text
DATABASE_URL="postgresql://..."
```

`.dev.vars` and `.env` are ignored by this experiment's `.gitignore`.

## Reusing the proven PostgreSQL layer

The Neon database should use the already-proven files in `../050-postgresql/`:

1. `schema.sql`
2. `seed_books.sql`
3. `import_morphhb.py`
4. pinned MorphHB / VerseMap source

Conceptually:

```text
schema.sql + seed_books.sql
          ↓
Neon PostgreSQL
          ↑
import_morphhb.py
          ↑
pinned MorphHB
```

The database remains a derived search index. GitHub + pinned source + importer remain the reproducible source of truth.

## CI

`.github/workflows/dtworks-cloudflare-neon-poc.yml` runs:

1. dependency installation,
2. search-contract tests,
3. TypeScript typecheck,
4. `wrangler deploy --dry-run` bundle validation.

No Cloudflare API token or Neon password is required for this stage.

## Next deployment step

After CI passes, the first live deployment should remain Genesis-only:

1. create a Neon PostgreSQL project,
2. apply the existing schema and 39-book metadata,
3. import Genesis with the existing Python importer,
4. create the Cloudflare Worker,
5. save the Neon connection string as `DATABASE_URL` secret,
6. deploy the Worker,
7. verify `/health` and the 050 search over HTTPS,
8. create a separate 050-B UI so the current XML-backed 050 remains available for A/B comparison.

Only after the live 050-B result matches the existing 050 should the importer be expanded to all 39 books.
