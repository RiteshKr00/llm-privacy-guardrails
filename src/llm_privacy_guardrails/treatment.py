"""Treatment dataclass + the recipient-profile-aware treatment matrix.

A 'Treatment' is the decided action for ONE finding under ONE recipient
profile. The matrix is a lookup table: entity_type × profile → action.

The matrix is intentionally hardcoded config for v1. In Phase 4 we'll
add a policy_lookup tool (RAG over DPDP/GDPR) that can *override* the
matrix toward stricter treatment (never looser — safe by default).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Treatment:
    """The action decided for one finding."""
    finding_index: int    # index into the findings list this treatment applies to
    action: str           # "keep" | "mask" | "redact" | "pseudonymize" | "tokenize"
    reason: str           # human-readable justification (for the audit trail)


# ─────────────────────────────────────────────────────────────────────────────
# The treatment matrix.
#
# Rows = entity types (must match what detectors emit as `Finding.entity_type`).
# Columns = recipient profiles. Values = the action to take.
#
# Design choices worth remembering:
#  - LOCATION is "keep" everywhere because we're treating city-level locations
#    as non-identifying for our v1 scope. Refining to mask street-level
#    addresses is future work.
#  - PERSON pseudonymizes for vendor/public to preserve co-occurrence patterns
#    (the vendor can still see "Person_A and Person_B both work at Company_X")
#    without revealing identity.
#  - AADHAAR / PAN / CREDIT_CARD all redact for vendor/public — these are
#    the most-sensitive entities. Auditor gets "mask" (last-4-digits visible
#    for verification) but never full disclosure.
# ─────────────────────────────────────────────────────────────────────────────

TREATMENT_MATRIX: dict[str, dict[str, str]] = {
    "PERSON":        {"auditor": "keep", "vendor": "pseudonymize", "public": "pseudonymize"},
    "EMAIL_ADDRESS": {"auditor": "keep", "vendor": "tokenize",     "public": "redact"},
    "PHONE_NUMBER":  {"auditor": "keep", "vendor": "mask",         "public": "redact"},
    "LOCATION":      {"auditor": "keep", "vendor": "keep",         "public": "keep"},
    "CREDIT_CARD":   {"auditor": "mask", "vendor": "redact",       "public": "redact"},
    "AADHAAR":       {"auditor": "mask", "vendor": "redact",       "public": "redact"},
    "PAN":           {"auditor": "mask", "vendor": "redact",       "public": "redact"},
    # URL is intentionally absent: after reconciliation, standalone URLs are
    # rare in PII context (they're usually contained inside emails which
    # win). If one survives, the fallback below kicks in.
}

# Safe default for unknown entity types: redact. Fail-safe by default —
# never silently keep PII we don't have a policy for.
DEFAULT_TREATMENT: str = "redact"
