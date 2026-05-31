"""LLM Privacy Guardrails — agentic privacy layer for LLM pipelines.

Public API:

    from llm_privacy_guardrails import build_graph, AgentState
    from llm_privacy_guardrails import Finding, Treatment, TREATMENT_MATRIX

    app = build_graph()
    result = app.invoke({
        "document_text": "Name: Aarav Verhoeff\\nEmail: aarav@example.com",
        "recipient_profile": "vendor",
        "findings": [], "treatments": [], "morphed_text": "", "llm_called": False,
    })
    print(result["morphed_text"])
"""

from .agent import AgentState, build_graph
from .finding import Finding
from .treatment import Treatment, TREATMENT_MATRIX, DEFAULT_TREATMENT

__all__ = [
    "AgentState",
    "build_graph",
    "Finding",
    "Treatment",
    "TREATMENT_MATRIX",
    "DEFAULT_TREATMENT",
]

__version__ = "0.1.0"
