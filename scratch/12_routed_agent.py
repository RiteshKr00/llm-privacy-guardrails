"""Day 12 — Cost-routed agent.

Same three-node graph as Day 6 (detect -> decide -> apply), but `detect`
now uses cost-routing to decide whether to call the LLM extractor.

The routing rule (v1 — deliberately conservative):
  Skip the LLM ONLY if:
    1. Cheap detectors found zero findings, AND
    2. The text contains no PII-syntax markers (@, +1-, Aadhaar, PAN, ...)
  Otherwise: always call the LLM.

For a privacy guardrail, skipping a needed LLM call = a real leak. Err
toward "call it." On our 15-doc corpus this skips the 3 clean_control
docs (20% savings) and runs the LLM on everything else.

Cost-routing matters less with local Ollama (free). It matters a lot when
swapping to Gemini / OpenAI via LLM_PROVIDER env var — same code, paid LLM.
"""

import hashlib
from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from finding import Finding
from india_regex import scan_aadhaar, scan_pan
from llm_extractor import scan_with_llm
from presidio_wrapper import scan_with_presidio
from reconcile import reconcile
from treatment import Treatment, TREATMENT_MATRIX, DEFAULT_TREATMENT


# ─────────────────────────────────────────────────────────────────────────────
# State — adds llm_called for cost-transparency.
# ─────────────────────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    document_text: str           # input
    recipient_profile: str       # input
    findings: list[Finding]      # populated by detect
    treatments: list[Treatment]  # populated by decide
    morphed_text: str            # populated by apply
    llm_called: bool             # populated by detect — was the LLM consulted?


# ─────────────────────────────────────────────────────────────────────────────
# Routing rule
# ─────────────────────────────────────────────────────────────────────────────

