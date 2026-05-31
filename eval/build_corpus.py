"""Build the eval corpus programmatically.

The trick: build the text and the labels in LOCKSTEP. Every time we append
a PII span, we know its start/end offsets because we just wrote them. No
character counting by hand. No offset drift when the surrounding text changes.

Each builder function returns a dict matching the eval/README.md label schema:
  {doc_id, genre, text, labels: [{text, start, end, entity_type, treatments}]}
"""

import json
from pathlib import Path


# Per-entity treatment defaults — used by every builder.
# Same shape as scratch/treatment.py's TREATMENT_MATRIX but lives here so the
# corpus is self-contained.
TREATMENTS = {
    "PERSON":        {"auditor": "keep", "vendor": "pseudonymize", "public": "pseudonymize"},
    "EMAIL_ADDRESS": {"auditor": "keep", "vendor": "tokenize",     "public": "redact"},
    "PHONE_NUMBER":  {"auditor": "keep", "vendor": "mask",         "public": "redact"},
    "LOCATION":      {"auditor": "keep", "vendor": "keep",         "public": "keep"},
    "AADHAAR":       {"auditor": "mask", "vendor": "redact",       "public": "redact"},
    "PAN":           {"auditor": "mask", "vendor": "redact",       "public": "redact"},
    "CREDIT_CARD":   {"auditor": "mask", "vendor": "redact",       "public": "redact"},
}


def _add(text: str, labels: list, span: str, entity_type: str) -> str:
    """Append `span` to `text`, record a label with computed offsets.

    Returns the new text. `labels` is mutated in place (cheaper than
    threading two return values through every builder).
    """
    start = len(text)
    new_text = text + span
    end = len(new_text)
    labels.append({
        "text": span,
        "start": start,
        "end": end,
        "entity_type": entity_type,
        "treatments": TREATMENTS[entity_type],
    })
    return new_text


# ─────────────────────────────────────────────────────────────────────────────
# Doc 1: a standard resume with English-friendly PII (good for Presidio + spaCy)
# ─────────────────────────────────────────────────────────────────────────────

def build_resume_001():
    labels: list = []
    text = ""
    text = _add(text, labels, "Aarav Verhoeff", "PERSON")
    text += "\nSoftware Engineer\nEmail: "
    text = _add(text, labels, "aarav.verhoeff@example.com", "EMAIL_ADDRESS")
    text += " | Phone: "
    text = _add(text, labels, "+1-202-555-0123", "PHONE_NUMBER")
    text += "\nAddress: 42 "
    text = _add(text, labels, "Fictional Maple Street", "LOCATION")
    text += ", "
    text = _add(text, labels, "Springfield", "LOCATION")
    text += "\n\nEXPERIENCE\nAcme Corp — Senior Backend Engineer (2022-Present)\n"
    text += "  Led the migration of legacy services to microservices.\n\n"
    text += "EDUCATION\nBTech in Computer Science (2018-2022)"

    return {
        "doc_id": "resume_001",
        "genre": "resume",
        "text": text,
        "labels": labels,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Doc 2: a resume with India-specific entities (Aadhaar + PAN inline)
# This is the kind of doc Presidio's defaults will under-detect.
# ─────────────────────────────────────────────────────────────────────────────

def build_resume_002():
    labels: list = []
    text = "Application form\n\nFull name: "
    text = _add(text, labels, "Priya Datacheck", "PERSON")
    text += "\nContact: "
    text = _add(text, labels, "priya.datacheck@example.test", "EMAIL_ADDRESS")
    text += "\nMobile: "
    text = _add(text, labels, "+1-202-555-0199", "PHONE_NUMBER")
    text += "\n\nIdentity documents:\n  Aadhaar: "
    # Valid Verhoeff Aadhaar with 0000 prefix (clearly synthetic).
    text = _add(text, labels, "0000 1234 5676", "AADHAAR")
    text += "\n  PAN: "
    # ZZZZP1234X — 4 Zs as a fictional-prefix marker, P=Individual, valid format.
    text = _add(text, labels, "ZZZZP1234X", "PAN")
    text += "\n\nCurrent city: "
    text = _add(text, labels, "Bengaluru", "LOCATION")
    text += "\nReferences available on request."

    return {
        "doc_id": "resume_002",
        "genre": "resume",
        "text": text,
        "labels": labels,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Doc 3: a more chatty resume with a credit card on file (rare but real —
# some freelance/onboarding forms collect this).
# ─────────────────────────────────────────────────────────────────────────────

def build_resume_003():
    labels: list = []
    text = "Freelancer profile — "
    text = _add(text, labels, "Rohan Testname", "PERSON")
    text += "\n\nPreferred email: "
    text = _add(text, labels, "rohan.testname@example.com", "EMAIL_ADDRESS")
    text += "\nBackup phone (text only): "
    text = _add(text, labels, "+1-202-555-0177", "PHONE_NUMBER")
    text += "\n\nPayment method on file:\n  Card: "
    text = _add(text, labels, "4111-1111-1111-1111", "CREDIT_CARD")
    text += " (test card, do not charge)\n  Billing city: "
    text = _add(text, labels, "Pune", "LOCATION")
    text += "\n\nNotes: Available for backend Python work, prefers async / Celery stacks."

    return {
        "doc_id": "resume_003",
        "genre": "resume",
        "text": text,
        "labels": labels,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main — write each builder's output as JSON in eval/corpus/
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    out_dir = Path(__file__).parent / "corpus"
    out_dir.mkdir(exist_ok=True)

    builders = [build_resume_001, build_resume_002, build_resume_003]

    for builder in builders:
        doc = builder()
        path = out_dir / f"{doc['doc_id']}.json"
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote {path.name}  ({len(doc['labels'])} labels)")

    print(f"\nDone. Run `python eval\\validate_corpus.py` to verify offsets.")
