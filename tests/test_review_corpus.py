"""Offline corpus contracts at the loading, export and correction seams."""

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from mapify_cli.skills_eval.review_corpus import export_case, load_corpus


def test_narrow_diff_matches_complete_literal_u30_and_keeps_full_export(
    tmp_path: Path,
) -> None:
    from mapify_cli.skills_eval.review_corpus import introducing_diff

    repo = Path(__file__).resolve().parents[1]
    root = repo / "tests/skills_eval/review_corpus"
    for case in load_corpus(root, repo)["cases"]:
        expected = subprocess.check_output(
            [
                "git",
                "--literal-pathspecs",
                "diff",
                "--no-ext-diff",
                "--no-textconv",
                "--no-renames",
                "--src-prefix=base/",
                "--dst-prefix=head/",
                "-U30",
                case["base"],
                case["head"],
                "--",
                *(f["path"] for f in case["files"]),
            ],
            cwd=repo,
        )
        assert introducing_diff(root, repo, case["id"]) == expected
        exported = export_case(root, repo, case["id"], tmp_path / case["id"])
        assert exported["schema_version"] == 1
        assert any(name.startswith("head/") for name in exported["files"])


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


@pytest.fixture
def corpus(tmp_path: Path) -> tuple[Path, Path, dict[str, Any]]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "Fixture")
    (repo / "link").symlink_to("code.py")
    git(repo, "add", "link")
    revisions = []
    blobs = []
    for value in ("return True", "return False", "return True # repaired"):
        (repo / "code.py").write_text(f"def valid():\n    {value}\n")
        git(repo, "add", "code.py")
        git(repo, "commit", "-qm", "snapshot")
        revisions.append(git(repo, "rev-parse", "HEAD"))
        blobs.append(git(repo, "rev-parse", "HEAD:code.py"))
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "repro.txt").write_text("base pass; head fails; fix pass\n")
    label = {
        "path": "code.py",
        "blob": blobs[1],
        "start_line": 2,
        "end_line": 2,
        "description": "Returns false",
        "fix_mapping": {
            "path": "code.py",
            "blob": blobs[2],
            "start_line": 2,
            "end_line": 2,
            "explanation": "Corrected return value",
        },
    }
    bug = {
        "id": "case-amber",
        "kind": "bug",
        "group": "shared-logic",
        "base": revisions[0],
        "head": revisions[1],
        "fix": revisions[2],
        "files": [{"path": "code.py", "base_blob": blobs[0], "head_blob": blobs[1]}],
        "labels": [label],
        "scenario": "Call valid()",
        "control_audit": None,
        "evidence": [
            {
                "path": "repro.txt",
                "sha256": hashlib.sha256((root / "repro.txt").read_bytes()).hexdigest(),
            }
        ],
    }
    control = {
        **bug,
        "id": "case-blue",
        "kind": "control",
        "labels": [],
        "fix": None,
        "control_audit": {
            "cutoff": revisions[2],
            "examined_commits": revisions,
            "limitations": "Tiny synthetic history",
            "attribution": "Audited history",
            "audited_at": "2026-10-19T00:00:00Z",
        },
    }
    data = {
        "schema_version": 1,
        "audit_cutoff": {"commit": revisions[2], "timestamp": "2026-10-18T00:00:00Z"},
        "cases": [bug, control],
        "dispositions": [
            {
                "issue": issue,
                "status": "admitted" if issue == 501 else "excluded",
                "case_ids": ["case-amber", "case-blue"] if issue == 501 else [],
                "reason": "Synthetic audit",
            }
            for issue in range(501, 521)
        ],
    }
    save(root, data)
    return root, repo, data


def save(root: Path, data: dict[str, Any]) -> None:
    (root / "corpus.json").write_text(json.dumps(data))


def test_loading_rejects_missing_case_record(
    corpus: tuple[Path, Path, dict[str, Any]],
) -> None:
    root, repo, data = corpus
    del data["cases"][0]["head"]
    save(root, data)
    with pytest.raises(ValueError, match="head"):
        load_corpus(root, repo)


