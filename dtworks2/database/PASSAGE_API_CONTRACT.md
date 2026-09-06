# DTWorks 2 `/passage` API contract

Status: v1 request/response contract fixed; MorphHB availability expanded to all 39 Tanakh books.

## Design rule

`/passage` identifies both a corpus source and an OSIS reference. It does not treat a WLC verse row ID as the universal biblical reference.

Current request forms:

```text
GET /passage?source=morphhb-wlc&ref=Gen.32.4
GET /passage?source=morphhb-wlc&start=Gen.32.4&end=Gen.32.8
```

Current loaded source:

```text
source=morphhb-wlc
reference system=WLC
available books=all 39 Tanakh books
```

Future sources should retain the same endpoint shape:

```text
source=lxx
source=peshitta
```

A future corpus is not exposed by the API until its source metadata, reference passages, mappings, and textual data have actually been loaded and verified.

## Reference resolution

The request path is resolved through:

```text
core.corpus_sources
        ↓
core.source_passages
        ↓
core.reference_passages
        ↓
source-specific corpus storage
```

Cross-versification relationships are returned from:

```text
core.reference_links
```

Therefore WLC `Gen.32.4` can return a linked KJV-style `Gen.32.3` without changing the source reference itself.

## Response principles

A response contains:

1. source metadata,
2. source reference system,
3. requested OSIS range,
4. ordered verse objects,
5. mapping relationships to other reference systems,
6. ordered source tokens and their source-specific analysis.

The current MorphHB response exposes Hebrew token fields already used by `/search`. Later Greek/Syriac sources may store their physical token analyses differently, while the common verse-level response envelope remains stable.

## Authored-content relationship

Asaichi Torah JSON remains authored content in GitHub. It should identify its primary biblical passage using the external pair:

```json
{
  "reference": {
    "system": "WLC",
    "osis": "Gen.32.4"
  }
}
```

Database indexing/linking uses `content.documents` + `content.document_passages` to connect that JSON document to `core.reference_passages`. The PostgreSQL copy/index is derived and reconstructible; the authored JSON remains canonical.

## Non-goals at this stage

- No LXX/Peshitta corpus delivery yet.
- No parallel-text endpoint yet.
- No final Notion/BibleWorks-style visual design yet.

The Genesis benchmark remains the regression anchor while the same API boundary serves the complete Tanakh.
