"""Build the eval corpus programmatically.

The trick: build the text and the labels in LOCKSTEP. Every time we append
a PII span, we know its start/end offsets because we just wrote them. No
character counting by hand. No offset drift when the surrounding text changes.

Each builder function returns a dict matching the eval/README.md label schema:
  {doc_id, genre, text, labels: [{text, start, end, entity_type, treatments}]}
"""

import json
from pathlib import Path

from llm_privacy_guardrails.detectors.india_regex import synthetic_valid_aadhaar


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
# Indian government form genre — Aadhaar/PAN-heavy, Presidio's blind spot
# ─────────────────────────────────────────────────────────────────────────────

def build_indian_gov_form_001():
    """Aadhaar enrollment form."""
    labels: list = []
    aadhaar = synthetic_valid_aadhaar("00001234567")
    text = "AADHAAR ENROLMENT / UPDATE FORM\n\nApplicant Name: "
    text = _add(text, labels, "Vikram Testchan", "PERSON")
    text += "\nFather's Name: "
    text = _add(text, labels, "Suresh Testchan", "PERSON")
    text += "\nDate of Birth: 15-June-1990\nMobile: "
    text = _add(text, labels, "+1-202-555-0145", "PHONE_NUMBER")
    text += "\nEmail: "
    text = _add(text, labels, "vikram.testchan@example.com", "EMAIL_ADDRESS")
    text += "\n\nExisting Aadhaar (for update): "
    text = _add(text, labels, aadhaar, "AADHAAR")
    text += "\n\nResidential Address:\n  Block A, "
    text = _add(text, labels, "Test Lane", "LOCATION")
    text += ", "
    text = _add(text, labels, "Mumbai", "LOCATION")
    text += " 400001"
    return {"doc_id": "indian_gov_form_001", "genre": "indian_gov_form", "text": text, "labels": labels}


def build_indian_gov_form_002():
    """PAN application form."""
    labels: list = []
    text = "Form 49A — Application for PAN\n\nFull Name: "
    text = _add(text, labels, "Ananya Testdata", "PERSON")
    text += "\nFather's Name: "
    text = _add(text, labels, "Rakesh Testdata", "PERSON")
    text += "\nDate of Birth: 22-March-1985\nMobile: "
    text = _add(text, labels, "+1-202-555-0156", "PHONE_NUMBER")
    text += "\nEmail (for OTP): "
    text = _add(text, labels, "ananya.testdata@example.test", "EMAIL_ADDRESS")
    text += "\n\nExisting PAN (if reapply): "
    text = _add(text, labels, "ZZZZP9876Y", "PAN")
    text += "\nCommunication address city: "
    text = _add(text, labels, "Hyderabad", "LOCATION")
    return {"doc_id": "indian_gov_form_002", "genre": "indian_gov_form", "text": text, "labels": labels}


def build_indian_gov_form_003():
    """GST registration form — proprietor's IDs."""
    labels: list = []
    aadhaar = synthetic_valid_aadhaar("00002345678")
    text = "GST Registration — Proprietor Details\n\nProprietor Name: "
    text = _add(text, labels, "Rohan Mocktest", "PERSON")
    text += "\nProprietor PAN: "
    text = _add(text, labels, "ZZZZP1122M", "PAN")
    text += "\nProprietor Aadhaar: "
    text = _add(text, labels, aadhaar, "AADHAAR")
    text += "\nMobile: "
    text = _add(text, labels, "+1-202-555-0188", "PHONE_NUMBER")
    text += "\nEmail: "
    text = _add(text, labels, "rohan.mocktest@example.com", "EMAIL_ADDRESS")
    text += "\nPrincipal Place of Business: "
    text = _add(text, labels, "Chennai", "LOCATION")
    return {"doc_id": "indian_gov_form_003", "genre": "indian_gov_form", "text": text, "labels": labels}


