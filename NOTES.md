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

## Day 5 — 2026-05-31

### Two-node agent: detect + decide

Added:

- `scratch/treatment.py`: `Treatment` dataclass + the `TREATMENT_MATRIX` constant (entity_type × recipient_profile → action).
- `scratch/05_decide_agent.py`: extended state with `recipient_profile` and `treatments`. Added `decide_node` that performs matrix lookup per finding. Graph is now `START → detect → decide → END`.

`decide_node` makes **no LLM call.** It's a deterministic dict lookup. The "decision" is encoded in the matrix; the function just applies it. (Phase 4 will add an LLM-driven `policy_lookup` that can *override* the matrix toward stricter — never looser.)

### Lesson: state grows monotonically across nodes

| Node | Reads | Writes |
|---|---|---|
| `detect` | `document_text` | `findings` |
| `decide` | `findings`, `recipient_profile` | `treatments` |

Each node touches a different slice. LangGraph merges automatically — no need to pass through fields a node didn't change. This is the pattern that scales to 4, 5, 10 nodes without bookkeeping pain.

### Lesson: the demo screen-share is real

Same 8 findings → three different treatment outputs based on `recipient_profile`:

- **auditor** keeps almost everything; only masks AADHAAR / PAN / CREDIT_CARD (last-4-digits visible for verification)
- **vendor** pseudonymizes PERSON (preserves co-occurrence patterns), tokenizes EMAIL (reversible via vault), masks PHONE, redacts hard IDs
- **public** redacts everything sensitive; only LOCATION stays (city-level → not identifying)

One source → three policy-correct outputs. The "recipient-aware morphing" pitch is no longer theoretical.

### Decisions vs application — important distinction

The agent has now *decided* what to do with each finding. **It hasn't actually changed the document text.** The morphing step is Day 6 — the `apply` node will take `state["treatments"]` and rewrite `state["document_text"]` accordingly.

This separation matters: the decision logic is testable in isolation (assert "PERSON × vendor → pseudonymize" without ever applying anything). The application logic is testable in isolation (assert that `apply` of `redact` to offsets (10, 20) replaces those characters correctly). Coupling them would mean every test needs both. Keep them split.

### Tiny implementation choices worth knowing

- **Two-layer matrix fallback**: unknown `entity_type` → `DEFAULT_TREATMENT`; known `entity_type` but unknown `profile` → also `DEFAULT_TREATMENT`. Fail-safe: never silently keep PII we don't have a policy for. Default is `redact`.
- **LOCATION is "keep" in all three profiles** (v1 only): I'm scoping LOCATION to city-grain. A real implementation needs street-level detection + a per-grain treatment (street → redact, city → keep, country → keep). Future work.

### What I'd tell future-me (Day 5)

- Multi-node state flow is barely more code than single-node — once the first node works, adding the second is ~10 lines.
- Separating *decisions* from *application* is the right cut. Two simple steps beat one combined step that's hard to test.
- The treatment matrix is just config. Keep it boring data; resist the urge to make it a class hierarchy.
- A safe-by-default fallback (unknown → redact) is non-negotiable. The cost of over-redaction is a noisy output; the cost of under-redaction is a leak.

---

## Day 6 — 2026-05-31

### Three-node agent: detect → decide → apply

`apply_node` takes the Treatments from `decide` and rewrites the document text. Six action handlers wired up via a dispatch dict:

| Action | v1 implementation |
|---|---|
| `keep` | return source unchanged |
| `redact` | `[REDACTED]` |
| `mask` | last 4 chars visible, rest `*` |
| `pseudonymize` | `Person_<first 4 hex of sha256>` — deterministic |
| `tokenize` | `tok_<first 8 hex of sha256>` — deterministic; real vault lookup is Phase 5 |
| `generalize` | `[<TYPE>_GENERALIZED]` — placeholder; real impl needs per-type ranges (DOB → age decade, salary → band) |

Unknown actions fall back to `redact` — same fail-safe principle as the decide step.

### Lesson: tail-first replacement is critical AND silent