@pytest.mark.parametrize(
    "mutation", ["root", "version", "case", "dispositions", "duplicate"]
)
def test_loading_rejects_malformed_authority(
    corpus: tuple[Path, Path, dict[str, Any]], mutation: str
) -> None:
    root, repo, data = corpus
    if mutation == "root":
        (root / "corpus.json").write_text("[]")
    else:
        if mutation == "version":
            data["schema_version"] = 2
        elif mutation == "case":
            data["cases"][0]["files"] = "code.py"
        elif mutation == "dispositions":
            data["dispositions"].pop()
        else:
            data["cases"].append(data["cases"][0])
        save(root, data)
    with pytest.raises(ValueError):
        load_corpus(root, repo)


@pytest.mark.parametrize(
    "mutation", ["parent", "fix-input", "blob", "range", "unknown", "ambiguous"]
)
def test_loading_rejects_unbound_historical_labels(
    corpus: tuple[Path, Path, dict[str, Any]], mutation: str
) -> None:
    root, repo, data = corpus
    case = data["cases"][0]
    if mutation == "parent":
        case["base"] = case["fix"]
    elif mutation == "fix-input":
        case["head"] = case["fix"]
    elif mutation == "blob":
        case["labels"][0]["blob"] = case["files"][0]["base_blob"]
    elif mutation == "range":
        case["labels"][0]["end_line"] = 99
    elif mutation == "unknown":
        case["labels"][0]["path"] = "missing.py"
    else:
        case["base"] = "HEAD~1"
    save(root, data)
    with pytest.raises(ValueError):
        load_corpus(root, repo)


@pytest.mark.parametrize(
    "mutation", ["audit", "cutoff", "evidence", "traversal", "kind", "empty"]
)
def test_loading_requires_audited_integrity(
    corpus: tuple[Path, Path, dict[str, Any]], mutation: str
) -> None:
    root, repo, data = corpus
    if mutation == "audit":
        data["cases"][1]["control_audit"] = None
    elif mutation == "cutoff":
        data["cases"][1]["control_audit"]["cutoff"] = data["cases"][1]["base"]
    elif mutation == "evidence":
        (root / "repro.txt").write_text("tampered")
    elif mutation == "traversal":
        data["cases"][0]["files"][0]["path"] = "../code.py"
    elif mutation == "kind":
        data["cases"][0]["kind"] = "maybe"
    else:
        data["cases"][0]["evidence"] = []
    save(root, data)
    with pytest.raises(ValueError):
        load_corpus(root, repo)


def test_valid_corpus_loads_pinned_cases(
    corpus: tuple[Path, Path, dict[str, Any]],
) -> None:
    root, repo, _ = corpus
    assert [case["id"] for case in load_corpus(root, repo)["cases"]] == [
        "case-amber",
        "case-blue",
    ]


def test_export_contains_only_allowlisted_historical_input(
    corpus: tuple[Path, Path, dict[str, Any]], tmp_path: Path
) -> None:
    root, repo, data = corpus
    output = tmp_path / "reviewer"
    export_case(root, repo, "case-amber", output)
    assert (output / "head/code.py").read_text() == "def valid():\n    return False\n"
    assert (output / "base/code.py").read_text() == "def valid():\n    return True\n"
    assert sorted(
        str(p.relative_to(output)) for p in output.rglob("*") if p.is_file()
    ) == ["base/code.py", "head/code.py", "input.json", "review.diff"]
    contents = "\n".join(p.read_text() for p in output.rglob("*") if p.is_file())
    for forbidden in (
        data["cases"][0]["fix"],
        "Returns false",
        "shared-logic",
        "repro.txt",
        "repaired",
    ):
        assert forbidden not in contents
    assert "+    return False" in (output / "review.diff").read_text()
    with pytest.raises(ValueError, match="exist"):
        export_case(root, repo, "case-amber", output)


