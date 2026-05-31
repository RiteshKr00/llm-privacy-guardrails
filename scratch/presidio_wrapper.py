"""Day 3.3 — Presidio adapter.

Wraps Presidio's AnalyzerEngine so it emits Finding objects instead of
RecognizerResult objects. After this, all three detectors (Presidio, Aadhaar
regex, PAN regex) speak the same shape — which is exactly what the reconciler
needs.

Note on performance: AnalyzerEngine() loads the spaCy model (~500MB), which
takes a few seconds on first call. We cache it at module level via lru_cache
so subsequent calls are fast.
"""

from functools import lru_cache

from presidio_analyzer import AnalyzerEngine

from finding import Finding


@lru_cache(maxsize=1)
def _get_analyzer() -> AnalyzerEngine:
    """Lazy singleton — built on first call, reused after."""
    return AnalyzerEngine()


def scan_with_presidio(text: str) -> list[Finding]:
    """Run Presidio over `text` and return a list of Finding objects.

    Mapping from Presidio's RecognizerResult fields to Finding fields:
      RecognizerResult.entity_type  → Finding.entity_type
      RecognizerResult.start        → Finding.start
      RecognizerResult.end          → Finding.end
      RecognizerResult.score        → Finding.confidence
      text[start:end]               → Finding.text (slice the source)
      "presidio" (literal)          → Finding.detector
      True (literal)                → Finding.validated   ← Presidio has no
                                                            second-stage validator,
                                                            so we mark its findings
                                                            as 'already validated.'
    """
    analyzer = _get_analyzer()
    results = analyzer.analyze(text=text, language="en")

    findings: list[Finding] = []
    for r in results:
        findings.append(Finding(
            text=text[r.start:r.end],
            start=r.start,
            end=r.end,
            entity_type=r.entity_type,
            detector="presidio",
            confidence=r.score,
            validated=True,  # Presidio has no second-stage validator
        ))

    return findings


# ─────────────────────────────────────────────────────────────────────────────
# Demo — run this file directly to see it work.
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sample_text = """
Customer record:
  Name: Aarav Verhoeff
  Email: aarav.verhoeff@example.com
  Phone: +1-202-555-0123
  Address: 42 Fictional Maple Street, Springfield
  Credit card: 4111-1111-1111-1111
"""

    print("Loading Presidio (first call loads spaCy — takes ~5s)...\n")
    findings = scan_with_presidio(sample_text)

    print(f"Found {len(findings)} findings:\n")
    for f in findings:
        print(f"  {f.entity_type:<15}  '{f.text:<32}'  conf={f.confidence:.2f}  "
              f"offsets=({f.start:4d}, {f.end:4d})  detector={f.detector}")