# ─────────────────────────────────────────────────────────────────────────────
# Customer support genre — chat/email style, names + emails + phones in prose
# ─────────────────────────────────────────────────────────────────────────────

def build_customer_support_001():
    """Inbound email complaint."""
    labels: list = []
    text = "Subject: Order #98765 not delivered\n\nHi support,\n\nMy name is "
    text = _add(text, labels, "Anjali Testname", "PERSON")
    text += " and my order from last week hasn't arrived. The shipping address was 14 "
    text = _add(text, labels, "Park Lane", "LOCATION")
    text += ", "
    text = _add(text, labels, "Pune", "LOCATION")
    text += ". You can reach me at "
    text = _add(text, labels, "anjali.testname@example.com", "EMAIL_ADDRESS")
    text += " or call "
    text = _add(text, labels, "+1-202-555-0167", "PHONE_NUMBER")
    text += ".\n\nThanks,\nAnjali"
    return {"doc_id": "customer_support_001", "genre": "customer_support", "text": text, "labels": labels}


def build_customer_support_002():
    """Chat transcript — refund request."""
    labels: list = []
    text = "[chat] Customer: Hi, I want to request a refund.\n[chat] Agent: Sure, can I get your name and order ID?\n[chat] Customer: I'm "
    text = _add(text, labels, "John Testchan", "PERSON")
    text += ", order ID is 555-44-3322. My email is "
    text = _add(text, labels, "john.testchan@example.com", "EMAIL_ADDRESS")
    text += ".\n[chat] Agent: Thanks. Refund processed to card on file.\n[chat] Customer: Great, do you have my number too? It's "
    text = _add(text, labels, "+1-202-555-0102", "PHONE_NUMBER")
    text += " if you need to text confirmation."
    return {"doc_id": "customer_support_002", "genre": "customer_support", "text": text, "labels": labels}


def build_customer_support_003():
    """Internal phone-call notes after escalation."""
    labels: list = []
    text = "Call notes — escalation #ESC-2245\n\nCaller: "
    text = _add(text, labels, "Maya Datacheck", "PERSON")
    text += "\nCallback number: "
    text = _add(text, labels, "+1-202-555-0119", "PHONE_NUMBER")
    text += "\nEmail on file: "
    text = _add(text, labels, "maya.datacheck@example.test", "EMAIL_ADDRESS")
    text += "\nResidence (verified): "
    text = _add(text, labels, "Bengaluru", "LOCATION")
    text += "\n\nIssue: payment failed three times on card ending "
    text = _add(text, labels, "4111-1111-1111-1111", "CREDIT_CARD")
    text += ". Agent agreed to retry once after manual review."
    return {"doc_id": "customer_support_003", "genre": "customer_support", "text": text, "labels": labels}


# ─────────────────────────────────────────────────────────────────────────────
# Internal chat genre — Slack/email casual, mixed PII
# ─────────────────────────────────────────────────────────────────────────────

def build_internal_chat_001():
    """Slack-style channel message."""
    labels: list = []
    text = "@channel reminder — onboarding session today at 3pm. New joiner is "
    text = _add(text, labels, "Kavya Synthname", "PERSON")
    text += ", reach out at "
    text = _add(text, labels, "kavya.synthname@example.com", "EMAIL_ADDRESS")
    text += " if you want to introduce yourself before then. Office is in "
    text = _add(text, labels, "Gurgaon", "LOCATION")
    text += "; she'll be remote first month."
    return {"doc_id": "internal_chat_001", "genre": "internal_chat", "text": text, "labels": labels}


def build_internal_chat_002():
    """Forwarded internal email snippet."""
    labels: list = []
    text = "From: "
    text = _add(text, labels, "Arjun Faketest", "PERSON")
    text += " <"
    text = _add(text, labels, "arjun.faketest@example.com", "EMAIL_ADDRESS")
    text += ">\nTo: backend-team@example.com\nSubject: deployment window\n\nAll, the deploy window is locked for 10 PM tonight. If anything blocks, ping me on "
    text = _add(text, labels, "+1-202-555-0133", "PHONE_NUMBER")
    text += " directly — I'm working from "
    text = _add(text, labels, "Delhi", "LOCATION")
    text += " timezone."
    return {"doc_id": "internal_chat_002", "genre": "internal_chat", "text": text, "labels": labels}