# Substrings whose presence strongly suggests the doc could contain PII the
# cheap detectors might miss (e.g., Indian-name context, descriptive PII).
# If any of these appear, we call the LLM even when cheap detectors found nothing.
_PII_SYNTAX_MARKERS = (
    "@",       # email anywhere
    "+1-",     # US-style phone prefix
    "Aadhaar", # explicit Aadhaar mention
    "PAN",     # explicit PAN mention
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
        # Cheap detectors found matrix-relevant PII — LLM might catch more
        # (e.g., Indian PERSON entities spaCy missed alongside the email).
        return True
    if any(marker in text for marker in _PII_SYNTAX_MARKERS):
        # Cheap detectors missed everything matrix-relevant, but the doc
        # has form-style markers suggesting PII is present. Call the LLM.
        return True
    # Cheap found nothing matrix-relevant AND no PII-syntax markers
    # → highest-confidence "skip LLM" case.
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Action handlers (same as Day 6)
# ─────────────────────────────────────────────────────────────────────────────

def _keep(finding: Finding) -> str:
    return finding.text

def _redact(finding: Finding) -> str:
    return "[REDACTED]"

def _mask(finding: Finding) -> str:
    raw = finding.text
    if len(raw) <= 4:
        return "*" * len(raw)
    return "*" * (len(raw) - 4) + raw[-4:]

def _pseudonymize(finding: Finding) -> str:
    h = hashlib.sha256(finding.text.encode()).hexdigest()[:4]
    return f"Person_{h}"

def _tokenize(finding: Finding) -> str:
    h = hashlib.sha256(finding.text.encode()).hexdigest()[:8]
    return f"tok_{h}"

def _generalize(finding: Finding) -> str:
    return f"[{finding.entity_type}_GENERALIZED]"


ACTION_HANDLERS = {
    "keep":         _keep,
    "redact":       _redact,
    "mask":         _mask,
    "pseudonymize": _pseudonymize,
    "tokenize":     _tokenize,
    "generalize":   _generalize,
}


# ─────────────────────────────────────────────────────────────────────────────
# Nodes
# ─────────────────────────────────────────────────────────────────────────────

def detect_node(state: AgentState) -> dict:
    """Cost-routed detection: cheap detectors first, then LLM if needed."""
    text = state["document_text"]

    # Phase 1: always run the cheap deterministic detectors.
    cheap = scan_with_presidio(text) + scan_aadhaar(text) + scan_pan(text)

    # Phase 2: decide whether to escalate to the LLM.
    if should_call_llm(text, cheap):
        all_findings = cheap + scan_with_llm(text)
        llm_called = True
    else:
        all_findings = cheap
        llm_called = False

    findings = reconcile(all_findings)

    # Filter to matrix-relevant types only. Presidio fires on entity types
    # our system has no policy for (DATE_TIME, ORG, URL etc.). Letting those
    # through would surprise-redact things like "seven years" via the
    # DEFAULT_TREATMENT fallback in decide_node. Consistency: the agent
    # only acts on types it has explicit policy for.
    findings = [f for f in findings if f.entity_type in TREATMENT_MATRIX]

    return {
        "findings": findings,
        "llm_called": llm_called,
    }


def decide_node(state: AgentState) -> dict:
    findings = state["findings"]
    profile = state["recipient_profile"]

    treatments: list[Treatment] = []
    for i, f in enumerate(findings):
        row = TREATMENT_MATRIX.get(f.entity_type, {})
        action = row.get(profile, DEFAULT_TREATMENT)
        treatments.append(Treatment(
            finding_index=i,
            action=action,
            reason=f"matrix[{f.entity_type}][{profile}] = {action}",
        ))
    return {"treatments": treatments}


def apply_node(state: AgentState) -> dict:
    text = state["document_text"]
    findings = state["findings"]
    treatments = state["treatments"]

    pairs = [(findings[t.finding_index], t) for t in treatments]
    pairs.sort(key=lambda p: p[0].start, reverse=True)  # tail-first

    morphed = text
    for finding, treatment in pairs:
        handler = ACTION_HANDLERS.get(treatment.action, _redact)
        morphed = morphed[:finding.start] + handler(finding) + morphed[finding.end:]

    return {"morphed_text": morphed}


# ─────────────────────────────────────────────────────────────────────────────
# Graph
# ─────────────────────────────────────────────────────────────────────────────

def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("detect", detect_node)
    graph.add_node("decide", decide_node)
    graph.add_node("apply",  apply_node)
    graph.add_edge(START,    "detect")
    graph.add_edge("detect", "decide")
    graph.add_edge("decide", "apply")
    graph.add_edge("apply",  END)
    return graph.compile()


# ─────────────────────────────────────────────────────────────────────────────
# Demo — three documents: one with PII (LLM called), one clean (LLM skipped),
# one minimal-text-no-PII (LLM skipped).
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    docs = {
        "doc_a_with_pii": (
            "Customer record:\n"
            "  Name: Aarav Verhoeff\n"
            "  Email: aarav.verhoeff@example.com\n"
            "  Phone: +1-202-555-0123\n"
            "  Aadhaar: 0000 1234 5676\n"
            "  PAN: ABCPK1234L\n"
        ),
        "doc_b_clean_marketing": (
            "Introducing our latest privacy-first analytics platform. "
            "Designed for engineering teams that need observability without "
            "compromising data sovereignty. Pricing starts at the basic tier."
        ),
        "doc_c_minimal_policy": (
            "Data retention policy: all customer records are kept for seven "
            "years to comply with regulatory obligations, then archived."
        ),
    }

    app = build_graph()

    for doc_id, text in docs.items():
        print("=" * 70)
        print(f"DOC: {doc_id}")
        print("=" * 70)

        final = app.invoke({
            "document_text": text,
            "recipient_profile": "vendor",
            "findings": [],
            "treatments": [],
            "morphed_text": "",
            "llm_called": False,
        })

        print(f"LLM called: {final['llm_called']}")
        print(f"Findings:   {len(final['findings'])}")
        print()
        print("MORPHED:")
        print(final["morphed_text"])
        print()
