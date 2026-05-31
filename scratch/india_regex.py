"""Day 2 — India-specific PII detection (Aadhaar + PAN).

Catches what spaCy + Presidio defaults miss:
  - Aadhaar: 12-digit national ID. Regex finds candidates; Verhoeff checksum
    confirms structural validity (filters ~90% of random 12-digit false positives).
  - PAN: 10-character income-tax ID. Regex enforces format; position-4 check
    confirms the entity-type code is one of the 10 recognized values.

Both scanners return findings in a shared shape so a future reconciler can
treat them uniformly.
"""

import re

from finding import Finding

# ─────────────────────────────────────────────────────────────────────────────
# Verhoeff algorithm — standard implementation, treat as a black box.
# Used by Aadhaar (UIDAI) for check-digit validation. Detects all single-digit
# errors and adjacent-digit swaps — exactly the human-typing errors that matter
# for ID numbers.
# ─────────────────────────────────────────────────────────────────────────────

_VERHOEFF_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]

_VERHOEFF_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def verhoeff_valid(digits: str) -> bool:
    """Return True if `digits` has a valid Verhoeff checksum.

    Strips non-digit chars first, so spaces/dashes are tolerated.
    """
    digits = "".join(c for c in digits if c.isdigit())
    if not digits:
        return False
    c = 0
    for i, d in enumerate(reversed(digits)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(d)]]
    return c == 0


def synthetic_valid_aadhaar(prefix_11: str = "00001234567") -> str:
    """Brute-force the last digit so the full 12-digit string has a valid Verhoeff checksum.

    Default prefix starts with 0000 — real Aadhaars never start with 0, so anything
    we generate this way is clearly synthetic. Useful for safe test data.
    """
    for last in range(10):
        candidate = prefix_11 + str(last)
        if verhoeff_valid(candidate):
            return candidate
    raise RuntimeError("no valid checksum for prefix — should be impossible")


# ─────────────────────────────────────────────────────────────────────────────
# Aadhaar — 12 digits, optionally grouped 4-4-4 with spaces or dashes.
# \b boundaries prevent matching inside longer digit sequences.
# ─────────────────────────────────────────────────────────────────────────────

AADHAAR_RE = re.compile(r"\b(\d{4}[\s-]?\d{4}[\s-]?\d{4})\b")


def scan_aadhaar(text: str) -> list[Finding]:
    """Find Aadhaar candidates in `text` and validate each with Verhoeff.

    Returns one Finding per candidate. Verhoeff-valid candidates get confidence
    1.0; shape-matched-but-checksum-failed candidates get 0.5. We keep both —
    over-flagging is safer than under-flagging for PII detection. Downstream
    (reconciler, treatment) can decide what to do with low-confidence findings.
    """
    findings: list[Finding] = []
    for m in AADHAAR_RE.finditer(text):
        raw = m.group(1)
        digits_only = re.sub(r"[\s-]", "", raw)
        validated = verhoeff_valid(digits_only)
        findings.append(Finding(
            text=raw,
            start=m.start(),
            end=m.end(),
            entity_type="AADHAAR",
            detector="regex_india",
            confidence=1.0 if validated else 0.5,
            validated=validated,
        ))
    return findings


# ─────────────────────────────────────────────────────────────────────────────
# PAN (Permanent Account Number) — 10 chars: [A-Z]{5}[0-9]{4}[A-Z]
# Position 4 encodes entity type (P=Individual, C=Company, F=Firm, ...).
# No checksum — only format + position-4 semantic check.
# ─────────────────────────────────────────────────────────────────────────────

# Recognized position-4 entity-type codes. Frozenset for O(1) membership and
# immutability (safe to share across modules without copy).
PAN_ENTITY_TYPES: frozenset[str] = frozenset(
    {"P", "C", "F", "H", "A", "T", "B", "L", "J", "G"}
)

# Case-sensitive: formal PANs are always uppercase. \b prevents matching
# inside longer alphanumeric tokens.
PAN_RE = re.compile(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b")


def pan_format_valid(candidate: str) -> bool:
    """Return True if `candidate`'s 4th character is in PAN_ENTITY_TYPES.

    The regex already enforces the rest of the format (letters/digits, length).
    This function only adds the position-4 *semantic* check: is the entity-type
    code one of the 10 recognized values?

    Edge case: do NOT crash on strings shorter than 4 chars — return False instead.
    (Defensive coding: a caller might pass a malformed string by mistake.)
    """
    if len(candidate) < 4:
        return False
    return candidate[3] in PAN_ENTITY_TYPES


def scan_pan(text: str) -> list[Finding]:
    """Find PAN candidates in `text` and validate the position-4 entity-type code.

    Returns one Finding per candidate. Format-valid candidates get confidence
    1.0; candidates with an unrecognized position-4 code get 0.4 — lower than
    Aadhaar's 'invalid' tier because PAN's format is tighter, so a position-4
    failure is more clearly suspicious.
    """
    findings: list[Finding] = []
    for m in PAN_RE.finditer(text):
        raw = m.group(1)
        validated = pan_format_valid(raw)
        findings.append(Finding(
            text=raw,
            start=m.start(),
            end=m.end(),
            entity_type="PAN",
            detector="regex_india",
            confidence=1.0 if validated else 0.4,
            validated=validated,
        ))
    return findings


# ─────────────────────────────────────────────────────────────────────────────
# Demo — run this file directly to see it work.
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    valid_a = synthetic_valid_aadhaar()
    print(f"Generated valid synthetic Aadhaar: {valid_a}\n")

    sample_text = f"""
Customer record:
  Name: Aarav Verhoeff
  Aadhaar (clean): {valid_a}
  Aadhaar (spaced): {valid_a[:4]} {valid_a[4:8]} {valid_a[8:]}
  Aadhaar (dashed): {valid_a[:4]}-{valid_a[4:8]}-{valid_a[8:]}
  Random 12-digit (should be INVALID): 987654321012
  Phone: +1-202-555-0123
  Order #98765432101 (only 11 digits, should NOT match at all)
  PAN (Individual): ABCPK1234L
  PAN (Company): XYZCY9876Z
  PAN (invalid 4th char): ABCXK1234L
  PAN (wrong length): ABCPK1234
  PAN (lowercase): abcpk1234l
"""

    results = scan_aadhaar(sample_text)
    print(f"Found {len(results)} Aadhaar-shaped candidates:\n")
    for r in results:
        status = "VALID  " if r.validated else "INVALID"
        print(f"  {status}  '{r.text:<18}'  offsets=({r.start:4d}, {r.end:4d})  conf={r.confidence}")

    pan_results = scan_pan(sample_text)
    print(f"\nFound {len(pan_results)} PAN-shaped candidates:\n")
    for r in pan_results:
        status = "VALID  " if r.validated else "INVALID"
        print(f"  {status}  '{r.text:<18}'  offsets=({r.start:4d}, {r.end:4d})  conf={r.confidence}")
