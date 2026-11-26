"""Compare two report exports offline; never choose a winner for conflicts.

Writes a private review file, not an import payload. Neither source is mutated.
"""
import argparse
import json
from pathlib import Path
from export_insforge_for_migration import atomic_json


def indexed(rows):
    result = {}
    if not isinstance(rows, list):
        raise ValueError("Expected a JSON row array")
    for row in rows:
        key = row.get("id")
        if not isinstance(key, str) or not key or key in result:
            raise ValueError("Missing or duplicate report ID")
        result[key] = row
    return result


def reconcile(old_rows, insforge_rows):
    old, new = indexed(old_rows), indexed(insforge_rows)
    result = {"old_only": [], "insforge_only": [], "identical": [], "conflicts": []}
    for key in sorted(old.keys() | new.keys()):
        if key not in old:
            result["insforge_only"].append(key)
        elif key not in new:
            result["old_only"].append(key)
        elif old[key] == new[key]:
            result["identical"].append(key)
        else:
            fields = sorted(k for k in old[key].keys() | new[key].keys()
                            if k not in old[key] or k not in new[key] or old[key][k] != new[key][k])
            result["conflicts"].append({"id": key, "fields": fields})
    return result


def merge_verified_reports(old_rows, insforge_rows):
    """Union only missing fields; reject conflicting business values.

    The observed report-content difference is an absent _translations cache.
    Never use a last-write-wins rule for owners, visibility, balances or content.
    """
    old, new = indexed(old_rows), indexed(insforge_rows)
    merged = []
    for key in sorted(old.keys() | new.keys()):
        if key not in old or key not in new:
            merged.append(dict(old[key] if key in old else new[key]))
            continue
        row = dict(old[key])
        for field, value in new[key].items():
            if field not in row:
                row[field] = value
            elif row[field] != value:
                if field != 'report' or not isinstance(value, dict) or not isinstance(row[field], dict):
                    raise ValueError('Conflicting report field requires review: ' + field)
                left = row[field]
                different = {k for k in left.keys() | value.keys()
                             if k not in left or k not in value or left[k] != value[k]}
                if different != {'_translations'} or ('_translations' in left and '_translations' in value):
                    raise ValueError('Conflicting report content requires review')
                row[field] = {**left, **value}
        merged.append(row)
    return merged


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--old", type=Path, required=True)
    p.add_argument("--insforge", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        p.error("Output already exists; use a new review filename")
    result = reconcile(json.loads(args.old.read_text()), json.loads(args.insforge.read_text()))
    atomic_json(args.output, result)
    print(json.dumps({key: len(value) for key, value in result.items()}))
    return 2 if result["conflicts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
