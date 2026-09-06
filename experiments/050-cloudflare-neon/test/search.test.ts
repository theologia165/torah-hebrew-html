import assert from "node:assert/strict";
import test from "node:test";
import { ApiInputError, buildSearchPlan, normalizeForm, parseSearchUrl } from "../src/search";

test("Form normalization removes cantillation/meteg but keeps niqqud", () => {
  assert.equal(
    normalizeForm("וַיִּשְׁלַ֨ח"),
    normalizeForm("וַיִּשְׁלַח")
  );
  assert.notEqual(normalizeForm("וַיִּשְׁלַח"), normalizeForm("וישלח"));
});

test("050 lemma + Qal + wayyiqtol + Genesis builds bound SQL", () => {
  const criteria = parseSearchUrl(new URL(
    "https://example.test/search?strong=7971&stem=q&conjugation=w&books=Gen&limit=100"
  ));
  const plan = buildSearchPlan(criteria);

  assert.deepEqual(plan.count.params, [7971, "q", "w", "Gen"]);
  assert.match(plan.count.text, /primary_strong = \$1/);
  assert.match(plan.count.text, /main_stem_code = \$2/);
  assert.match(plan.count.text, /main_conjugation_code = \$3/);
  assert.match(plan.count.text, /book = ANY\(string_to_array\(\$4, ','\)\)/);
  assert.deepEqual(plan.rows.params, [7971, "q", "w", "Gen", 100, 0]);
  assert.match(plan.rows.text, /LIMIT \$5 OFFSET \$6/);
});

test("scope-only request is rejected", () => {
  assert.throws(
    () => parseSearchUrl(new URL("https://example.test/search?books=Gen")),
    (error: unknown) => error instanceof ApiInputError && error.status === 400
  );
});

test("unsupported book code is rejected before SQL", () => {
  assert.throws(
    () => parseSearchUrl(new URL("https://example.test/search?strong=7971&books=Gen,Robert%27%29%3Bdrop")),
    (error: unknown) => error instanceof ApiInputError && error.status === 422
  );
});

test("Torah group and selected books remain bound values", () => {
  const criteria = parseSearchUrl(new URL(
    "https://example.test/search?stem=q&conjugation=w&group=torah&books=Gen,Exod&limit=5&offset=10"
  ));
  const plan = buildSearchPlan(criteria);
  assert.deepEqual(plan.count.params, ["q", "w", "torah", "Gen,Exod"]);
  assert.deepEqual(plan.rows.params, ["q", "w", "torah", "Gen,Exod", 5, 10]);
});

test("KJV versification is accepted as display preference only", () => {
  const criteria = parseSearchUrl(new URL(
    "https://example.test/search?strong=7971&books=Gen&versification=kjv"
  ));
  assert.equal(criteria.versification, "kjv");
  const plan = buildSearchPlan(criteria);
  assert.doesNotMatch(plan.count.text, /kjv/i);
});