def test_correction_invalidates_bound_evidence_after_reload(corpus):
    from mapify_cli.skills_eval.review_corpus import (
        correct_labels,
        evidence_binding,
        require_fresh_evidence,
    )

    root, repo, data = corpus
    state = root / "state.json"
    binding = evidence_binding(root, repo, "case-amber", state)
    labels = data["cases"][0]["labels"]
    labels[0]["description"] = "Corrected adjudication"
    result = correct_labels(
        root,
        repo,
        state,
        "c-one",
        "case-amber",
        labels,
        expected_revision=0,
        reason="Human correction",
    )
    assert result["revision"] == 1
    assert result["history"][0]["reason"] == "Human correction"
    with pytest.raises(ValueError, match="stale"):
        require_fresh_evidence(root, repo, "case-amber", state, binding)
    fresh = evidence_binding(root, repo, "case-amber", state)
    require_fresh_evidence(root, repo, "case-amber", state, fresh)
    assert (
        correct_labels(
            root,
            repo,
            state,
            "c-one",
            "case-amber",
            labels,
            expected_revision=0,
            reason="Human correction",
        )
        == result
    )
    with pytest.raises(ValueError, match="conflict"):
        correct_labels(
            root,
            repo,
            state,
            "c-one",
            "case-amber",
            labels,
            expected_revision=0,
            reason="Different payload",
        )
    with pytest.raises(ValueError, match="revision"):
        correct_labels(
            root,
            repo,
            state,
            "c-two",
            "case-amber",
            labels,
            expected_revision=0,
            reason="Stale writer",
        )


@pytest.mark.parametrize("damage", ["history", "revision", "truncated", "symlink"])
def test_corrections_never_reset_corrupt_state(corpus, damage):
    from mapify_cli.skills_eval.review_corpus import correct_labels, evidence_binding

    root, repo, data = corpus
    state = root / "state.json"
    correct_labels(
        root,
        repo,
        state,
        "c-one",
        "case-amber",
        data["cases"][0]["labels"],
        expected_revision=0,
        reason="confirmed",
    )
    if damage == "truncated":
        state.write_text("{")
    elif damage == "symlink":
        target = root / "moved.json"
        state.rename(target)
        state.symlink_to(target)
    else:
        contents = json.loads(state.read_text())
        if damage == "history":
            contents["history"][0]["labels"][0]["end_line"] = 99
        else:
            contents["revision"] = True
        state.write_text(json.dumps(contents))
    with pytest.raises(ValueError):
        evidence_binding(root, repo, "case-amber", state)


def test_offline_cli_validates_exports_and_binds(corpus, tmp_path):
    import sys

    root, repo, _ = corpus
    args = [sys.executable, "-m", "mapify_cli.skills_eval.review_corpus"]

    def run(*options):
        return subprocess.run(
            [*args, *options], check=False, capture_output=True, text=True
        )

    result = run("validate", str(root), "--repo", str(repo))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["cases"] == 2
    output = tmp_path / "bundle"
    result = run(
        "export",
        str(root),
        "--repo",
        str(repo),
        "--case",
        "case-amber",
        "--out",
        str(output),
    )
    assert result.returncode == 0, result.stderr
    assert (output / "review.diff").is_file()
    result = run("validate", str(tmp_path / "missing"), "--repo", str(repo))
    assert result.returncode == 2
    assert "Error:" in result.stderr


