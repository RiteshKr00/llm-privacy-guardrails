"""PII detectors. Each detector emits list[Finding] for uniform downstream handling."""

from .india_regex import scan_aadhaar, scan_pan, synthetic_valid_aadhaar
from .llm import scan_with_llm
from .presidio import scan_with_presidio

__all__ = [
    "scan_aadhaar",
    "scan_pan",
    "scan_with_llm",
    "scan_with_presidio",
    "synthetic_valid_aadhaar",
]
