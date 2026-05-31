"""Day 6 — Three-node agent: detect + decide + apply.

The `apply` node takes the Treatments produced by `decide` and rewrites the
source document accordingly. After this, the agent's output is a MORPHED
DOCUMENT, not just a list of decisions.

Key implementation gotcha — tail-first replacement:
  If you apply treatments from start-of-document forwards, each variable-
  length replacement shifts every subsequent offset. The second replacement
  lands at the wrong characters; the third even worse.

  Fix: sort by offset_start DESCENDING, apply from the end of the document
  backwards. Tail replacements never invalidate offsets you haven't applied yet.
"""

import hashlib
from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from finding import Finding
from india_regex import scan_aadhaar, scan_pan
from presidio_wrapper import scan_with_presidio
from reconcile import reconcile
from treatment import Treatment, TREATMENT_MATRIX, DEFAULT_TREATMENT


# ─────────────────────────────────────────────────────────────────────────────
# State — one new field: morphed_text (output of apply).
# ─────────────────────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    document_text: str            # input
    recipient_profile: str        # input
    findings: list[Finding]       # populated by detect_node
    treatments: list[Treatment]   # populated by decide_node
    morphed_text: str             # populated by apply_node


# ─────────────────────────────────────────────────────────────────────────────
# Action handlers — one per treatment action.
#
# Each handler takes a Finding and returns the REPLACEMENT string. The
# apply_node does the splicing.
#
# v1 simplifications:
#  - pseudonymize/tokenize use a short SHA-256 hash so the same input
#    always produces the same output (deterministic, no vault needed yet).
#  - generalize is a placeholder — real generalization would use entity-
#    specific logic (DOB → age range, salary → band, etc.).
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
    """Replace with Person_<4 hex>. Same input → same output (deterministic)."""
    h = hashlib.sha256(finding.text.encode()).hexdigest()[:4]
    return f"Person_{h}"


def _tokenize(finding: Finding) -> str:
    """Replace with a vault-style token. v1: deterministic hash (no real vault yet).

    In Phase 5, this becomes a real lookup: store {token → encrypted_original}
    in the vault DB so authorized callers can reverse it.
    """
    h = hashlib.sha256(finding.text.encode()).hexdigest()[:8]
    return f"tok_{h}"


def _generalize(finding: Finding) -> str:
    """Placeholder. v1 just labels the type; real impl needs per-type ranges."""
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
# Nodes — detect and decide are unchanged from Day 5.
# ─────────────────────────────────────────────────────────────────────────────

def detect_node(state: AgentState) -> dict:
    text = state["document_text"]
    all_findings = (
        scan_with_presidio(text)
        + scan_aadhaar(text)
        + scan_pan(text)
    )
    return {"findings": reconcile(all_findings)}


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
    """Rewrite document_text per the treatments. Tail-first replacement.

    Reads:  state["document_text"], state["findings"], state["treatments"]
    Writes: state["morphed_text"]
    """
    text = state["document_text"]
    findings = state["findings"]
    treatments = state["treatments"]

    # Pair each treatment with its corresponding finding (by index).
    pairs = [(findings[t.finding_index], t) for t in treatments]

    # CRITICAL: sort by offset_start DESCENDING. Apply from the end backwards
    # so earlier offsets stay valid as later spans get rewritten.
    pairs.sort(key=lambda p: p[0].start, reverse=True)

    morphed = text
    for finding, treatment in pairs:
        handler = ACTION_HANDLERS.get(treatment.action, _redact)  # fail-safe → redact
        replacement = handler(finding)
        # Splice: keep everything before the span, insert replacement, keep everything after.
        morphed = morphed[:finding.start] + replacement + morphed[finding.end:]

    return {"morphed_text": morphed}


# ─────────────────────────────────────────────────────────────────────────────
# Graph — three nodes, linear flow.
# ─────────────────────────────────────────────────────────────────────────────

def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("detect", detect_node)
    graph.add_node("decide", decide_node)
    graph.add_node("apply",  apply_node)

    graph.add_edge(START, "detect")
    graph.add_edge("detect", "decide")
    graph.add_edge("decide", "apply")
    graph.add_edge("apply",  END)

    return graph.compile()


# ─────────────────────────────────────────────────────────────────────────────
# Demo — show ORIGINAL + three MORPHED versions side by side.
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

    app = build_graph()

    print("=" * 70)
    print("ORIGINAL")
    print("=" * 70)
    print(sample_text)

    for profile in ("auditor", "vendor", "public"):
        print("=" * 70)
        print(f"MORPHED (recipient: {profile})")
        print("=" * 70)

        final = app.invoke({
            "document_text": sample_text,
            "recipient_profile": profile,
            "findings": [],
            "treatments": [],
            "morphed_text": "",
        })

        print(final["morphed_text"])