Sort treatments by `offset_start` DESCENDING, apply from the end of the document backwards. Without this, every variable-length replacement shifts all subsequent offsets, and the second/third/fourth replacements land at wrong characters.

The good outcome of getting this right is **boring**: clean output, no surprises. The bad outcome of getting it wrong is **subtle and silent**: text fragments interleaved with the wrong replacements, and no exception thrown.

**Three months from now, if anyone changes the loop order, this will quietly break.** The comment in the code (`# CRITICAL: sort by offset_start DESCENDING`) is the only thing protecting against the regression. Worth a unit test in Phase 5 that asserts:

- Two adjacent findings get morphed correctly
- A short replacement next to a long one doesn't corrupt either

### Lesson: deterministic pseudonymization is what makes the vendor profile useful

`Person_<sha256[:4]>` means the same input always produces the same output. `Aarav Verhoeff` → `Person_6a33` in every run, every document, forever (until the hash function changes).

**This property is load-bearing for the vendor use case.** A vendor doing analytics on the morphed data needs to see that `Person_6a33` appears in 100 documents and infer relationship structure — *without* learning the identity. Random pseudonyms would destroy that analytical utility.

(The downside: deterministic pseudonyms are vulnerable to **frequency-analysis attacks** when an attacker has external data. If `Person_6a33` appears 1000 times and only one CEO name appears 1000 times in your public hiring announcements, the mapping is recoverable. Acknowledge this — true anonymization needs k-anonymity or differential privacy. Pseudonymization is *not* anonymization.)

### Lesson: V1 limitations to acknowledge explicitly

- **LOCATION is `keep` everywhere.** Street-level redaction is future work. In the morphed output, `42 Fictional Maple Street, Springfield` stays intact across all three profiles.
- **`generalize` is a placeholder.** Real implementations need entity-specific ranges. Worth saying "v1 ships with 5 working actions + 1 placeholder" rather than overclaiming six.
- **Pseudonym collisions possible at scale.** 4 hex chars = 65,536 possible pseudonyms. A document with more than ~256 distinct PERSON entities is at risk of birthday-paradox collisions. Adequate for v1 demo docs (<10 names); future work for production.
- **No vault yet.** Tokens are computed hashes, not vault-stored. Phase 5 adds the real vault with reversibility under authorization.

### State now has 5 fields

| Field | Set by |
|---|---|
| `document_text` | input (graph caller) |
| `recipient_profile` | input (graph caller) |
| `findings` | `detect_node` |
| `treatments` | `decide_node` |
| `morphed_text` | `apply_node` |

Each node touches a different slice. The state grows monotonically; no node mutates what another wrote.

### Milestone: Phase 2 complete

Looking at the 6-phase plan:

| Phase | Status |
|---|---|
| 1. Deterministic baseline | ✅ Days 1–3 |
| 2. First agent (LangGraph) | ✅ Days 4–6 |
| 3. Measure (eval corpus) | next |
| 4. LLM where eval says yes | pending |
| 5. Ship V1 | pending |
| 6. V2 stretch | pending |

End-to-end: input doc → detection → reconciliation → decision → application → morphed doc. Working. With three demoable profiles. That's the spine of the system.

### What I'd tell future-me (Day 6)

- Tail-first replacement is the kind of bug that doesn't throw — it silently corrupts. Add a comment, add a test, move on.
- Deterministic pseudonymization is a feature, not a shortcut. Don't replace it with random pseudonyms "for security" without understanding what you'd lose.
- Pseudonymization ≠ anonymization. Be honest about this. K-anonymity / differential privacy are different tools for different problems.
- Three working profiles are enough for v1. Adding a fourth is a 10-minute matrix edit; adding the fifth action handler is more interesting and only happens when the matrix demands it.

---

## Day 7 — 2026-05-31

### Phase 3 begins: building the eval corpus

Started `eval/` directory. Structure:

