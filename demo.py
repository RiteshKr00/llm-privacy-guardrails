"""Demo — run the privacy-guardrails agent on a sample document.

Shows the recipient-aware morphing: same source → three policy-correct
outputs (auditor / vendor / public). This is the 60-second screen-share
that summarizes the whole project.

Run with the default LLM provider (Ollama):
    python demo.py

Or swap providers via env var:
    $env:LLM_PROVIDER = "gemini"; python demo.py
"""

from llm_privacy_guardrails import build_graph


SAMPLE = """
Customer record:
  Name: Aarav Verhoeff
  Email: aarav.verhoeff@example.com
  Phone: +1-202-555-0123
  Aadhaar: 0000 1234 5676
  PAN (Individual): ABCPK1234L
  Address: 42 Fictional Maple Street, Springfield
  Credit card: 4111-1111-1111-1111
"""


def main():
    app = build_graph()

    print("=" * 70)
    print("ORIGINAL")
    print("=" * 70)
    print(SAMPLE)

    for profile in ("auditor", "vendor", "public"):
        result = app.invoke({
            "document_text": SAMPLE,
            "recipient_profile": profile,
            "findings": [],
            "treatments": [],
            "morphed_text": "",
            "llm_called": False,
        })

        print("=" * 70)
        print(f"MORPHED  (recipient: {profile}   LLM called: {result['llm_called']})")
        print("=" * 70)
        print(result["morphed_text"])


if __name__ == "__main__":
    main()
