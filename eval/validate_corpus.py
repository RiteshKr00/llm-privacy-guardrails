"""Validate the eval corpus.

For every JSON doc in eval/corpus/, assert that each label's `text` field
exactly matches `source_text[start:end]`. Catches offset drift early.

Run this any time you edit a doc by hand. Exit code 0 = all good, 1 = bugs.
"""

import json
import sys
from pathlib import Path


def validate_doc(doc: dict) -> list[str]:
    """Return a list of error messages (empty list means doc is clean)."""
    errors: list[str] = []
    text = doc["text"]

    for i, label in enumerate(doc["labels"]):
        actual = text[label["start"]:label["end"]]
        if actual != label["text"]:
            errors.append(
                f"  Label[{i}] entity_type={label['entity_type']}: "
                f"expected '{label['text']}', got '{actual}' "
                f"at offsets ({label['start']}, {label['end']})"
            )
    return errors


def main() -> int:
    corpus_dir = Path(__file__).parent / "corpus"
    if not corpus_dir.exists():
        print(f"No corpus directory at {corpus_dir} — run build_corpus.py first.")
        return 1

    json_files = sorted(corpus_dir.glob("*.json"))
    if not json_files:
        print(f"No JSON files in {corpus_dir} — run build_corpus.py first.")
        return 1

    failed = 0
    for json_path in json_files:
        doc = json.loads(json_path.read_text(encoding="utf-8"))
        errors = validate_doc(doc)
        if errors:
            failed += 1
            print(f"FAIL  {json_path.name}")
            for e in errors:
                print(e)
        else:
            print(f"PASS  {json_path.name}  ({len(doc['labels'])} labels)")

    if failed:
        print(f"\n{failed}/{len(json_files)} doc(s) have offset errors.")
    else:
        print(f"\nAll {len(json_files)} docs clean.")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
