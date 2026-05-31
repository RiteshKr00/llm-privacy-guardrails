"""Day 3.4 — Reconciler: merge overlapping findings from multiple detectors.

Three detectors (Presidio, Aadhaar regex, PAN regex) produce Findings that may
overlap. The reconciler picks the "best" finding per overlapping cluster, using
confidence to break ties.

V1 rule: when findings overlap, the highest-confidence one wins; the others
are discarded. Future versions could merge agreeing findings into a single
boosted-confidence finding, but for now we keep it simple.
"""

from finding import Finding
from india_regex import scan_aadhaar, scan_pan
from presidio_wrapper import scan_with_presidio


def _overlaps(a: Finding, b: Finding) -> bool:
    """Return True if `a` and `b` share at least one character position.

    Standard interval-overlap formula: two ranges overlap iff
        a.start < b.end  AND  b.start < a.end
    (using exclusive ends, Python-slice style).
    """
    return a.start < b.end and b.start < a.end


def reconcile(findings: list[Finding]) -> list[Finding]:
    """Deduplicate overlapping findings, keeping the highest-confidence one per cluster.

    Algorithm:
      1. Sort findings by (start position ASC, confidence DESC).
         Ties on start go to highest confidence first.
      2. For each finding `f`:
         a. Collect all already-kept findings that overlap with `f`.
         b. If none → keep `f`.
         c. If `f.confidence` is strictly higher than every overlapping finding
            → remove the overlapping ones from `keep`, then append `f`.
         d. Otherwise → drop `f` (a better finding already covers this span).
      3. Return the `keep` list.
    """
    keep: list[Finding] = []

    # Sort by start ASC, then confidence DESC. The DESC on confidence means
    # that when two findings tie on start, the higher-confidence one is
    # processed FIRST — so it lands in `keep` before its weaker neighbor
    # tries to compete with it.
    for f in sorted(findings, key=lambda f: (f.start, -f.confidence)):

        # Which currently-kept findings does `f` overlap with?
        overlapping = [k for k in keep if _overlaps(f, k)]

        if not overlapping:
            # No conflicts → keep `f` unconditionally.
            keep.append(f)
            continue

        if all(f.confidence > k.confidence for k in overlapping):
            # `f` is strictly better than EVERY conflicting finding.
            # Kick out the losers, then keep `f`.
            for k in overlapping:
                keep.remove(k)
            keep.append(f)
        # else: drop `f` silently — at least one overlapping finding is
        # equal or better, so we already have something covering this span.

    return keep


# ─────────────────────────────────────────────────────────────────────────────
# Demo — run all three detectors, then reconcile, and compare before/after.
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

    # Run all three detectors and concatenate
    print("Running all three detectors...\n")
    all_findings = (
        scan_with_presidio(sample_text)
        + scan_aadhaar(sample_text)
        + scan_pan(sample_text)
    )

    print(f"=== BEFORE reconciliation: {len(all_findings)} findings ===\n")
    for f in sorted(all_findings, key=lambda f: f.start):
        print(f"  {f.entity_type:<15}  '{f.text:<32}'  conf={f.confidence:.2f}  "
              f"offsets=({f.start:4d}, {f.end:4d})  detector={f.detector}")

    # Reconcile
    deduped = reconcile(all_findings)

    print(f"\n=== AFTER reconciliation: {len(deduped)} findings ===\n")
    for f in sorted(deduped, key=lambda f: f.start):
        print(f"  {f.entity_type:<15}  '{f.text:<32}'  conf={f.confidence:.2f}  "
              f"offsets=({f.start:4d}, {f.end:4d})  detector={f.detector}")