```
eval/
  README.md              — corpus design + format spec
  build_corpus.py        — programmatic builder (computes offsets in lockstep)
  validate_corpus.py     — asserts every label's text matches text[start:end]
  corpus/                — output: one JSON per labeled doc
    resume_001.json
    resume_002.json
    resume_003.json
```

Three resume docs labeled and passing validation. 17 labeled spans total across the 3 docs.

### Lesson: never count offsets by hand

The corpus builder uses an `_add(text, labels, span, type)` helper that appends a PII span to the running text AND records its label with computed offsets in the same step. Two consequences:

1. **The offsets cannot drift relative to the text** — they're computed from `len(text)` at the moment of insertion.
2. **Editing a doc just means re-running `build_corpus.py`** — offsets are recomputed automatically. No "find/replace and pray."

This pattern is the right shape for any test corpus where you'd otherwise hand-count character positions. The 30 minutes spent writing the builder buys back hours of correctness later.

### Lesson: build the validator before you build the corpus

`validate_corpus.py` is 50 lines and pays for itself the first time anyone edits a doc by hand. It compares `text` field vs `text[start:end]` for every label. Mismatch → loud failure.

In Phase 5 (when the corpus has 15+ docs), this validator runs in CI. For now, run it manually after any edit.

### What I'd tell future-me (Day 7)

- Offsets-in-lockstep with text-in-progress is a universal pattern for test data with positional labels (NER, span extraction, token classification). Reach for it whenever the test data has hand-computed positions.
- A 50-line validator is cheaper than one hour of mysterious test failure. Write the validator before you write the test data.
- A 3-doc corpus is enough to validate the format. Don't generate 30 docs until you've confirmed the schema works at 3.

---

## Day 8 — 2026-05-31

### Corpus scaled to 15 docs across 5 genres

| Genre | Docs | Labels |
|---|---|---|
| resume | 3 | 17 |
| indian_gov_form | 3 | ~19 |
| customer_support | 3 | ~13 |
| internal_chat | 3 | ~12 |
| clean_control | 3 | 0 (false-positive check) |
| **total** | **15** | **60** |

### First real eval — the numbers

Run: `python eval/run_eval.py` on the 15-doc / 60-label corpus.

| Config | TP | FP | FN | Recall | Precision | F1 |
|---|---|---|---|---|---|---|
| presidio_only | 45 | 35 | 15 | 75.00% | 56.25% | 64.29% |
| regex_only (Aadhaar+PAN) | 6 | 2 | 54 | 10.00% | 75.00% | 17.65% |
| merged_unreconciled | 51 | 37 | 9 | 85.00% | 57.95% | 68.92% |
| **merged_reconciled** | **51** | **18** | **9** | **85.00%** | **73.91%** | **79.07%** |

Treatment accuracy on the reconciled pipeline: **100%** across all three profiles (51/51). This is by construction — the matrix that `decide_node` reads is the same matrix the labels are built against. It's a sanity-check metric, not a quality metric.

### Lesson: the reconciler earns its keep — +10 F1 from overlap math alone

`merged_unreconciled → merged_reconciled`:

- TPs unchanged (51 → 51): reconciler doesn't drop real findings.
- FPs cut nearly in half (37 → 18): URLs inside emails get eaten, Aadhaar regex matching the first 12 digits of credit cards gets dropped, etc.
- F1 jumps **+10.15 points** (68.92% → 79.07%).

Zero new ML. Pure interval-overlap logic. **This is the headline result for the interview defense of the reconciler design.**

### Lesson: defense-in-depth in numbers

Each detector alone:
- Presidio alone: 75% recall
- Regex alone: 10% recall

Merged (no reconcile): 85% recall. That's **+10 points of recall** just from adding the cheap regex layer to Presidio. The detectors are complementary by design — Presidio misses Indian IDs, the regex doesn't know names — and the numbers show it.

### Lesson: 9 FN remaining on merged_reconciled is the Phase 4 motivation

The 9 missed labels (15% miss rate) are almost certainly:

- Indian PERSON entities the English-trained spaCy NER doesn't recognize ("Sneha Testdoc", "Priyanka Faketest", "Anjali Testname" etc.)
- Possibly Indian city LOCATIONs that spaCy doesn't tag confidently

