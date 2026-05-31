"""Eval harness — run agent variants against the labeled corpus, report metrics.

Compares FOUR detector configurations against the ground-truth labels:

    1. presidio_only         — Presidio defaults alone
    2. regex_only            — our India regex (Aadhaar + PAN) alone
    3. merged_unreconciled   — both, but no dedup (just concatenated findings)
    4. merged_reconciled     — both + reconciler (what the agent actually runs)

The interesting story is the delta between #3 and #4: the reconciler should
hold recall flat while dropping precision/F1 noise from overlapping findings.

Plus: treatment accuracy per recipient profile, on the reconciled pipeline.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

# Make scratch/ importable.
sys.path.insert(0, str(Path(__file__).parent.parent / "scratch"))

from finding import Finding
from india_regex import scan_aadhaar, scan_pan
from presidio_wrapper import scan_with_presidio
from reconcile import reconcile
from treatment import TREATMENT_MATRIX, DEFAULT_TREATMENT


# ─────────────────────────────────────────────────────────────────────────────
# Span matching (lenient: same entity_type + offset overlap)
# ─────────────────────────────────────────────────────────────────────────────

def spans_overlap(label: dict, finding: Finding) -> bool:
    """Standard interval-overlap formula on character offsets."""
    return label["start"] < finding.end and finding.start < label["end"]


def match_labels_to_findings(
    labels: list, findings: list[Finding]
) -> tuple[set[int], set[int]]:
    """Greedy match: for each label, claim the first compatible finding.

    Compatible = same entity_type AND offsets overlap.
    Returns (matched_label_indices, matched_finding_indices).
    """
    matched_l: set[int] = set()
    matched_f: set[int] = set()
    for li, label in enumerate(labels):
        for fi, f in enumerate(findings):
            if fi in matched_f:
                continue
            if label["entity_type"] == f.entity_type and spans_overlap(label, f):
                matched_l.add(li)
                matched_f.add(fi)
                break
    return matched_l, matched_f


# ─────────────────────────────────────────────────────────────────────────────
# Metric helpers
# ─────────────────────────────────────────────────────────────────────────────

def _safe_div(num: int, den: int) -> float:
    return num / den if den > 0 else 0.0


def evaluate_detector(corpus: list, detector_fn, name: str) -> dict:
    """Run `detector_fn` over every doc, aggregate TP/FP/FN, compute P/R/F1."""
    total_tp = total_fp = total_fn = 0
    for doc in corpus:
        labels = doc["labels"]
        findings = detector_fn(doc["text"])
        matched_l, matched_f = match_labels_to_findings(labels, findings)
        total_tp += len(matched_l)
        total_fn += len(labels) - len(matched_l)
        total_fp += len(findings) - len(matched_f)

    recall = _safe_div(total_tp, total_tp + total_fn)
    precision = _safe_div(total_tp, total_tp + total_fp)
    f1 = _safe_div(2 * recall * precision, recall + precision)
    return {
        "name": name,
        "tp": total_tp, "fp": total_fp, "fn": total_fn,
        "recall": recall, "precision": precision, "f1": f1,
    }


def evaluate_treatments(corpus: list) -> dict:
    """For each matched (label, finding), compare the matrix-decided treatment
    against the label's expected treatment, per profile.

    Only counts treatments for labels the agent actually detected — a label
    we missed at detection time can't be scored on treatment.
    """
    per_profile: dict = defaultdict(lambda: {"correct": 0, "total": 0})

    for doc in corpus:
        labels = doc["labels"]
        findings = reconcile(
            scan_with_presidio(doc["text"])
            + scan_aadhaar(doc["text"])
            + scan_pan(doc["text"])
        )
        matched_l, matched_f = match_labels_to_findings(labels, findings)

        for li in matched_l:
            label = labels[li]
            for fi, f in enumerate(findings):
                if fi not in matched_f:
                    continue
                if label["entity_type"] == f.entity_type and spans_overlap(label, f):
                    row = TREATMENT_MATRIX.get(f.entity_type, {})
                    for profile, expected in label["treatments"].items():
                        actual = row.get(profile, DEFAULT_TREATMENT)
                        per_profile[profile]["total"] += 1
                        if actual == expected:
                            per_profile[profile]["correct"] += 1
                    break

    return per_profile


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    corpus_dir = Path(__file__).parent / "corpus"
    docs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(corpus_dir.glob("*.json"))]
    n_labels = sum(len(d["labels"]) for d in docs)
    print(f"Loaded {len(docs)} docs with {n_labels} total labels.\n")

    print("=" * 86)
    print("DETECTION METRICS  (lenient match: same entity_type + offset overlap)")
    print("=" * 86)
    header = f"{'config':<28}  {'TP':>4}  {'FP':>4}  {'FN':>4}  {'recall':>8}  {'precision':>10}  {'F1':>7}"
    print()
    print(header)
    print("-" * 86)

    configs = [
        ("presidio_only", lambda t: scan_with_presidio(t)),
        ("regex_only (Aadhaar+PAN)", lambda t: scan_aadhaar(t) + scan_pan(t)),
        ("merged_unreconciled", lambda t: scan_with_presidio(t) + scan_aadhaar(t) + scan_pan(t)),
        ("merged_reconciled", lambda t: reconcile(scan_with_presidio(t) + scan_aadhaar(t) + scan_pan(t))),
    ]

    for name, fn in configs:
        m = evaluate_detector(docs, fn, name)
        print(
            f"{m['name']:<28}  {m['tp']:>4}  {m['fp']:>4}  {m['fn']:>4}  "
            f"{m['recall']:>8.2%}  {m['precision']:>10.2%}  {m['f1']:>7.2%}"
        )

    print()
    print("=" * 86)
    print("TREATMENT ACCURACY  (per recipient profile, reconciled pipeline only)")
    print("=" * 86)
    print()

    treatments = evaluate_treatments(docs)
    for profile in ("auditor", "vendor", "public"):
        counts = treatments[profile]
        acc = _safe_div(counts["correct"], counts["total"])
        print(f"  {profile:<10}  {counts['correct']:>3}/{counts['total']:<3}  ({acc:.0%})")

    print("\nDone.")


if __name__ == "__main__":
    main()
