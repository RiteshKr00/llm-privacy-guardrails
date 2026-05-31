"""Day 5 — Two-node agent: detect + decide.

Adds the `decide` node. For each Finding produced by `detect`, the decide
node looks up the treatment in the matrix using:
    (Finding.entity_type, state.recipient_profile) → action

V1 is a pure matrix lookup — no LLM, no RAG. Phase 4 will add a
policy_lookup tool that can override the matrix (toward stricter only).

This is the first time state GROWS across multiple nodes:
  - detect writes `findings`
  - decide reads `findings` AND `recipient_profile`, writes `treatments`
"""

from typing import TypedDict
from langgraph.graph import StateGraph, START, END

from finding import Finding
from india_regex import scan_aadhaar, scan_pan
from presidio_wrapper import scan_with_presidio
from reconcile import reconcile
from treatment import Treatment, TREATMENT_MATRIX, DEFAULT_TREATMENT


# ─────────────────────────────────────────────────────────────────────────────
# State — now with two more fields than Day 4.
# ─────────────────────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    document_text: str            # input
    recipient_profile: str        # input — "auditor" | "vendor" | "public"
    findings: list[Finding]       # populated by detect_node
    treatments: list[Treatment]   # populated by decide_node


# ─────────────────────────────────────────────────────────────────────────────
# Nodes
# ─────────────────────────────────────────────────────────────────────────────

def detect_node(state: AgentState) -> dict:
    """Same as Day 4 — run all detectors, reconcile, return findings."""
    text = state["document_text"]
    all_findings = (
        scan_with_presidio(text)
        + scan_aadhaar(text)
        + scan_pan(text)
    )
    return {"findings": reconcile(all_findings)}


def decide_node(state: AgentState) -> dict:
    """For each finding, look up the matrix and produce a Treatment.

    Reads:  state["findings"], state["recipient_profile"]
    Writes: state["treatments"]

    Note this node makes NO LLM call. It's a deterministic lookup. The
    'decision' is encoded in the matrix; this function just applies it.
    """
    findings = state["findings"]
    profile = state["recipient_profile"]

    treatments: list[Treatment] = []
    for i, f in enumerate(findings):
        # Matrix lookup with two layers of fallback:
        #   1. Unknown entity_type → fall through to DEFAULT_TREATMENT
        #   2. Known entity_type but unknown profile → also DEFAULT_TREATMENT
        row = TREATMENT_MATRIX.get(f.entity_type, {})
        action = row.get(profile, DEFAULT_TREATMENT)

        treatments.append(Treatment(
            finding_index=i,
            action=action,
            reason=f"matrix[{f.entity_type}][{profile}] = {action}",
        ))

    return {"treatments": treatments}


# ─────────────────────────────────────────────────────────────────────────────
# Graph — two nodes, linear flow.
#
# detect → decide
#
# The edge from detect to decide is what makes state flow: detect's output
# update lands in state, then decide reads from the updated state.
# ─────────────────────────────────────────────────────────────────────────────

def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("detect", detect_node)
    graph.add_node("decide", decide_node)

    graph.add_edge(START, "detect")
    graph.add_edge("detect", "decide")
    graph.add_edge("decide", END)

    return graph.compile()


# ─────────────────────────────────────────────────────────────────────────────
# Demo — run the same document through all THREE profiles to see the matrix.
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

    # Run the SAME document through all three profiles to show the matrix
    # in action. Detection results are identical across runs; only the
    # treatments differ.
    for profile in ("auditor", "vendor", "public"):
        print(f"\n{'='*70}")
        print(f"RECIPIENT PROFILE: {profile}")
        print('='*70)

        final = app.invoke({
            "document_text": sample_text,
            "recipient_profile": profile,
            "findings": [],
            "treatments": [],
        })

        # Print per-finding treatments. Sort by start offset for readability.
        sorted_findings = sorted(
            enumerate(final["findings"]), key=lambda pair: pair[1].start
        )
        for idx, f in sorted_findings:
            # Find the treatment with matching finding_index
            t = next(t for t in final["treatments"] if t.finding_index == idx)
            print(f"  {f.entity_type:<15}  '{f.text[:30]:<30}'  →  {t.action:<14}  ({t.reason})")