This is exactly where an LLM extractor (Phase 4) earns its place — context-aware extraction over names and entities that don't match Western training distributions. Adding the LLM should:

- Reduce FN (improve recall)
- Possibly add some FPs (LLMs hallucinate)
- Bring per-doc cost up, but selectively (router skips LLM when cheap detectors already agree)

The cost-routing story is exactly the trade we'll measure in Phase 4.

### Numbers I can quote in interview (test-set, defensible)

> "On a 15-doc, 60-label eval corpus, the merged-and-reconciled pipeline hits 85% recall, 74% precision, 79% F1. The reconciler alone is worth +10 F1 points by removing overlapping false positives without dropping any true positives. The 15% recall gap is concentrated on non-Western names spaCy doesn't recognize — that's the motivation for an LLM-extractor layer."

Honest framing: this is a small, synthetic corpus. Real-world numbers will differ. The *relative ordering* of approaches and the *direction* of the wins should transfer.

### What I'd tell future-me (Day 8)

- The first number you measure is the most useful number — even on a tiny corpus, it tells you which way to push.
- Treatment-accuracy = 100% is a sanity-check, not a brag. Don't quote it as a quality result.
- "Reconciler +10 F1" is a teachable result. It encodes the entire "do reconciliation properly" argument in one number.
- The remaining FNs map cleanly to a hypothesis (English NER misses Indian names). Phase 4 will test that hypothesis with a different detector.

---

## Day 10 — 2026-05-31

### LLM factory wired

`scratch/llm_factory.py` — single `get_llm()` returning a LangChain `BaseChatModel` based on the `LLM_PROVIDER` env var. Default: ollama. Supports gemini and openai by changing one env var; never need to touch code.

Imports are **lazy inside the function** so we don't load all three SDKs on every call. Per-provider model overrides via `OLLAMA_MODEL` / `GEMINI_MODEL` / `OPENAI_MODEL`.

Smoke test (`scratch/10_llm_hello.py`) confirms the chain works end-to-end with Ollama + llama3.2:3b.

### Lesson: factory pattern locks in optionality before commitment

By forcing every LLM call to go through `get_llm()`, swapping providers becomes a one-env-var change. The cost of writing this factory is ~30 lines and zero ongoing maintenance; the cost of NOT writing it is grep-and-replace pain when you eventually want to compare providers (or fall back to a cheaper one in production).

The Gemini docstring in the factory also locks in the **Gemini 3.0+ temperature trap** memory: default is `1.0`, dropping to `0.7` causes infinite loops, go straight to `0.1` if you need determinism. Easier to read it in the right place at write-time than to hit the trap at runtime.

### Next: Day 11 will test whether 3b is "enough"

llama3.2:3b handles free-text generation easily (the smoke test was trivial for it). Structured-output extraction is qualitatively harder — small models sometimes return malformed JSON or invent offsets. Mitigations baked into Day 11:

- LangChain's `.with_structured_output()` retries automatically on validation failure.
- Verify offsets at the boundary: `text[finding.start:finding.end] == finding.text`; drop mismatches.

If 3b can't hold the Pydantic schema reliably even with retries, the fallback is `llama3.1:8b` (5GB pull) or `qwen2.5:7b` (better at structured tasks), set via `OLLAMA_MODEL`. Or pivot to Gemini for the eval (`LLM_PROVIDER=gemini`).

---

## Day 11 — 2026-05-31

### LLM extractor wired and measured — Phase 4 hypothesis confirmed

`scratch/llm_extractor.py`: `scan_with_llm(text)` returns `list[Finding]` using LangChain's `.with_structured_output()` against a Pydantic `LLMFindings` schema.

**Design choice that makes 3b models work better:** don't ask the LLM for character offsets. The LLM returns only `text + entity_type`; Python's `str.find()` does the offsetting. This sidesteps the LLM's well-known weakness at counting characters AND makes hallucination-checking trivial (a substring not found = drop). Also finds **all occurrences** of a repeated span, not just the first.

