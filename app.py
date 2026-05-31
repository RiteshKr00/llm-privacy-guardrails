"""Streamlit UI for LLM Privacy Guardrails.

Run with:
    streamlit run app.py

Then open http://localhost:8501 in a browser.

The page lets a user paste/upload a document, pick a recipient profile, and
see the agent's morphed output side-by-side with the original — plus the
per-finding treatments table.
"""

import json
from pathlib import Path

import streamlit as st

from llm_privacy_guardrails import build_graph


# ─────────────────────────────────────────────────────────────────────────────
# Load the labeled corpus once — used by the "Pick from corpus" mode.
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data
def load_corpus() -> dict[str, dict]:
    """Return {doc_id → doc dict} for every JSON in eval/corpus/.
    Returns {} if the corpus directory doesn't exist (e.g., running from a
    location without the eval folder)."""
    corpus_dir = Path(__file__).parent / "eval" / "corpus"
    if not corpus_dir.is_dir():
        return {}
    docs = {}
    for path in sorted(corpus_dir.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        docs[doc["doc_id"]] = doc
    return docs


# ─────────────────────────────────────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="LLM Privacy Guardrails",
    page_icon=":lock:",
    layout="wide",
)

# Cache the compiled LangGraph across Streamlit reruns. Without this, every
# slider drag would rebuild the graph and reload spaCy. With it, the first
# page load takes a few seconds; everything after is instant.
@st.cache_resource(show_spinner="Building the agent (one-time, ~5s)...")
def get_app():
    return build_graph()


# ─────────────────────────────────────────────────────────────────────────────
# Sample text — for the "Try a sample" path
# ─────────────────────────────────────────────────────────────────────────────

SAMPLE_TEXT = """Customer record:
  Name: Aarav Verhoeff
  Email: aarav.verhoeff@example.com
  Phone: +1-202-555-0123
  Aadhaar: 0000 1234 5676
  PAN (Individual): ABCPK1234L
  Address: 42 Fictional Maple Street, Springfield
  Credit card: 4111-1111-1111-1111
"""


# ─────────────────────────────────────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────────────────────────────────────

st.title("LLM Privacy Guardrails")
st.caption(
    "An agentic privacy layer for LLM pipelines. Detects PII "
    "(including Aadhaar / PAN), reasons about per-recipient treatment, "
    "and produces a morphed document with an audit trail."
)

# Input picker
mode = st.radio(
    "Input source",
    ["Try a sample", "Pick from corpus", "Paste text", "Upload file"],
    horizontal=True,
)

text = ""
selected_corpus_doc: dict | None = None  # set when mode == "Pick from corpus"

if mode == "Try a sample":
    text = SAMPLE_TEXT
    st.text_area("Sample text (read-only)", value=text, height=220, disabled=True)

elif mode == "Pick from corpus":
    corpus = load_corpus()
    if not corpus:
        st.warning(
            "No labeled corpus found at `eval/corpus/`. Run "
            "`python eval/build_corpus.py` from the repo root first."
        )
    else:
        # Show by genre + doc_id for usability
        labels_by_id = {
            doc_id: f"{doc['genre']:<18}  {doc_id}   ({len(doc['labels'])} labels)"
            for doc_id, doc in corpus.items()
        }
        choice = st.selectbox(
            "Pick a labeled document",
            options=list(corpus.keys()),
            format_func=labels_by_id.get,
            help="These docs come with ground-truth labels — agent output will be visible to compare against.",
        )
        selected_corpus_doc = corpus[choice]
        text = selected_corpus_doc["text"]
        st.text_area("Corpus text (read-only)", value=text, height=220, disabled=True)
        with st.expander(f"Ground-truth labels ({len(selected_corpus_doc['labels'])})"):
            label_rows = [
                {
                    "entity_type": label["entity_type"],
                    "span": label["text"],
                    "offsets": f"({label['start']}, {label['end']})",
                    "treatment[auditor]": label["treatments"]["auditor"],
                    "treatment[vendor]": label["treatments"]["vendor"],
                    "treatment[public]": label["treatments"]["public"],
                }
                for label in selected_corpus_doc["labels"]
            ]
            if label_rows:
                st.dataframe(label_rows, use_container_width=True, hide_index=True)
            else:
                st.info("This doc has no labels (clean control).")

elif mode == "Paste text":
    text = st.text_area("Paste document text here", height=220, placeholder="Customer record:\n  Name: ...\n  Email: ...")

elif mode == "Upload file":
    uploaded = st.file_uploader("Upload a .txt or .md file", type=["txt", "md"])
    if uploaded is not None:
        text = uploaded.read().decode("utf-8")
        st.text_area("Uploaded text (read-only)", value=text, height=220, disabled=True)

# Profile + run button on one row
col_profile, col_run, _spacer = st.columns([1, 1, 3])
with col_profile:
    profile = st.selectbox(
        "Recipient profile",
        ["auditor", "vendor", "public"],
        index=1,
        help=(
            "auditor: keeps most things; masks AADHAAR/PAN/CARD last-4.  "
            "vendor: pseudonymizes name, tokenizes email, redacts sensitive IDs.  "
            "public: aggressive redaction; only city-level location kept."
        ),
    )
with col_run:
    st.write("")  # vertical spacer to line up the button with the dropdown
    run_clicked = st.button("Run agent", type="primary", disabled=not text.strip())


# ─────────────────────────────────────────────────────────────────────────────
# Invoke + render results
# ─────────────────────────────────────────────────────────────────────────────

if run_clicked and text.strip():
    with st.spinner("Running detect → decide → apply..."):
        app = get_app()
        try:
            result = app.invoke({
                "document_text": text,
                "recipient_profile": profile,
                "findings": [],
                "treatments": [],
                "morphed_text": "",
                "llm_called": False,
            })
        except Exception as e:
            st.error(f"Agent failed: {e}")
            st.info(
                "If this is an Ollama connection error, make sure `ollama serve` "
                "is running, or set `$env:LLM_PROVIDER = 'gemini'` to use Gemini instead."
            )
            st.stop()

    # Summary metrics row
    m1, m2, m3 = st.columns(3)
    m1.metric("Findings", len(result["findings"]))
    m2.metric("LLM called", "Yes" if result["llm_called"] else "No")
    m3.metric("Profile", profile)

    # Side-by-side original vs morphed
    col_orig, col_morphed = st.columns(2)
    with col_orig:
        st.subheader("Original")
        st.code(text, language=None)
    with col_morphed:
        st.subheader(f"Morphed for {profile}")
        st.code(result["morphed_text"], language=None)

    # Findings + treatments table
    if result["findings"]:
        st.subheader("Findings and treatments")
        rows = []
        treatments_by_idx = {t.finding_index: t for t in result["treatments"]}
        for i, f in enumerate(sorted(result["findings"], key=lambda f: f.start)):
            # Re-locate the matching treatment (the index in `result['findings']`
            # may have shifted after sorting; rebuild by source list).
            # Simpler approach: don't sort; treatments map by original index.
            pass
        # Recompute without sort to keep treatment indices aligned.
        for i, f in enumerate(result["findings"]):
            t = treatments_by_idx.get(i)
            rows.append({
                "entity_type": f.entity_type,
                "span": f.text,
                "offsets": f"({f.start}, {f.end})",
                "detector": f.detector,
                "confidence": f"{f.confidence:.2f}",
                "treatment": t.action if t else "?",
                "reason": t.reason if t else "?",
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("No PII detected in this document.")
