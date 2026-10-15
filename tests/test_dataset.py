import json
import shutil
import subprocess
from pathlib import Path

import pytest

from datasets.dataset import bump, content_hash, load_cases, load_manifest, manifest_at_ref, validate

REAL_DATASET = Path(__file__).parent.parent / "datasets" / "support"

GOOD_ROW = {
    "id": "case_one",
    "ticket": "Refund A1001",
    "allowed_actions": ["refund"],
    "reply_criteria": "Approves the refund.",
}


@pytest.fixture
def ds(tmp_path) -> Path:
    """A copy of the real dataset that tests can freely edit."""
    target = tmp_path / "support"
    shutil.copytree(REAL_DATASET, target)
    return target


def write_rows(ds: Path, rows: list) -> None:
    lines = [r if isinstance(r, str) else json.dumps(r) for r in rows]
    (ds / "cases.jsonl").write_text("\n".join(lines) + "\n")


def append_case(ds: Path, **overrides) -> None:
    with open(ds / "cases.jsonl", "a") as f:
        f.write(json.dumps({**GOOD_ROW, **overrides}) + "\n")


# --- the real dataset ------------------------------------------------------


def test_real_dataset_is_valid():
    assert validate(REAL_DATASET, base=None) == []
    assert load_manifest(REAL_DATASET).row_count == 25


# --- hashing ---------------------------------------------------------------


def test_hash_ignores_key_order_and_whitespace():
    a = [{"id": "x", "ticket": "hi"}]
    b = [{"ticket": "hi", "id": "x"}]
    assert content_hash(a) == content_hash(b)


def test_hash_changes_when_data_changes():
    assert content_hash([{"ticket": "hi"}]) != content_hash([{"ticket": "hi!"}])


def test_reformatting_file_keeps_dataset_valid(ds):
    rows = [json.loads(line) for line in (ds / "cases.jsonl").read_text().splitlines()]
    write_rows(ds, [json.dumps(r, indent=None, separators=(", ", " : ")) for r in rows])
    assert validate(ds, base=None) == []


# --- schema errors ---------------------------------------------------------


def test_schema_errors_report_line_and_field(ds):
    write_rows(ds, [GOOD_ROW, {**GOOD_ROW, "id": "bad", "allowed_actions": ["teleport"]}])
    _, _, errors = load_cases(ds)
    assert len(errors) == 1
    assert errors[0].startswith("line 2: allowed_actions.0:")


def test_unknown_field_is_rejected(ds):
    write_rows(ds, [{**GOOD_ROW, "alowed_actions": ["refund"]}])
    _, _, errors = load_cases(ds)
    assert any("alowed_actions" in e for e in errors)


def test_tool_in_must_call_and_must_not_call(ds):
    write_rows(ds, [{**GOOD_ROW, "must_call": ["escalate"], "must_not_call": ["escalate"]}])
    _, _, errors = load_cases(ds)
    assert any("must_call and must_not_call" in e for e in errors)


def test_invalid_json_blank_line_and_duplicate_id(ds):
    write_rows(ds, [GOOD_ROW, "{not json", "", GOOD_ROW])
    _, _, errors = load_cases(ds)
    assert "line 2: not valid JSON" in errors[0]
    assert errors[1] == "line 3: blank line"
    assert errors[2] == "line 4: duplicate id 'case_one' (first on line 1)"


# --- manifest checks -------------------------------------------------------


def test_edit_without_bump_is_caught(ds):
    append_case(ds, id="new_case")
    errors = validate(ds, base=None)
    assert any("row_count is" in e for e in errors)
    assert any("manifest sha256 was not updated" in e for e in errors)


def test_bump_fixes_it_and_increments_version(ds):
    start = load_manifest(ds)
    append_case(ds, id="new_case")
    m = bump(ds)
    assert (m.version, m.row_count) == (start.version + 1, start.row_count + 1)
    assert validate(ds, base=None) == []


def test_bump_refuses_when_nothing_changed(ds):
    with pytest.raises(ValueError, match="hasn't changed"):
        bump(ds)


def test_bump_wrong_folder_gives_clear_error(tmp_path):
    (tmp_path / "cases.jsonl").write_text(json.dumps(GOOD_ROW) + "\n")
    with pytest.raises(ValueError, match="has no manifest.json"):
        bump(tmp_path)


def test_hand_updated_hash_without_version_bump_fails_against_base(ds):
    base = load_manifest(ds)
    append_case(ds, id="new_case")
    m = bump(ds)
    # Simulate someone updating the hash by hand but resetting the version.
    (ds / "manifest.json").write_text(m.model_copy(update={"version": base.version}).model_dump_json())
    assert validate(ds, base=base) == [f"data changed but version is still {base.version}; bump it"]


def test_version_going_backwards_fails(ds):
    base = load_manifest(ds).model_copy(update={"version": 5})
    assert any("went backwards" in e for e in validate(ds, base=base))


# --- git base --------------------------------------------------------------


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_end_to_end_against_git_ref(ds):
    repo = ds.parent
    git(repo, "init", "-q")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "v1")

    base = manifest_at_ref(ds, "HEAD")
    assert base is not None and base.version == load_manifest(ds).version
    assert validate(ds, base) == []

    append_case(ds, id="new_case")
    assert validate(ds, base) != []  # edited, not bumped

    bump(ds)
    assert validate(ds, base) == []  # bumped: ok


def test_manifest_at_ref_missing_returns_none(ds):
    assert manifest_at_ref(ds, "HEAD") is None  # tmp dir is not a git repo
