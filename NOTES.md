# Build Notes — LLM Privacy Guardrails

> Build journal. One entry per learning moment. Raw observations, not polished prose. Dated.
>
> Eventually goes alongside `README.md` when this project is pushed publicly.

---

## Day 1 — 2026-05-30

### Setup

- Python 3.10.11 (system install).
- Venv: `piienv` (project-specific name; `.venv` is the default convention but a named venv reads more intentionally in `git status` if it ever leaks).
- Dependencies: `presidio-analyzer`, `spacy`, plus the spaCy model `en_core_web_lg` (~500MB).

### Gotcha — missing transitive dependency

After `pip install presidio-analyzer spacy`, running `python -m spacy download en_core_web_lg` failed with:

```
ModuleNotFoundError: No module named 'click'
```

spaCy depends on `click` via `typer`, but pip's resolver had skipped it. Fix was `pip install click typer`. **Lesson:** Python's transitive deps can silently get missed — when you see a `ModuleNotFoundError` on a package you never explicitly installed, install it directly. Not magic, just a resolver quirk.

### First Presidio scan — what I observed

Wrote `scratch/01_presidio_hello.py`. Sample text contained: a person name (`Aarav Verhoeff`), email, phone, street address, credit card. Presidio returned **9 findings**. Highlights:

| Entity type | Score | What was matched |
|---|---|---|
| `EMAIL_ADDRESS` | 1.00 | `aarav.verhoeff@example.com` |
| `CREDIT_CARD` | 1.00 | `4111-1111-1111-1111` (valid Luhn test card) |
| `PHONE_NUMBER` | 0.75 | `+1-202-555-0123` |
| `PERSON` | 0.85 | `Aarav` (only the first name!) |
| `LOCATION` | 0.85 | `Fictional Maple Street` |
| `LOCATION` | 0.85 | `Springfield` |
| `DATE_TIME` | 0.85 | `March 14, 2026` |
| `URL` | 0.50 | `aarav.ve` (overlapping with email!) |
| `URL` | 0.50 | `example.com` (overlapping with email!) |

### Four lessons from this output

**1. Score tiers signal HOW something was detected.**

- `1.00` → deterministic regex with validation (email format, credit-card Luhn checksum). Zero semantic uncertainty.
- `0.85` → spaCy NER. Model is statistically right most of the time but not always.
- `0.75` → pattern regex without validation (phone has many formats; ambiguous).
- `0.50` → heuristic / weak overlap signal.

Confidence isn't arbitrary — it's a function of detector certainty. The reconciler (later phase) will use this.

**2. English NER misses non-Western surnames.**

`Aarav` was caught as `PERSON`, but `Verhoeff` was dropped. spaCy's `en_core_web_lg` is trained on English-language web text — it recognized `Aarav` (now a name common enough in English data) but not `Verhoeff` (fictional / non-Western). **This is the recall hole the India regex layer (Day 2) and the LLM extractor (Phase 4) exist to patch.** Not theoretical — saw it on the first scan.

**3. Detectors overlap and don't deduplicate.**

`EMAIL_ADDRESS` at offsets `200–226` fully contained two `URL` findings at `200–208` and `215–226`. Presidio's recognizers fire independently. **The reconciler we'll build in Day 3 has to handle this** — high-confidence span that contains lower-confidence ones should drop the inner spans. Without it: over-redaction, duplicate audit entries, confused downstream.

**4. NER thinks in atoms, not intents.**

The street address became two separate `LOCATION` findings (`Fictional Maple Street` + `Springfield`). NER tags street and city as separate entities. There is no `ADDRESS` entity type — that's a human concept I'd have to compose from the parts if I want to treat "the whole address" as one redaction unit.

### Sanity check at end of Day 1

Tried adding a 12-digit number `2345 6789 0123` (an Aadhaar-shaped string) to the sample text. **Presidio did not detect it.** No built-in recognizer for Aadhaar; spaCy NER doesn't tag arbitrary number sequences as PII. Confirmed: this is exactly where my custom India regex (Day 2) starts paying off.

### What I'd tell future-me

- Don't fight Presidio's defaults — understand the recognizers it ships, then layer on top.
- Score is a feature, not a number to ignore. The reconciler depends on it.
- The English-name bias is real and visible on the first try; don't trust Western-trained NER on Indian / non-Western data without evidence.

---

## Day 2 — 2026-05-30

### Aadhaar regex + Verhoeff checksum

Wrote `scratch/02_india_regex.py` — regex `\b(\d{4}[\s-]?\d{4}[\s-]?\d{4})\b` for 12-digit candidates in clean / spaced / dashed formats, then ran each candidate through the Verhoeff algorithm to filter out non-checksum-valid sequences.

Generated a safe synthetic Aadhaar using the prefix `00001234567` (since real Aadhaars never start with 0, the resulting `000012345676` is clearly non-real but structurally valid for testing).

### Lesson: Verhoeff is a STRUCTURAL check, not an AUTHENTICITY check

Tried a "random" 12-digit number `987654321012` in the sample expecting it to fail Verhoeff. **It passed.** Not a bug — that's expected probability.

