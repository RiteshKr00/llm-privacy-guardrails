"""Day 11 — LLM extractor: fourth detector emitting Finding objects.

The LLM is asked for `text + entity_type` only — NOT offsets. Character
counting is famously hard for LLMs; we sidestep it by re-finding each
returned substring in the source via str.find(). If find() returns -1,
the LLM hallucinated a substring that isn't in the source — we drop it.

This also handles repeated occurrences correctly: if the LLM says
'Aarav' is a PERSON and 'Aarav' appears 3 times in the source, we
emit 3 separate Finding objects (one per occurrence).

Confidence is 0.8 for LLM findings — high enough to compete with Presidio
NER (0.85) but not so high that LLM hallucinations would dominate the
reconciler in a tie. Tune later based on eval results.
"""

from pydantic import BaseModel, Field

from finding import Finding
from llm_factory import get_llm


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic schema for the LLM's response
# ─────────────────────────────────────────────────────────────────────────────

# The set of entity types the LLM is allowed to emit. Must match what
# treatment.py's TREATMENT_MATRIX recognizes — otherwise the decide step
# falls through to DEFAULT_TREATMENT (redact) which is fine but noisy.
RECOGNIZED_TYPES = {
    "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "LOCATION",
    "AADHAAR", "PAN", "CREDIT_CARD",
}


class LLMFinding(BaseModel):
    """One PII span from the LLM. No offsets — we re-find them ourselves."""
    text: str = Field(description="The exact substring as it appears in the source text.")
    entity_type: str = Field(
        description=(
            "One of: PERSON, EMAIL_ADDRESS, PHONE_NUMBER, LOCATION, "
            "AADHAAR, PAN, CREDIT_CARD"
        )
    )


class LLMFindings(BaseModel):
    """Wrapper because most LLMs handle structured output better with a
    named outer object than with a bare list."""
    findings: list[LLMFinding]


# ─────────────────────────────────────────────────────────────────────────────
# The prompt
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a PII (personally identifiable information) extraction tool.

Identify every PII span in the user's text. For each one, return:
  - text: the EXACT substring as it appears in the source (do not paraphrase or correct spelling)
  - entity_type: one of PERSON, EMAIL_ADDRESS, PHONE_NUMBER, LOCATION, AADHAAR, PAN, CREDIT_CARD

Rules:
  - PERSON includes full names, first names, last names — any human name.
  - LOCATION includes cities, states, countries, full or partial addresses.
  - AADHAAR is a 12-digit Indian national ID, possibly with spaces or dashes.
  - PAN is a 10-character Indian tax ID like ABCPK1234L (5 letters, 4 digits, 1 letter).
  - Return the substring EXACTLY as written. If the source says "+1-202-555-0123", return that with the plus, dashes, etc.
  - Do not invent spans that are not literally present in the text.
  - One finding per distinct span (even if the same name appears multiple times — list it once and we'll find all occurrences ourselves).
  - If you are not sure something is PII, skip it. False positives hurt more than false negatives at this layer."""


# ─────────────────────────────────────────────────────────────────────────────
# Main extractor function
# ─────────────────────────────────────────────────────────────────────────────

def scan_with_llm(text: str) -> list[Finding]:
    """Call the LLM, parse structured output, verify each finding by substring
    match in the source, and emit Finding objects.

    Returns an empty list if the LLM returns malformed output that even
    `.with_structured_output()`'s retries can't recover from. We log to
    stdout in that case for debugging — production would route to proper
    logging.
    """
    llm = get_llm()
    structured = llm.with_structured_output(LLMFindings)

    try:
        result: LLMFindings = structured.invoke(
            f"{_SYSTEM_PROMPT}\n\nTEXT:\n{text}"
        )
    except Exception as e:
        print(f"  [llm_extractor] structured output failed: {e}")
        return []

    findings: list[Finding] = []
    for lf in result.findings:
        # Drop unknown entity types — the matrix wouldn't know what to do with them.
        if lf.entity_type not in RECOGNIZED_TYPES:
            continue

        # Find ALL occurrences of this span in the source text.
        # Drop hallucinations (substring not present).
        cursor = 0
        while True:
            idx = text.find(lf.text, cursor)
            if idx < 0:
                break
            findings.append(Finding(
                text=lf.text,
                start=idx,
                end=idx + len(lf.text),
                entity_type=lf.entity_type,
                detector="llm",
                confidence=0.8,
                validated=True,  # substring match IS our validation
            ))
            cursor = idx + 1  # advance past this occurrence to find the next

    return findings


# ─────────────────────────────────────────────────────────────────────────────
# Demo — run on one corpus doc to see what the 3b model produces
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sample_text = """
Customer record:
  Name: Aarav Verhoeff
  Email: aarav.verhoeff@example.com
  Phone: +1-202-555-0123
  Aadhaar: 0000 1234 5676
  PAN (Individual): ABCPK1234L
  Address: 42 Fictional Maple Street, Springfield
  Credit card: 4111-1111-1111-1111
"""

    print("Calling LLM extractor (first call may take 10-30 seconds)...\n")
    findings = scan_with_llm(sample_text)

    print(f"LLM returned {len(findings)} findings (after offset verification):\n")
    for f in sorted(findings, key=lambda f: f.start):
        print(f"  {f.entity_type:<15}  '{f.text:<32}'  offsets=({f.start:4d}, {f.end:4d})")