def test_cli_correction_and_freshness_survive_process_restart(corpus):
    import sys

    root, repo, data = corpus
    state = root / "state.json"
    args = [sys.executable, "-m", "mapify_cli.skills_eval.review_corpus"]
    common = [
        str(root),
        "--repo",
        str(repo),
        "--case",
        "case-amber",
        "--state",
        str(state),
    ]
    before = subprocess.run(
        [*args, "bind", *common], check=False, capture_output=True, text=True
    )
    assert before.returncode == 0, before.stderr
    binding = root / "binding.json"
    binding.write_text(before.stdout)
    labels = root / "labels.json"
    labels.write_text(json.dumps(data["cases"][0]["labels"]))
    corrected = subprocess.run(
        [
            *args,
            "correct",
            *common,
            "--id",
            "one",
            "--labels",
            str(labels),
            "--expected-revision",
            "0",
            "--reason",
            "verified",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert corrected.returncode == 0, corrected.stderr
    stale = subprocess.run(
        [*args, "freshness", *common, "--binding", str(binding)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert stale.returncode == 2
    assert "stale" in stale.stderr
    assert binding.read_text() == before.stdout


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate-json",
        "unknown-disposition",
        "unsafe-id",
        "empty-files",
        "lock-link",
        "control-labels",
    ],
)
def test_fail_closed_at_authority_and_correction_boundaries(corpus, mutation):
    from mapify_cli.skills_eval.review_corpus import correct_labels

    root, repo, data = corpus
    state = root / "state.json"
    if mutation == "duplicate-json":
        text = (root / "corpus.json").read_text()
        (root / "corpus.json").write_text(
            text.replace(
                '"schema_version": 1', '"schema_version": 2, "schema_version": 1'
            )
        )
    elif mutation == "lock-link":
        (root / "state.json.lock").symlink_to(root / "repro.txt")
    else:
        if mutation == "unknown-disposition":
            data["dispositions"][0] = None
        elif mutation == "unsafe-id":
            data["cases"][0]["id"] = "../oops"
        elif mutation == "empty-files":
            data["cases"][1]["files"] = []
        save(root, data)
    with pytest.raises(ValueError):
        if mutation in {"lock-link", "control-labels"}:
            correct_labels(
                root,
                repo,
                state,
                "one",
                "case-blue",
                data["cases"][0]["labels"],
                expected_revision=0,
                reason="invalid",
            )
        else:
            load_corpus(root, repo)


def test_export_rejects_symlink_source(corpus):
    root, repo, data = corpus
    case = data["cases"][1]
    case["files"] = [
        {
            "path": "link",
            "base_blob": git(repo, "rev-parse", "HEAD:link"),
            "head_blob": git(repo, "rev-parse", "HEAD:link"),
        }
    ]
    save(root, data)
    with pytest.raises(ValueError, match="regular"):
        export_case(root, repo, "case-blue", root / "out")


def test_failed_replace_preserves_previous_revision(corpus, monkeypatch):
    import os

    from mapify_cli.skills_eval.review_corpus import correct_labels, evidence_binding

    root, repo, data = corpus
    state = root / "state.json"
    labels = data["cases"][0]["labels"]
    correct_labels(
        root,
        repo,
        state,
        "one",
        "case-amber",
        labels,
        expected_revision=0,
        reason="first",
    )
    before = evidence_binding(root, repo, "case-amber", state)

    def failed_replace(*_args):
        raise OSError("simulated interrupted publication")

    monkeypatch.setattr(os, "replace", failed_replace)
    with pytest.raises(OSError, match="interrupted"):
        correct_labels(
            root,
            repo,
            state,
            "two",
            "case-amber",
            labels,
            expected_revision=1,
            reason="second",
        )
    assert evidence_binding(root, repo, "case-amber", state) == before
    assert sorted(p.name for p in root.glob("state.json.*")) == ["state.json.lock"]


def test_concurrent_corrections_allow_exactly_one_expected_revision(corpus):
    import sys

    root, repo, data = corpus
    state = root / "state.json"
    labels = root / "labels.json"
    labels.write_text(json.dumps(data["cases"][0]["labels"]))
    common = [
        sys.executable,
        "-m",
        "mapify_cli.skills_eval.review_corpus",
        "correct",
        str(root),
        "--repo",
        str(repo),
        "--state",
        str(state),
        "--case",
        "case-amber",
        "--labels",
        str(labels),
        "--expected-revision",
        "0",
        "--reason",
        "race",
    ]
    processes = [
        subprocess.Popen(
            [*common, "--id", name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for name in ("one", "two")
    ]
    outputs = [process.communicate(timeout=30) for process in processes]
    assert sorted(process.returncode for process in processes) == [0, 2], outputs
    assert any("revision mismatch" in stderr for _, stderr in outputs)


@pytest.mark.parametrize(
    "mutation",
    ["bool-version", "cutoff", "unlinked", "bad-id", "duplicate-path", "only-controls"],
)
def test_complete_corpus_authority_is_required(corpus, mutation):
    root, repo, data = corpus
    if mutation == "bool-version":
        data["schema_version"] = True
    elif mutation == "cutoff":
        del data["audit_cutoff"]
    elif mutation == "unlinked":
        data["dispositions"][0]["case_ids"] = ["case-amber"]
    elif mutation == "bad-id":
        data["cases"][0]["id"] = "../oops"
        data["dispositions"][0]["case_ids"][0] = "../oops"
    elif mutation == "duplicate-path":
        data["cases"][0]["files"].append(data["cases"][0]["files"][0])
    else:
        data["cases"] = data["cases"][1:]
        data["dispositions"][0]["case_ids"] = ["case-blue"]
    save(root, data)
    with pytest.raises(ValueError):
        load_corpus(root, repo)


def test_committed_corpus_exports_every_admitted_case(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    root = repo / "tests/skills_eval/review_corpus"
    data = load_corpus(root, repo)
    assert {case["kind"] for case in data["cases"]} == {"bug", "control"}
    assert {entry["issue"] for entry in data["dispositions"]} == set(range(501, 521))
    for case in data["cases"]:
        output = tmp_path / case["id"]
        manifest = export_case(root, repo, case["id"], output)
        assert (output / "review.diff").stat().st_size > 0
        assert set(manifest) == {"schema_version", "case_id", "files"}
        assert not (output / ".git").exists()
        for relative, digest in manifest["files"].items():
            assert (
                hashlib.sha256((output / relative).read_bytes()).hexdigest() == digest
            )
        if case["fix"]:
            assert case["fix"] not in (output / "input.json").read_text()


@pytest.mark.parametrize(
    "field,value",
    [
        ("correction_id", ""),
        ("reason", ""),
        ("expected_revision", False),
        ("labels", {}),
    ],
)
def test_invalid_correction_payload_cannot_poison_state(corpus, field, value):
    from mapify_cli.skills_eval.review_corpus import correct_labels, evidence_binding

    root, repo, data = corpus
    state = root / "state.json"
    before = evidence_binding(root, repo, "case-amber", state)
    arguments = {
        "correction_id": "one",
        "case_id": "case-amber",
        "labels": data["cases"][0]["labels"],
        "expected_revision": 0,
        "reason": "checked",
    }
    arguments[field] = value
    with pytest.raises(ValueError):
        correct_labels(root, repo, state, **arguments)
    assert evidence_binding(root, repo, "case-amber", state) == before
    assert not state.exists()


def test_malformed_disposition_links_raise_validation_error(corpus):
    root, repo, data = corpus
    data["dispositions"][0]["case_ids"] = [{}]
    save(root, data)
    with pytest.raises(ValueError, match="case_ids"):
        load_corpus(root, repo)


def test_cli_rejects_duplicate_label_keys_without_mutation(corpus):
    import sys

    root, repo, data = corpus
    labels = root / "labels.json"
    labels.write_text(
        json.dumps(data["cases"][0]["labels"]).replace(
            '"start_line": 2', '"start_line": 999, "start_line": 2'
        )
    )
    state = root / "state.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mapify_cli.skills_eval.review_corpus",
            "correct",
            str(root),
            "--repo",
            str(repo),
            "--state",
            str(state),
            "--case",
            "case-amber",
            "--id",
            "one",
            "--reason",
            "checked",
            "--labels",
            str(labels),
            "--expected-revision",
            "0",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "duplicate JSON key" in result.stderr
    assert not state.exists()


def test_invalid_correction_preserves_existing_state_bytes(corpus):
    from mapify_cli.skills_eval.review_corpus import correct_labels

    root, repo, data = corpus
    state = root / "state.json"
    labels = data["cases"][0]["labels"]
    correct_labels(
        root,
        repo,
        state,
        "one",
        "case-amber",
        labels,
        expected_revision=0,
        reason="first",
    )
    before = state.read_bytes()
    with pytest.raises(ValueError, match="reason"):
        correct_labels(
            root,
            repo,
            state,
            "two",
            "case-amber",
            labels,
            expected_revision=1,
            reason="",
        )
    assert state.read_bytes() == before


def test_missing_corpus_is_a_validation_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="corpus"):
        load_corpus(tmp_path, tmp_path)
