"""Day 4 — First LangGraph agent: a single-node graph.

The whole point of today: see ONE node run end-to-end inside a StateGraph.
The node wraps the deterministic plumbing you already built (Presidio +
India regex + reconciler). The agent doesn't replace that work — it
*orchestrates* it.

A 'node' is just a function. State flows in, partial state flows out,
LangGraph merges it back. That's the entire mental model for today.
"""

from typing import TypedDict
from langgraph.graph import StateGraph, START, END

from finding import Finding
from india_regex import scan_aadhaar, scan_pan
from presidio_wrapper import scan_with_presidio
from reconcile import reconcile


# ─────────────────────────────────────────────────────────────────────────────
# State — the typed dict that flows through the graph.
#
# Every node reads fields out of this dict, optionally returns a partial dict
# of updates, and LangGraph merges the update back into the state automatically.
#
# For today's single-node graph the state is small. Day 5+ adds more fields
# as we add nodes for reconcile, decide, apply.
# ─────────────────────────────────────────────────────────────────────────────

class GuardrailState(TypedDict):
    document_text: str         # input — set when we invoke the graph
    findings: list[Finding]    # output — populated by the detect node


# ─────────────────────────────────────────────────────────────────────────────
# Node — `detect`.
#
# A node is just a Python function with the signature:
#     def node_name(state: SomeState) -> dict
#
# It reads from `state`, does its work, and returns a dict of field names →
# new values. LangGraph applies those updates to the state before running
# the next node.
#
# IMPORTANT: never mutate the input `state` directly. Always return a new
# dict of updates. (You can't actually mutate it for typed dicts at runtime,
# but the discipline matters for when you switch to Pydantic state later.)
# ─────────────────────────────────────────────────────────────────────────────

def detect_node(state: GuardrailState) -> dict:
    """Run all three detectors, merge, deduplicate, and return findings."""
    text = state["document_text"]

    # Concatenate findings from all three sources. Each detector returns
    # list[Finding], so + is just list concatenation.
    all_findings = (
        scan_with_presidio(text)
        + scan_aadhaar(text)
        + scan_pan(text)
    )

    # Deduplicate with the reconciler from Day 3.
    deduped = reconcile(all_findings)

    # Return a partial state update. LangGraph will merge this into the
    # running state — equivalent to state["findings"] = deduped, but without
    # the side effect.
    return {"findings": deduped}


# ─────────────────────────────────────────────────────────────────────────────
# Graph construction.
#
# Three steps:
#   1. Create the StateGraph with the state type.
#   2. Add nodes by name.
#   3. Connect nodes with edges (including START → first_node and last_node → END).
#
# Then .compile() turns the declarative graph into a runnable object.
# ─────────────────────────────────────────────────────────────────────────────

def build_graph():
    graph = StateGraph(GuardrailState)

    graph.add_node("detect", detect_node)

    graph.add_edge(START, "detect")
    graph.add_edge("detect", END)

    return graph.compile()


# ─────────────────────────────────────────────────────────────────────────────
# Demo
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

    print("Building and compiling the graph...\n")
    app = build_graph()

    # Invocation: pass the initial state, get the final state back.
    # `findings` starts empty; `detect_node` will populate it.
    initial_state: GuardrailState = {
        "document_text": sample_text,
        "findings": [],
    }

    print("Invoking the graph (first call loads spaCy — takes ~5s)...\n")
    final_state = app.invoke(initial_state)

    print(f"Final state has {len(final_state['findings'])} findings:\n")
    for f in sorted(final_state["findings"], key=lambda f: f.start):
        print(f"  {f.entity_type:<15}  '{f.text:<32}'  conf={f.confidence:.2f}  "
              f"offsets=({f.start:4d}, {f.end:4d})  detector={f.detector}")