### Eval — full table at 15 docs / 60 labels

```
config                     TP   FP   FN   recall    precision   F1
all_four_reconciled        58   18    2   96.67%    76.32%   85.29%   ← lowest FNs
llm_only                   49    3   11   81.67%    94.23%   87.50%   ← highest F1
merged_no_llm_reconciled   51   18    9   85.00%    73.91%   79.07%
presidio_only              45   35   15   75.00%    56.25%   64.29%
regex_only                  6    2   54   10.00%    75.00%   17.65%
```

### Headline lesson: the LLM adds 7 true positives the deterministic stack misses

`merged_no_llm_reconciled` → `all_four_reconciled`:
- +7 TP (51 → 58)
- **−7 FN (9 → 2)**
- Recall jumps from 85% to **96.67%** — 4.5× fewer leaks
- Precision drops slightly (74% → 76%) — actually IMPROVES because the LLM is highly precise
- F1 climbs from 79.07% to 85.29%

The Phase 4 hypothesis (LLM helps catch Indian-name PERSON entities) is confirmed. Per-doc evidence:
- `indian_gov_form_002`: merged_no_llm 5/6 → all_four 6/6
- `indian_gov_form_003`: merged_no_llm 5/6 → all_four 6/6
- `internal_chat_003`: merged_no_llm 2/5 → all_four 5/5 (LLM caught 3 of 3 Indian names spaCy missed)

### Lesson: recall > F1 for a privacy use case

`llm_only` has the highest F1 (87.50%), but `all_four_reconciled` has the highest recall (96.67%). **For a privacy guardrail, optimizing for F1 is the wrong metric.** A leak (missed PII) is a real-world breach; over-redaction is just noisy.

The interview defense: *"My eval shows the LLM extractor adds 7 TPs that the deterministic detectors miss, bringing recall to 96.67%. F1 favors the LLM-only configuration at 87.5%, but for privacy I optimize for recall, not F1 — the cost of a missed Aadhaar in production isn't comparable to the cost of a redacted phone number that didn't need to be."*

### Lesson: 3b models have run-to-run variance even at temperature=0.1

Two consecutive eval runs:
- Run 1 (interrupted, partial): `llm_only` was TP=51, FP=2, FN=9 — F1=90.27%
- Run 2 (full): `llm_only` was TP=49, FP=3, FN=11 — F1=87.50%

Same code, same model, same temperature. **5% variance in TP/FN on a 60-label corpus at this model size.** Implications:

- The deterministic detectors (Presidio, regex) ARE deterministic — Presidio's numbers were identical in both runs.
- LLM determinism is a *spectrum* depending on size, sampling, and prompt sensitivity. Smaller models = more variance.
- For audit/compliance contexts that require reproducible output, this matters. **Document the per-run variance honestly; don't claim deterministic behavior the system doesn't have.**
- Mitigation: log every LLM input/output so a discrepancy is reviewable post-hoc. Don't try to eliminate variance at the cost of recall.

### One real bug to flag for Phase 5 polish

`resume_002` per-doc: `llm_only` got 6/6 (perfect) but `all_four_reconciled` got 5/6 (one FN). Reconciler appears to have *kept a lower-quality Presidio span that doesn't match a label*, when it could have kept the LLM's better span.

Hypothesis: Presidio's PERSON conf=0.85 > LLM's PERSON conf=0.8. When both overlap, reconciler picks Presidio. But if Presidio's span doesn't cover the full labeled entity (e.g., just "Priya" instead of "Priya Datacheck"), the greedy span-matcher may end up paired with the partial Presidio span instead of the full LLM span.

Fix candidates (Phase 5):
1. **Same-type tie should prefer the longer span** (more complete coverage).
2. **Boost confidence when two detectors agree on entity_type** at overlapping offsets (the cross-detector-agreement idea from earlier docs).
3. Tune LLM confidence above Presidio's NER confidence (0.85+).

