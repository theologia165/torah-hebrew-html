import assert from "node:assert/strict";
import test from "node:test";
import { ApiInputError } from "../src/search";
import { buildPassageQuery, parsePassageUrl } from "../src/passage";

test("single verse uses source-aware OSIS contract", () => {
  const criteria = parsePassageUrl(new URL("https://example.test/passage?source=morphhb-wlc&ref=Gen.32.4"));
  assert.equal(criteria.source, "morphhb-wlc");
  assert.equal(criteria.start.osis, "Gen.32.4");
  assert.equal(criteria.end.osis, "Gen.32.4");
  const query = buildPassageQuery(criteria);
  assert.deepEqual(query.params, ["morphhb-wlc", "Gen", 32, 4, 32, 4]);
  assert.match(query.text, /core\.source_passages/);
  assert.match(query.text, /core\.reference_links/);
});

test("verse range is accepted within Genesis", () => {
  const criteria = parsePassageUrl(new URL("https://example.test/passage?start=Gen.32.4&end=Gen.32.8"));
  assert.equal(criteria.start.verse, 4);
  assert.equal(criteria.end.verse, 8);
});

test("ref and range parameters cannot be mixed", () => {
  assert.throws(
    () => parsePassageUrl(new URL("https://example.test/passage?ref=Gen.32.4&start=Gen.32.4")),
    (error: unknown) => error instanceof ApiInputError && error.status === 400
  );
});

test("current implementation rejects non-Genesis content without changing API shape", () => {
  assert.throws(
    () => parsePassageUrl(new URL("https://example.test/passage?ref=Exod.1.1")),
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
