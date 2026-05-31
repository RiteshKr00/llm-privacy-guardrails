"""Cost-routing — decides whether to escalate to the LLM extractor.

v1 rule, conservative by design:
  Skip the LLM only if (a) cheap detectors found no matrix-relevant PII
  AND (b) the text has no PII-syntax markers. Err toward calling the LLM
  because a privacy guardrail's worst failure mode is a missed leak.

For paid LLMs (Gemini / OpenAI), this routing is real cost control.
For local Ollama (free), it's hygiene.
"""

from .finding import Finding
from .treatment import TREATMENT_MATRIX


# Substrings whose presence strongly suggests PII the cheap detectors might
# have missed. If any appear, we call the LLM even when cheap-detectors are
# empty.
PII_SYNTAX_MARKERS: tuple[str, ...] = (
    "@",       # email anywhere
    "+1-",     # US-style phone prefix
    "Aadhaar", # explicit mention
    "PAN",     # explicit mention
    "Name:",   # form-style key
    "Email:",
    "Phone:",
    "Card:",
)


def should_call_llm(text: str, cheap_findings: list[Finding]) -> bool:
    """Return True if the LLM extractor should be called for this doc.

    Filters cheap findings to MATRIX-RELEVANT entity types first. Presidio
    fires on URL / DATE_TIME / ORG which we don't have policies for —
    finding them doesn't tell us whether matrix-relevant PII is present.
    """
    matrix_relevant = [f for f in cheap_findings if f.entity_type in TREATMENT_MATRIX]
    if matrix_relevant:
        return True
    if any(marker in text for marker in PII_SYNTAX_MARKERS):
        return True
    return False
