#!/usr/bin/env python3
"""Validate historical division YAML files for basic consistency."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

import yaml


@dataclass
class Division:
    id: str
    file: Path
    parent: Optional[str]
    from_date: Optional[date]
    to_date: Optional[date]
    base_id: str
    raw: dict


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--countries-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "countries",
        help="Path to the countries directory (defaults to ../countries relative to this script)",
    )
    parser.add_argument(
        "--country",
        default="norway",
        help="Specific country folder to lint (defaults to 'norway')",
    )
    return parser.parse_args()


def parse_date(value, context: str, errors: List[str]) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        errors.append(f"{context}: expected ISO date string or null, got {value!r}")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        errors.append(f"{context}: invalid date '{value}': {exc}")
        return None


def normalize_parent(value, context: str, errors: List[str]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        # YAML treats "NO"/"YES" as booleans, so coerce back to strings.
        return "YES" if value else "NO"
    if isinstance(value, str):
        return value
    errors.append(f"{context}: parent must be string or null, got {value!r}")
    return None


def normalize_relation(value, context: str, errors: List[str]) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        ids: List[str] = []
        for item in value:
            if isinstance(item, str):
                ids.append(item)
            elif isinstance(item, dict):
                if "id" in item and isinstance(item["id"], str):
                    ids.append(item["id"])
                else:
                    errors.append(f"{context}: relation dict missing string 'id' field: {item!r}")
            else:
                errors.append(f"{context}: expected string or mapping with id, got {item!r}")
        return ids
    errors.append(f"{context}: expected list, got {type(value).__name__}")
    return []


def collect_divisions(country_root: Path, errors: List[str]) -> Dict[str, Division]:
    divisions: Dict[str, Division] = {}
    for yaml_path in sorted(country_root.rglob("*.yaml")):
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            errors.append(f"{yaml_path}: failed to parse YAML: {exc}")
            continue
        for block in data.get("divisions", []) or []:
            div_id = block.get("id")
            if not isinstance(div_id, str):
                errors.append(f"{yaml_path}: division missing string id: {block}")
                continue
            if div_id in divisions:
                errors.append(
                    f"{yaml_path}: duplicate division id '{div_id}' also defined in {divisions[div_id].file}"
                )
                continue
            from_date = parse_date(block.get("from"), f"{yaml_path} ({div_id})", errors)
            to_date = parse_date(block.get("to"), f"{yaml_path} ({div_id})", errors)
            base_id = div_id.rsplit(":", 1)[0]
            divisions[div_id] = Division(
                id=div_id,
                file=yaml_path,
                parent=normalize_parent(block.get("parent"), f"{yaml_path} ({div_id})", errors),
                from_date=from_date,
                to_date=to_date,
                base_id=base_id,
                raw=block,
            )
    return divisions


def validate_parent_links(divisions: Dict[str, Division], errors: List[str]) -> None:
    valid_ids = set(divisions)
    for div in divisions.values():
        parent = div.parent
        if parent is None:
            errors.append(f"{div.file} ({div.id}): missing parent reference")
        elif parent != "NO" and parent not in valid_ids:
            errors.append(f"{div.file} ({div.id}): parent '{parent}' not found in dataset")


def validate_dates(divisions: Dict[str, Division], errors: List[str]) -> None:
    groups: Dict[str, List[Division]] = {}
    for div in divisions.values():
        groups.setdefault(div.base_id, []).append(div)
        if div.from_date and div.to_date and div.from_date > div.to_date:
            errors.append(
                f"{div.file} ({div.id}): from date {div.from_date} is after to date {div.to_date}"
            )
    for base, subset in groups.items():
        subset.sort(key=lambda d: (d.from_date or date.min, d.to_date or date.max))
        last_to: Optional[date] = None
        for div in subset:
            if last_to and div.from_date and div.from_date <= last_to:
                errors.append(
                    f"Timeline overlap for {base}: {div.file} ({div.id}) starts {div.from_date} before previous ended {last_to}"
                )
            if div.to_date:
                last_to = div.to_date
            else:
                last_to = date.max


def validate_lineage(divisions: Dict[str, Division], errors: List[str]) -> None:
    def check_relation(source: Division, field: str, counterpart: str) -> None:
        ids = normalize_relation(source.raw.get(field), f"{source.file} ({source.id}) {field}", errors)
        for target_id in ids:
            target = divisions.get(target_id)
            if not target:
                errors.append(
                    f"{source.file} ({source.id}): {field} references unknown id '{target_id}'"
                )
                continue
            other_ids = normalize_relation(
                target.raw.get(counterpart),
                f"{target.file} ({target.id}) {counterpart}",
                errors,
            )
            if source.id not in other_ids:
                errors.append(
                    f"Lineage mismatch: {source.file} ({source.id}) {field} -> {target_id} without reciprocal {counterpart}"
                )

    for div in divisions.values():
        check_relation(div, "was", "became")
        check_relation(div, "became", "was")


def main() -> int:
    args = parse_args()
    country_path = args.countries_root / args.country
    if not country_path.exists():
        print(f"Country directory not found: {country_path}", file=sys.stderr)
        return 2
    errors: List[str] = []
    divisions = collect_divisions(country_path, errors)
    validate_parent_links(divisions, errors)
    validate_dates(divisions, errors)
    validate_lineage(divisions, errors)
    if errors:
        print("Schema lint found issues:", file=sys.stderr)
        for issue in errors:
            print(f" - {issue}", file=sys.stderr)
        return 1
    print(f"OK: {len(divisions)} divisions validated in {country_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
