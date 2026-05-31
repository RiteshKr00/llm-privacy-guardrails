# LLM Privacy Guardrails

An agentic privacy layer for LLM pipelines. Detects PII (including India-specific
Aadhaar / PAN), reasons about per-recipient treatment, and produces a morphed
document with a defensible audit trail.

Built with **LangGraph + LangChain + Presidio + spaCy + Ollama** (or any
LangChain-supported provider — swappable via env var).

## Install

```powershell
python -m venv piienv
.\piienv\Scripts\Activate.ps1
pip install -e .
python -m spacy download en_core_web_lg
```

For local LLM inference, install [Ollama](https://ollama.com) and pull a model:

```powershell
ollama pull llama3.2:3b
```

## Demo

```powershell
python demo.py
```

Output: the same source document morphed three ways (auditor / vendor / public).

## How it works

Three-node LangGraph pipeline:

```
detect → decide → apply
```

- **detect** — Runs Presidio, India-specific regex (Aadhaar with Verhoeff
  checksum, PAN with position-4 entity-type validation), and an LLM extractor
  (cost-routed). Reconciles overlaps via wins-by-confidence. Filters to
  matrix-relevant entity types.
- **decide** — Per finding, looks up `TREATMENT_MATRIX[entity_type][profile]`
  to produce a `Treatment` record. Deterministic, config-driven.
- **apply** — Rewrites the document with tail-first replacement (preserves
  offsets across variable-length substitutions).

## Eval

On a 15-doc / 60-label synthetic corpus (`eval/corpus/`):

| Config | Recall | Precision | F1 |
|---|---|---|---|
| presidio_only | 75.00% | 56.25% | 64.29% |
| regex_only (Aadhaar+PAN) | 10.00% | 75.00% | 17.65% |
| llm_only | 81.67% | 94.23% | 87.50% |
| merged_no_llm_reconciled | 85.00% | 73.91% | 79.07% |
| **all_four_reconciled** | **96.67%** | **76.32%** | **85.29%** |

Run yourself: `python eval/run_eval.py`

## Build log

See [`NOTES.md`](NOTES.md) for the day-by-day engineering record — design
decisions, bugs encountered and fixed, real measured numbers, and honest
limitations.

## License

MIT
