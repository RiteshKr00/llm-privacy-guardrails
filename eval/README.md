# Evaluation Corpus

Hand-labeled synthetic documents for measuring detection and treatment accuracy.

## What's here

- `corpus/` — one JSON file per document. Each file contains the source text
  AND the labeled PII spans (with offsets, entity types, and per-recipient
  treatments).
- `validate_corpus.py` — small script that loads every doc and asserts each
  label's `text` field matches the substring at its `start`/`end` offsets.
  **Run this any time you edit a doc.** Catches offset drift early.
- (Day 8) `run_eval.py` — runs the agent against every doc, computes recall /
  precision / treatment accuracy. Compares against multiple baselines.

## Document genres (target distribution)

| Genre | Count | Why it stresses the system |
|---|---|---|
| resume | 3 | Lots of NER entities; mostly English-friendly |
| indian_gov_form | 3 | Aadhaar / PAN / GSTIN; Presidio's blind spot |
| customer_support | 3 | Descriptive PII (`my neighbor told me...`); LLM-extractor territory |
| internal_chat | 3 | Informal mentions, casual references |
| clean_control | 3 | No PII — false-positive check |

Total target: 15 documents.

## Label format (single JSON per doc)

```json
{
  "doc_id": "resume_001",
  "genre": "resume",
  "text": "...",
  "labels": [
    {
      "text": "Aarav Verhoeff",
      "start": 42,
      "end": 56,
      "entity_type": "PERSON",
      "treatments": {
        "auditor": "keep",
        "vendor": "pseudonymize",
        "public": "pseudonymize"
      }
    }
  ]
}
```

Fields:
- `text` — the exact substring (must match `source_text[start:end]`)
- `start`, `end` — character offsets, Python-slice style (end exclusive)
- `entity_type` — must match what our detectors emit (`PERSON`, `EMAIL_ADDRESS`,
  `PHONE_NUMBER`, `LOCATION`, `CREDIT_CARD`, `AADHAAR`, `PAN`)
- `treatments` — per-profile expected action. The eval will check the agent's
  choice against this.

## Synthetic data rules (no real PII, ever)

- Names: clearly fictional ("Aarav Verhoeff", "Priya Datacheck")
- Emails: `@example.com` / `@example.test` domains only (RFC-reserved)
- Phone numbers: `+1-202-555-XXXX` range (US "555" reserved for fiction)
- Aadhaars: start with `0000` (real Aadhaars never start with 0) and have
  valid Verhoeff checksum
- PANs: 4-letter prefix `ZZZZ` to clearly mark synthetic
- Credit cards: `4111-1111-1111-1111` (the standard Visa test card) or
  similar pattern-valid-but-known-fake numbers
