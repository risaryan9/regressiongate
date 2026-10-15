"""Load, hash and validate a dataset directory (cases.jsonl + manifest.json)."""

import hashlib
import json
import subprocess
from pathlib import Path

from pydantic import ValidationError

from datasets.schema import SCHEMA_VERSION, Case, Manifest

CASES_FILE = "cases.jsonl"
MANIFEST_FILE = "manifest.json"


def read_rows(path: Path) -> list[tuple[int, str]]:
    """Non-empty lines as (line_number, text). A trailing newline is fine; blank lines inside are not."""
    lines = path.read_text(encoding="utf-8").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [(i, line) for i, line in enumerate(lines, start=1)]


def content_hash(rows: list[dict]) -> str:
    """sha256 over the rows in canonical form.

    Keys are sorted and whitespace is stripped first, so reformatting the file or
    reordering keys keeps the hash; only a real change to the data changes it.
    Row order does count, since it decides the order cases run in.
    """
    canonical = "\n".join(json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False) for r in rows)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_cases(dataset_dir: Path) -> tuple[list[Case], list[dict], list[str]]:
    """Parse and validate every row. Returns (cases, raw rows, errors)."""
    cases: list[Case] = []
    raw: list[dict] = []
    errors: list[str] = []
    seen: dict[str, int] = {}

    for lineno, line in read_rows(dataset_dir / CASES_FILE):
        if not line.strip():
            errors.append(f"line {lineno}: blank line")
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            errors.append(f"line {lineno}: not valid JSON ({e.msg})")
            continue
        raw.append(row)
        try:
            case = Case.model_validate(row)
        except ValidationError as e:
            for err in e.errors():
                field = ".".join(str(p) for p in err["loc"]) or "row"
                errors.append(f"line {lineno}: {field}: {err['msg']}")
            continue
        if case.id in seen:
            errors.append(f"line {lineno}: duplicate id '{case.id}' (first on line {seen[case.id]})")
        seen[case.id] = lineno
        cases.append(case)

    return cases, raw, errors


def load_manifest(dataset_dir: Path) -> Manifest:
    return Manifest.model_validate_json((dataset_dir / MANIFEST_FILE).read_text(encoding="utf-8"))


def manifest_at_ref(dataset_dir: Path, ref: str) -> Manifest | None:
    """The manifest as it was at a git ref, or None if it didn't exist there (or no git)."""
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=dataset_dir, capture_output=True, text=True, check=True
        ).stdout.strip()
        rel = (dataset_dir / MANIFEST_FILE).resolve().relative_to(top)
        text = subprocess.run(
            ["git", "show", f"{ref}:{rel.as_posix()}"], cwd=top, capture_output=True, text=True, check=True
        ).stdout
        return Manifest.model_validate_json(text)
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError, ValidationError):
        return None


def validate(dataset_dir: Path, base: Manifest | None) -> list[str]:
    """All problems with the dataset. Empty list means valid.

    base is the manifest from the last accepted version (e.g. on main). If the data
    differs from base, the version must have been bumped.
    """
    try:
        manifest = load_manifest(dataset_dir)
    except FileNotFoundError:
        return [f"missing {MANIFEST_FILE}"]
    except ValidationError as e:
        return [f"{MANIFEST_FILE}: {err['loc'][0] if err['loc'] else ''}: {err['msg']}" for err in e.errors()]
    try:
        cases, raw, errors = load_cases(dataset_dir)
    except FileNotFoundError:
        return [f"missing {CASES_FILE}"]

    if manifest.schema_version != SCHEMA_VERSION:
        errors.append(f"schema_version is {manifest.schema_version}, code expects {SCHEMA_VERSION}")
    if manifest.row_count != len(raw):
        errors.append(f"row_count is {manifest.row_count} but {CASES_FILE} has {len(raw)} rows")

    actual = content_hash(raw)
    if actual != manifest.sha256:
        errors.append(
            f"{CASES_FILE} changed but manifest sha256 was not updated. "
            f"Run `rgate bump {dataset_dir}` to bump the version and record the new hash."
        )

    if base is not None:
        if actual != base.sha256 and (manifest.version, manifest.schema_version) == (base.version, base.schema_version):
            errors.append(f"data changed but version is still {manifest.version}; bump it")
        if manifest.version < base.version:
            errors.append(f"version went backwards: {base.version} -> {manifest.version}")

    return errors


def bump(dataset_dir: Path) -> Manifest:
    """Increment the version and record the current row count and hash."""
    for name in (MANIFEST_FILE, CASES_FILE):
        if not (dataset_dir / name).is_file():
            raise ValueError(f"{dataset_dir} has no {name}; is this the right dataset folder?")
    manifest = load_manifest(dataset_dir)
    _, raw, errors = load_cases(dataset_dir)
    if errors:
        raise ValueError("fix these before bumping:\n" + "\n".join(errors))
    new_hash = content_hash(raw)
    if new_hash == manifest.sha256:
        raise ValueError("cases.jsonl hasn't changed since the last bump; nothing to do")
    updated = manifest.model_copy(update={"version": manifest.version + 1, "row_count": len(raw), "sha256": new_hash})
    (dataset_dir / MANIFEST_FILE).write_text(updated.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return updated
