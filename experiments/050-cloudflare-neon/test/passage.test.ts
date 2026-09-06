import assert from "node:assert/strict";
import test from "node:test";
import { ApiInputError } from "../src/search";
import { buildPassageQuery, parsePassageUrl } from "../src/passage";

test("single verse uses source-aware OSIS and lexeme contract", () => {
  const criteria = parsePassageUrl(new URL("https://example.test/passage?source=morphhb-wlc&ref=Gen.32.4"));
  assert.equal(criteria.source, "morphhb-wlc");
  assert.equal(criteria.start.osis, "Gen.32.4");
  assert.equal(criteria.end.osis, "Gen.32.4");
  const query = buildPassageQuery(criteria);
  assert.deepEqual(query.params, ["morphhb-wlc", "Gen", 32, 4, 32, 4]);
  assert.match(query.text, /core\.source_passages/);
  assert.match(query.text, /core\.reference_links/);
  assert.match(query.text, /LEFT JOIN core\.lexemes/);
  assert.match(query.text, /lexeme_lemma/);
  assert.match(query.text, /lexeme_key/);
});

test("verse range is accepted within a Tanakh book", () => {
  const criteria = parsePassageUrl(new URL("https://example.test/passage?start=Gen.32.4&end=Gen.32.8"));
  assert.equal(criteria.start.verse, 4);
  assert.equal(criteria.end.verse, 8);
});

test("non-Genesis Tanakh references preserve the same passage contract", () => {
  const criteria = parsePassageUrl(new URL("https://example.test/passage?ref=Exod.1.1"));
  assert.equal(criteria.start.book, "Exod");
  assert.deepEqual(buildPassageQuery(criteria).params, ["morphhb-wlc", "Exod", 1, 1, 1, 1]);
});

test("ref and range parameters cannot be mixed", () => {
  assert.throws(
    () => parsePassageUrl(new URL("https://example.test/passage?ref=Gen.32.4&start=Gen.32.4")),
    (error: unknown) => error instanceof ApiInputError && error.status === 400
  );
});

test("non-Tanakh book codes are rejected without changing API shape", () => {
  assert.throws(
    () => parsePassageUrl(new URL("https://example.test/passage?ref=Matt.1.1")),
    (error: unknown) => error instanceof ApiInputError && error.status === 422
  );
});

test("unknown future corpus source is rejected explicitly", () => {
  assert.throws(
    () => parsePassageUrl(new URL("https://example.test/passage?source=lxx&ref=Gen.1.1")),
    (error: unknown) => error instanceof ApiInputError && error.status === 422
  );
});

test("reversed range is rejected", () => {
  assert.throws(
    () => parsePassageUrl(new URL("https://example.test/passage?start=Gen.32.8&end=Gen.32.4")),
    (error: unknown) => error instanceof ApiInputError && error.status === 422
  );
});