**Why:** Verhoeff produces one check digit (0–9). For a random 12-digit number, ~1 in 10 will accidentally have a valid checksum. Verhoeff confirms the number is *shape-of-Aadhaar*; it cannot confirm the number is an *issued Aadhaar* — that would require the UIDAI database.

**Implication for our system:**

- Our regex + Verhoeff layer has a built-in ~10% false-positive rate on random 12-digit inputs.
- Acceptable for PII detection: over-flagging is safer than under-flagging. Downstream (reconciliation, treatment) will treat Aadhaar findings as `confidence: MEDIUM` until cross-confirmed.
- Refinements possible (but not v1):
  - UIDAI doesn't issue numbers starting with `0` or `1`. Constrain first digit.
  - First 4 digits encode issuing-agency code; only some codes are real (a whitelist could reduce FP).
- **Label hygiene:** the output label `VALID` is misleading — better wording is `PASSES VERHOEFF` because we can't actually say "this is a real Aadhaar."

### PAN regex + position-4 semantic check

PAN format: `[A-Z]{5}[0-9]{4}[A-Z]`, 10 chars, no checksum. Built two stages:

1. **Regex stage** — enforces the literal format. Anything wrong length, wrong case, or wrong character class is **silently rejected** (never reaches the validator).
2. **Semantic stage** — `pan_format_valid()` checks the 4th character against `PAN_ENTITY_TYPES`, a frozenset of the 10 recognized entity-type codes (`P`=Individual, `C`=Company, etc.).

### Lesson: two-stage filter (format then semantic) is a useful pattern

Test cases ran:

| Input | Regex result | Validator result |
|---|---|---|
| `ABCPK1234L` | matched | VALID (`P` is in allow-set) |
| `XYZCY9876Z` | matched | VALID (`C` is in allow-set) |
| `ABCXK1234L` | matched | INVALID (`X` not in allow-set) |
| `ABCPK1234` (9 chars) | **rejected silently** | (never reached) |
| `abcpk1234l` (lowercase) | **rejected silently** | (never reached) |

**Important:** silent regex rejection is a *feature*, not a bug. If something doesn't have the right shape, it can't be a PAN; we shouldn't waste cycles on validators downstream. The validator only runs on candidates that already passed format.

The same pattern will repeat across all India IDs we add later (GSTIN, IFSC, voter ID): regex enforces literal format → semantic check confirms internal consistency.

### Shared output shape across scanners

Both `scan_aadhaar` and `scan_pan` return `list[dict]` with the same keys: `{match, start, end, valid}`. Deliberate decision — the upcoming reconciler (Day 3) needs to merge findings from multiple sources, and uniform shape makes that one-liner instead of conditional branching per source.

### What I'd tell future-me (Day 2)

- Checksums tell you a number is *plausibly* an ID, not that it *is* an ID. Don't oversell them in audit copy.
- A ~10% false-positive rate is a feature of the format, not a regex bug. Don't fix it at the regex layer.
- Format-stage rejection is silent; semantic-stage rejection is loud (returns a finding with `valid=False`). Different signals, different downstream behavior.
- Pre-deciding the output shape across heterogeneous detectors costs nothing and saves hours later.

---

## Day 3 — 2026-05-31

### Unified `Finding` dataclass

Introduced `scratch/finding.py`:

```python
@dataclass(frozen=True)
class Finding:
    text: str
    start: int
    end: int
    entity_type: str
    detector: str
    confidence: float
    validated: bool
```

`frozen=True` makes instances immutable — the reconciler can't accidentally mutate a finding; if it needs different values it creates a new one. Frozen also enables hashing if we ever put Findings in sets.

### Refactored detectors to emit `Finding` (not `dict`)

`scan_aadhaar` and `scan_pan` in `india_regex.py` now return `list[Finding]`. `presidio_wrapper.scan_with_presidio` does the same for Presidio's `AnalyzerEngine`. All three detectors now speak the same shape — the precondition for a reconciler that doesn't care which source produced what.

Confidence scheme by detector:

| Detector | Validated case | Failed validator |
|---|---|---|
| Presidio | `r.score` (its own confidence) | n/a (no second-stage validator → always `validated=True`) |
| Aadhaar regex | 1.0 | 0.5 (kept, low-confidence) |
| PAN regex | 1.0 | 0.4 (kept, lower than Aadhaar — format is tighter, failures more suspicious) |

### The reconciler — algorithm

`scratch/03_reconcile.py` implements simple **wins-by-confidence**:

1. Sort findings by `(start ASC, confidence DESC)`. Ties on start go to highest-confidence first.
2. For each finding `f`:
   - Find all already-kept findings that overlap with `f` (using `_overlaps()` — standard interval-overlap formula: `a.start < b.end AND b.start < a.end`).
   - No overlaps → keep `f`.
   - `f` strictly higher than every overlapping → kick them out, keep `f`.
   - Otherwise → drop `f` silently.

V1 doesn't *merge* agreeing findings into a confidence-boosted single finding (e.g., if two detectors flag the same AADHAAR span at the same offsets, the higher one wins instead of the agreement boosting confidence). That's a v2 enhancement.