Not urgent. Recall is still 96.67% overall. Note for the v1 polish phase.

### What I'd tell future-me (Day 11)

- For privacy systems, recall is the metric. Lead with recall; report F1 only as a sanity check.
- 3b is "good enough" for structured PII extraction when you DON'T ask for offsets. Save the model from things it's bad at; do them in Python.
- LLM determinism isn't real at 3b scale — document the variance, don't pretend it isn't there.
- Cross-detector reconciliation with simple "wins-by-confidence" leaves recall on the table when a lower-confidence detector has the better span. Same-type-prefer-longer-span is the v1 polish fix.

---

## Day 12 — 2026-05-31

### Cost-routing wired into the agent

`scratch/12_routed_agent.py`: same three-node graph (detect / decide / apply) as Day 6, but `detect_node` now decides whether to call the LLM based on the cheap detectors' output.

The routing rule (v1, conservative by design):

```python
def should_call_llm(text, cheap_findings) -> bool:
    matrix_relevant = [f for f in cheap_findings if f.entity_type in TREATMENT_MATRIX]
    if matrix_relevant:                     # cheap found PII we care about → call LLM (more recall possible)
        return True
    if any(marker in text for marker in PII_SYNTAX_MARKERS):
        return True                         # cheap found nothing but doc has PII syntax → call LLM
    return False                            # cheap found nothing AND no markers → safe to skip
```

Plus a new state field `llm_called: bool` so audit / monitoring downstream can see whether the LLM was consulted.

### Bug discovered AND fixed: agent was silently redacting non-PII

Demo on a generic policy doc:
> "...customer records are kept for seven years to comply..."

Output: `"...customer records are kept for [REDACTED] to comply..."`

**Why:** Presidio fired on `DATE_TIME` for "seven years". Our matrix has no policy for `DATE_TIME`. `decide_node` fell through to `DEFAULT_TREATMENT = "redact"`. `apply_node` redacted it. Silent — no warning, no exception, just disappearing words.

**Fix:** filter `findings` to `entity_type in TREATMENT_MATRIX` at the end of `detect_node`. The agent only acts on types it has explicit policy for. Anything Presidio reports outside the matrix is dropped *before* it reaches decide.

### Lesson: matrix is the agent's source of truth — filter at the boundary

The routing rule already filtered cheap findings to matrix-relevant types when deciding whether to escalate. But the downstream pipeline (decide / apply) had no such filter. The mismatch produced the bug.

The fix is the right pattern: **decide what the agent cares about once, at the detection boundary, and let that filter define the rest of the pipeline.** Anywhere else where the matrix gets consulted (decide, apply, audit) inherits the filter automatically. New entity type means one matrix row, not edge-case logic scattered across nodes.

### Lesson: demos with non-PII content are bug-finders

If the demo had only used PII-rich documents (resumes, gov forms), this bug would have shipped silently — the DATE_TIME finding in a resume would have been overwhelmed by the actual PII findings, and "seven years" would have been a buried side effect. **The clean-control marketing/policy documents I added to the eval corpus were what made the bug visible** — same docs as `clean_control_001/002/003` in `eval/corpus/`.

This is why control documents matter in any test corpus, not just the "positive" cases.

### Routing impact

For local Ollama (free), the routing is mostly hygiene. For paid Gemini / OpenAI via `LLM_PROVIDER=gemini`, the same routing reduces LLM calls on docs that don't need them — on the 15-doc corpus, the 3 clean_control docs (20%) get the skip path. Practical cost reduction with zero recall impact (clean docs have no PII to miss).

### What I'd tell future-me (Day 12)

- A privacy guardrail that operates on entity types the matrix doesn't recognize is broken in a quiet way. Filter at the detection boundary.
- Cost-routing for paid LLMs is a "v1 polish" feature when on local LLM. The architecture matters more than the savings at this stage.
- Control documents in eval corpora aren't there for the FP count alone — they're bug-discovery instruments.
- When routing logic and downstream logic disagree about which findings matter, you have a bug. Make consistency the design rule.

---