def build_internal_chat_003():
    """Stand-up notes — names in passing."""
    labels: list = []
    text = "Daily stand-up — 31 May\n\nPresent: "
    text = _add(text, labels, "Sneha Testdoc", "PERSON")
    text += ", "
    text = _add(text, labels, "Rahul Mockname", "PERSON")
    text += ", "
    text = _add(text, labels, "Priyanka Faketest", "PERSON")
    text += ".\n\nBlockers:\n  - "
    text = _add(text, labels, "Sneha Testdoc", "PERSON")
    text += " is waiting on infra ticket for the new "
    text = _add(text, labels, "Mumbai", "LOCATION")
    text += " region rollout."
    return {"doc_id": "internal_chat_003", "genre": "internal_chat", "text": text, "labels": labels}


# ─────────────────────────────────────────────────────────────────────────────
# Clean control genre — NO PII. Tests for false positives.
# `labels` is intentionally empty.
# ─────────────────────────────────────────────────────────────────────────────

def build_clean_control_001():
    """Marketing copy for a generic product page."""
    return {
        "doc_id": "clean_control_001",
        "genre": "clean_control",
        "text": (
            "Introducing our latest privacy-first analytics platform. Designed for "
            "engineering teams that need observability without compromising data "
            "sovereignty. Easy to deploy on-premises or in any cloud. Compatible "
            "with existing log aggregation pipelines. Pricing starts at the basic tier."
        ),
        "labels": [],
    }


def build_clean_control_002():
    """Internal policy text — describes policies, names no individuals."""
    return {
        "doc_id": "clean_control_002",
        "genre": "clean_control",
        "text": (
            "Data retention policy:\n\nAll customer transaction records are retained "
            "for seven years to comply with financial-reporting obligations. After "
            "that period, records are archived to cold storage for an additional "
            "three years, then deleted. Engineering logs are retained for ninety "
            "days. Access patterns to retained data are audited monthly."
        ),
        "labels": [],
    }


def build_clean_control_003():
    """General technical article — no individual identifiers."""
    return {
        "doc_id": "clean_control_003",
        "genre": "clean_control",
        "text": (
            "The Verhoeff checksum algorithm uses two precomputed lookup tables "
            "to detect single-digit errors and adjacent-digit swaps in ID numbers. "
            "It was designed specifically for human-typed identifiers where these "
            "two error classes dominate. Modern uses include several national-ID "
            "systems. The algorithm produces a single check digit that, when "
            "appended, makes the full sequence sum to zero under the table operations."
        ),
        "labels": [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main — write each builder's output as JSON in eval/corpus/
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    out_dir = Path(__file__).parent / "corpus"
    out_dir.mkdir(exist_ok=True)

    builders = [
        # resumes (Day 7)
        build_resume_001, build_resume_002, build_resume_003,
        # indian gov forms
        build_indian_gov_form_001, build_indian_gov_form_002, build_indian_gov_form_003,
        # customer support
        build_customer_support_001, build_customer_support_002, build_customer_support_003,
        # internal chat
        build_internal_chat_001, build_internal_chat_002, build_internal_chat_003,
        # clean control (no PII)
        build_clean_control_001, build_clean_control_002, build_clean_control_003,
    ]

    total_labels = 0
    for builder in builders:
        doc = builder()
        path = out_dir / f"{doc['doc_id']}.json"
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
        total_labels += len(doc["labels"])
        print(f"Wrote {path.name}  ({len(doc['labels'])} labels)")

    print(f"\nDone. {len(builders)} docs, {total_labels} labels total.")
    print(f"Run `python eval\\validate_corpus.py` to verify offsets.")
