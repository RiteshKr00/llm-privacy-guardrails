"""The privacy-guardrails agent — full LangGraph pipeline.

Three nodes, linear flow:

    detect → decide → apply

  detect_node: runs Presidio + India regex + (cost-routed) LLM extractor,
               reconciles overlaps, filters to matrix-relevant entity types.
  decide_node: looks up TREATMENT_MATRIX[entity_type][recipient_profile]
               per finding, produces Treatment records.
  apply_node:  rewrites document_text per the treatments using tail-first
               replacement to preserve offsets.

State grows monotonically — each node writes a different slice. Build the
runnable graph with `build_graph()`, invoke with an `AgentState` dict.
"""

import hashlib
from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from .detectors.india_regex import scan_aadhaar, scan_pan
from .detectors.llm import scan_with_llm
from .detectors.presidio import scan_with_presidio
from .finding import Finding
from .reconcile import reconcile
from .routing import should_call_llm
from .treatment import Treatment, TREATMENT_MATRIX, DEFAULT_TREATMENT


# ─────────────────────────────────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    """The typed state that flows through the graph."""
    document_text: str           # input
    recipient_profile: str       # input — "auditor" | "vendor" | "public"
    findings: list[Finding]      # populated by detect
    treatments: list[Treatment]  # populated by decide
    morphed_text: str            # populated by apply
    llm_called: bool             # populated by detect — was the LLM consulted?


# ─────────────────────────────────────────────────────────────────────────────
# Action handlers — one per treatment action. Each takes a Finding and
# returns the REPLACEMENT string. apply_node does the actual splicing.
# ─────────────────────────────────────────────────────────────────────────────

def _keep(finding: Finding) -> str:
    return finding.text


def _redact(finding: Finding) -> str:
    return "[REDACTED]"


def _mask(finding: Finding) -> str:
    """Show last 4 chars, mask the rest with asterisks."""
    raw = finding.text
    if len(raw) <= 4:
        return "*" * len(raw)
    return "*" * (len(raw) - 4) + raw[-4:]


def _pseudonymize(finding: Finding) -> str:
    """Replace with Person_<4 hex>. Same input → same output (deterministic).

    Deterministic pseudonyms preserve co-occurrence patterns for analytics
    while removing identity. The downside: vulnerable to frequency-analysis
    attacks combined with external data. This is pseudonymization, not
    anonymization — see NOTES.md.
    """
    h = hashlib.sha256(finding.text.encode()).hexdigest()[:4]
    return f"Person_{h}"


def _tokenize(finding: Finding) -> str:
    """Replace with a vault-style token. v1: deterministic hash; real impl
    would store {token → encrypted_original} in a vault DB for authorized
    reverse-lookups."""
    h = hashlib.sha256(finding.text.encode()).hexdigest()[:8]
    return f"tok_{h}"


def _generalize(finding: Finding) -> str:
    """Placeholder. Real impl needs per-type ranges (DOB → age decade,
    salary → band, etc.)."""
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
    """Cost-routed detection: cheap detectors first, then LLM if needed.
    Filters output to matrix-relevant entity types only."""
    text = state["document_text"]

    cheap = scan_with_presidio(text) + scan_aadhaar(text) + scan_pan(text)

    if should_call_llm(text, cheap):
        all_findings = cheap + scan_with_llm(text)
        llm_called = True
    else:
        all_findings = cheap
        llm_called = False

    findings = reconcile(all_findings)

    # Filter to matrix-relevant types only. Anything Presidio reports outside
    # the matrix (DATE_TIME, ORG, URL etc.) would otherwise fall through to
    # DEFAULT_TREATMENT and surprise-redact non-PII text.
    findings = [f for f in findings if f.entity_type in TREATMENT_MATRIX]

    return {"findings": findings, "llm_called": llm_called}


def decide_node(state: AgentState) -> dict:
    """Per finding, look up the matrix and produce a Treatment record."""
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
    """Rewrite document_text per the treatments. Tail-first replacement
    preserves offsets across variable-length substitutions."""
    text = state["document_text"]
    findings = state["findings"]
    treatments = state["treatments"]

    pairs = [(findings[t.finding_index], t) for t in treatments]
    pairs.sort(key=lambda p: p[0].start, reverse=True)  # tail-first

    morphed = text
    for finding, treatment in pairs:
        handler = ACTION_HANDLERS.get(treatment.action, _redact)  # fail-safe
        morphed = morphed[:finding.start] + handler(finding) + morphed[finding.end:]

    return {"morphed_text": morphed}


# ─────────────────────────────────────────────────────────────────────────────
# Graph construction
# ─────────────────────────────────────────────────────────────────────────────

def build_graph():
    """Return the compiled three-node StateGraph."""
    graph = StateGraph(AgentState)

    graph.add_node("detect", detect_node)
    graph.add_node("decide", decide_node)
    graph.add_node("apply",  apply_node)

    graph.add_edge(START,    "detect")
    graph.add_edge("detect", "decide")
    graph.add_edge("decide", "apply")
    graph.add_edge("apply",  END)

    return graph.compile()