### Lesson: detector collisions are real, and reconciliation catches them

Sample text contained `4111-1111-1111-1111` (a test Visa). Presidio detected `CREDIT_CARD` at offsets `(224, 243)` conf=1.00. **My Aadhaar regex *also* matched** — the first 12 digits of the card, `4111-1111-1111`, at offsets `(224, 238)` conf=0.50 (Verhoeff failed, so low-confidence).

Same characters claimed by two detectors as different entities. Reconciler kicked out the Aadhaar candidate because CREDIT_CARD's confidence was strictly higher. **Without the reconciler, the system would have produced two overlapping findings of incompatible types — the downstream audit would have looked confused.**

This is the canonical case for *why* defense-in-depth needs reconciliation, not just OR-ing.

### Lesson: NER results depend on context, not just the name string

Day 1: my sample text had "Aarav Verhoeff" buried in a paragraph. Presidio caught only "Aarav" (5 chars, just the first name).

Day 3: the demo sample had "Name: Aarav Verhoeff" — the `Name:` prefix is a strong NER signal. Same name; Presidio caught the FULL "Aarav Verhoeff" entity (14 chars).

**Implication:** evals using sterile "PII in a vacuum" docs may *over-report* NER recall. Real-world recall depends on whether the surrounding text gives the model contextual cues. For our eval corpus, include both well-cued docs (forms with `Name:` labels) and uncued docs (free-form text) to stress this.

### Lesson: URL recognizer inside EMAIL recognizer is a deduplication problem, not a detection problem

Presidio's URL recognizer fires on substrings inside emails — `aarav.ve` and `example.com` both got flagged inside `aarav.verhoeff@example.com`. That's two URL findings at conf=0.50 fully contained inside an EMAIL_ADDRESS finding at conf=1.00. The reconciler eats them.

The lesson: don't try to suppress Presidio's noisy sub-recognizers at the detection layer (you'd lose useful signal in other contexts). Let the reconciler handle it. **Separate detection from deduplication.**

### What I'd tell future-me (Day 3)

- A frozen dataclass is the right shape for findings — small, immutable, free repr, free comparison.
- A shared output shape across detectors makes the reconciler one function instead of three conditional branches.
- Cross-detector collisions are real (Aadhaar regex vs CREDIT_CARD). Don't try to prevent them at the detector layer — handle them at the reconciler.
- The reconciler's "wins-by-confidence" rule is enough for v1. Cross-detector agreement → confidence boost is a v2 idea, not a v1 necessity.
- NER recall is context-dependent. Evals should stress this with mixed cued/uncued documents.

---

## Day 4 — 2026-05-31

### First LangGraph node

Installed `langgraph`, built a one-node `StateGraph`:

- **State:** a `TypedDict` with two fields — `document_text` (input) and `findings` (output).
- **Node:** `detect_node(state)` reads `document_text`, runs all three detectors, calls `reconcile()`, and returns `{"findings": deduped}` — a partial state update.
- **Edges:** `START → detect → END`.

The graph is **declarative**: I don't call `detect_node` myself. I declare it as a node, connect it with edges, `.compile()` the graph, then `.invoke()` it with an initial state.

### Lesson: structural-only changes should produce identical output

Output of Day 4 graph is byte-for-byte the same as Day 3's reconciler output — same 8 findings, same offsets, same scores. **That's the success criterion for Day 4.** If the agent-shaped wiring had changed the answer, I would have introduced an unintended logic change.

This is a useful invariant for future refactors: when restructuring a pipeline, the *first* version of the restructure should produce identical output to the old version. Then add the new behavior on top in a second pass.

### Mental model — what changed and what didn't

| Old | New |
|---|---|
| `reconcile(scan_with_presidio(t) + scan_aadhaar(t) + scan_pan(t))` | `app.invoke({"document_text": t, "findings": []})["findings"]` |
| Imperative chain of function calls | Declarative graph compiled to a runnable |
| Adding "decide treatment" = wrap the chain in another function | Adding "decide treatment" = add one node + one edge |

The extensibility is the value — invisible at one node, real at multiple. Day 5 makes it visible.

### Tiny LangGraph mechanics worth knowing

- A node returns a **partial dict** of updates, not the full state. LangGraph merges automatically. You never have to pass through fields you didn't change.
- `START` and `END` are LangGraph-provided sentinel nodes — every graph has them.
- Default merge semantics for state fields is **replace** (the node's return value clobbers whatever was there). When we add multiple nodes writing to the same field (e.g., an `audit_log` that accumulates across nodes), we'll need `Annotated[list, operator.add]` reducer. Not needed yet — only one node writes `findings`.

### What I'd tell future-me (Day 4)

- The hardest part of an agent isn't the agent — it's the deterministic plumbing the agent orchestrates. If that's solid, adding the graph layer is mechanical.
- "Same output as before" is a feature for the first version of any restructure. Only add new behavior in a *second* pass, never the first.
- Default LangGraph state merge is "replace per field." Reducers are the exception for accumulating fields. Don't reach for reducers until you need them.

---
