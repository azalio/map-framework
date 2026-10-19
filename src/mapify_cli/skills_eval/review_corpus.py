"""Offline historical review corpus; never dispatches reviewers."""

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> Any:
    if path.is_symlink():
        raise ValueError("JSON authority must not be a symlink")
    return json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object
    )


def _record(value: Any, fields: dict[str, type]) -> None:
    if not isinstance(value, dict):
        raise ValueError("expected object")
    for key, kind in fields.items():
        if type(value.get(key)) is not kind or (kind is str and not value[key].strip()):
            raise ValueError(f"invalid or missing {key}")


def _git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "--no-replace-objects", "--literal-pathspecs", *args],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise ValueError(
            f"cannot resolve historical object: {result.stderr.decode(errors='replace')}"
        )
    return result.stdout


def _sha(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("historical object must be a full SHA")
    return value


def _label(label: Any, repo: Path, commit: str) -> None:
    _record(label, {"path": str, "blob": str, "start_line": int, "end_line": int})
    blob = _sha(label["blob"])
    actual = _git(repo, "rev-parse", f"{commit}:{label['path']}").decode().strip()
    if actual != blob:
        raise ValueError("label blob mismatch")
    size = len(_git(repo, "cat-file", "blob", blob).splitlines())
    if not 1 <= label["start_line"] <= label["end_line"] <= size:
        raise ValueError("label range outside blob")


def _path(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or any(p in {"", ".", "..", ".git"} for p in value.split("/"))
        or value.startswith("/")
        or ":" in value
        or "\x00" in value
    ):
        raise ValueError("unsafe corpus path")
    return value


def _audit(case: dict[str, Any], data: dict[str, Any], root: Path, repo: Path) -> None:
    if case["kind"] not in {"bug", "control"}:
        raise ValueError("invalid case kind")
    if not case["evidence"]:
        raise ValueError("missing confirming evidence")
    for evidence in case["evidence"]:
        _record(evidence, {"path": str, "sha256": str})
        path = root / _path(evidence["path"])
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("evidence escapes corpus")
        if hashlib.sha256(path.read_bytes()).hexdigest() != evidence["sha256"]:
            raise ValueError("evidence digest mismatch")
    if case["kind"] == "control":
        audit: Any = case.get("control_audit")
        _record(
            audit,
            {
                "cutoff": str,
                "examined_commits": list,
                "limitations": str,
                "audited_at": str,
                "attribution": str,
            },
        )
        if case["labels"] or case.get("fix") is not None:
            raise ValueError("control has bug adjudication")
        if (
            audit["cutoff"] != data["audit_cutoff"]["commit"]
            or not audit["examined_commits"]
        ):
            raise ValueError("control cutoff mismatch or missing history")
        _git(repo, "merge-base", "--is-ancestor", case["head"], _sha(audit["cutoff"]))
        for commit in audit["examined_commits"]:
            _git(repo, "cat-file", "-e", f"{_sha(commit)}^{{commit}}")


def _historical_case(case: dict[str, Any], repo: Path) -> None:
    base, head = _sha(case["base"]), _sha(case["head"])
    parents = _git(repo, "show", "-s", "--format=%P", head).decode().strip().split()
    if parents != [base]:
        raise ValueError("ambiguous or wrong introducing parent")
    if not case["files"]:
        raise ValueError("missing source allowlist")
    if case["kind"] == "control" and case["labels"]:
        raise ValueError("control cannot acquire bug labels")
    paths = set()
    for file in case["files"]:
        _record(file, {"path": str, "head_blob": str})
        _path(file["path"])
        if file["path"] in paths:
            raise ValueError("duplicate allowlisted path")
        paths.add(file["path"])
        for commit, key in ((base, "base_blob"), (head, "head_blob")):
            expected = file.get(key)
            entries = _git(repo, "ls-tree", commit, "--", file["path"]).decode().split()
            if expected is None and key == "base_blob" and not entries:
                continue
            if len(entries) < 3 or entries[2] != _sha(expected):
                raise ValueError("source blob mismatch")
            if entries[0] not in {"100644", "100755"} or entries[1] != "blob":
                raise ValueError("source must be a regular file")
    if case["kind"] == "bug":
        fix = _sha(case.get("fix"))
        if fix == head:
            raise ValueError("fixing input substituted for introduction")
        _git(repo, "merge-base", "--is-ancestor", head, fix)
        if not case["labels"]:
            raise ValueError("bug requires labels")
        for label in case["labels"]:
            _label(label, repo, head)
            if label["path"] not in paths:
                raise ValueError("label path not allowlisted")
            _record(label, {"description": str, "fix_mapping": dict})
            _label(label["fix_mapping"], repo, fix)
            _record(label["fix_mapping"], {"explanation": str})


def load_corpus(corpus_dir: Path, repo: Path) -> dict[str, Any]:
    """Load curated authority, raising ValueError on invalid input."""
    try:
        data = _read_json(corpus_dir / "corpus.json")
        _record(data, {"schema_version": int, "audit_cutoff": dict})
        if data["schema_version"] != 1:
            raise ValueError("invalid corpus schema_version")
        _record(data["audit_cutoff"], {"commit": str, "timestamp": str})
        _git(
            repo, "cat-file", "-e", f"{_sha(data['audit_cutoff']['commit'])}^{{commit}}"
        )
        cases = data.get("cases")
        if not isinstance(cases, list) or not cases:
            raise ValueError("cases must be a nonempty list")
        ids = set()
        for case in cases:
            _record(
                case,
                {
                    "id": str,
                    "kind": str,
                    "group": str,
                    "base": str,
                    "head": str,
                    "files": list,
                    "labels": list,
                    "scenario": str,
                    "evidence": list,
                },
            )
            if not re.fullmatch(r"[a-z][a-z0-9-]{2,63}", case["id"]):
                raise ValueError("case id must be an opaque slug")
            if case["id"] in ids:
                raise ValueError("duplicate case id")
            ids.add(case["id"])
            _historical_case(case, repo)
            _audit(case, data, corpus_dir, repo)
        if {case["kind"] for case in cases} != {"bug", "control"}:
            raise ValueError("corpus requires admitted bugs and audited controls")
        dispositions = data.get("dispositions")
        if not isinstance(dispositions, list) or len(dispositions) != 20:
            raise ValueError("dispositions must cover issues 501–520")
        for disposition in dispositions:
            _record(
                disposition,
                {"issue": int, "status": str, "case_ids": list, "reason": str},
            )
        if {d["issue"] for d in dispositions} != set(range(501, 521)):
            raise ValueError("dispositions must cover issues 501–520")
        for disposition in dispositions:
            _record(
                disposition,
                {"issue": int, "status": str, "case_ids": list, "reason": str},
            )
            status = disposition["status"]
            linked = disposition["case_ids"]
            if any(not isinstance(case_id, str) for case_id in linked):
                raise ValueError("case_ids must contain strings")
            if status not in {"admitted", "excluded"} or not set(linked) <= ids:
                raise ValueError("invalid disposition")
            if bool(linked) != (status == "admitted"):
                raise ValueError("disposition admission mismatch")
        if {case_id for d in dispositions for case_id in d["case_ids"]} != ids:
            raise ValueError("case missing admission disposition")
        return data
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read corpus: {exc}") from exc


def export_case(
    corpus_dir: Path, repo: Path, case_id: str, destination: Path
) -> dict[str, Any]:
    """Write plain allowlisted historical input, not an OS sandbox."""
    data = load_corpus(corpus_dir, repo)
    case = next((c for c in data["cases"] if c["id"] == case_id), None)
    if case is None:
        raise ValueError("unknown case")
    if destination.exists() or destination.is_symlink():
        raise ValueError("export destination already exists")
    destination.mkdir(parents=True)
    hashes = {}
    for file in case["files"]:
        for side in ("base", "head"):
            blob = file.get(f"{side}_blob")
            if blob is None:
                continue
            content = _git(repo, "cat-file", "blob", blob)
            relative = f"{side}/{file['path']}"
            path = destination / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            hashes[relative] = hashlib.sha256(content).hexdigest()
    diff = _git(
        repo,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--src-prefix=base/",
        "--dst-prefix=head/",
        case["base"],
        case["head"],
        "--",
        *(file["path"] for file in case["files"]),
    )
    (destination / "review.diff").write_bytes(diff)
    hashes["review.diff"] = hashlib.sha256(diff).hexdigest()
    manifest = {"schema_version": 1, "case_id": case_id, "files": hashes}
    (destination / "input.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")
    return manifest


def introducing_diff(corpus_dir: Path, repo: Path, case_id: str) -> bytes:
    """Return the complete literal-allowlisted introducing diff with 30 context lines.

    Unlike export_case, this narrow profile never materializes full source snapshots.
    Historical parent/blob and corpus checks remain identical to the full exporter.
    """
    data = load_corpus(corpus_dir, repo)
    case = next((c for c in data["cases"] if c["id"] == case_id), None)
    if case is None:
        raise ValueError("unknown case")
    return _git(
        repo,
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
        *(file["path"] for file in case["files"]),
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _state(path: Path, corpus_hash: str) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError("correction state must not be a symlink")
    if not path.exists():
        return {
            "schema_version": 1,
            "corpus_hash": corpus_hash,
            "revision": 0,
            "history": [],
        }
    try:
        state = _read_json(path)
        _record(
            state,
            {
                "schema_version": int,
                "corpus_hash": str,
                "revision": int,
                "history": list,
            },
        )
        if state["schema_version"] != 1 or state["corpus_hash"] != corpus_hash:
            raise ValueError("state corpus mismatch")
        if state["revision"] != len(state["history"]):
            raise ValueError("corrupt state history")
        ids = set()
        for revision, entry in enumerate(state["history"]):
            _record(
                entry,
                {
                    "id": str,
                    "case_id": str,
                    "labels": list,
                    "expected_revision": int,
                    "reason": str,
                    "payload_hash": str,
                },
            )
            if entry["id"] in ids or entry["expected_revision"] != revision:
                raise ValueError("corrupt correction sequence")
            ids.add(entry["id"])
            if entry["payload_hash"] != _digest(
                {k: v for k, v in entry.items() if k != "payload_hash"}
            ):
                raise ValueError("corrupt correction content")
        return state
    except (OSError, ValueError) as exc:
        raise ValueError(f"invalid correction state: {exc}") from exc


def evidence_binding(
    corpus_dir: Path, repo: Path, case_id: str, state_path: Path
) -> dict[str, Any]:
    """Return the exact authority binding required for derived evidence consumption."""
    data = load_corpus(corpus_dir, repo)
    state = _state(state_path, _digest(data))
    case = next((c for c in data["cases"] if c["id"] == case_id), None)
    if case is None:
        raise ValueError("unknown case")
    labels = case["labels"]
    for correction in state["history"]:
        if correction["case_id"] == case_id:
            labels = correction["labels"]
    return {
        "corpus_hash": _digest(data),
        "revision": state["revision"],
        "state_hash": _digest(state),
        "case_id": case_id,
        "input_hash": _digest({k: case[k] for k in ("base", "head", "files")}),
        "labels_hash": _digest(labels),
    }


def require_fresh_evidence(
    corpus_dir: Path,
    repo: Path,
    case_id: str,
    state_path: Path,
    binding: dict[str, Any],
) -> None:
    """Reject stale/missing/tampered derived bindings; do not rewrite raw evidence."""
    if binding != evidence_binding(corpus_dir, repo, case_id, state_path):
        raise ValueError("stale or missing evidence binding")


def correct_labels(
    corpus_dir: Path,
    repo: Path,
    state_path: Path,
    correction_id: str,
    case_id: str,
    labels: list[dict[str, Any]],
    *,
    expected_revision: int,
    reason: str,
) -> dict[str, Any]:
    """Serialize idempotent corrections through a stable lock and atomic state replace."""
    import fcntl
    import os
    import tempfile

    state_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = state_path.with_suffix(state_path.suffix + ".lock")
    if lock_path.is_symlink():
        raise ValueError("correction lock must not be a symlink")
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = load_corpus(corpus_dir, repo)
        state = _state(state_path, _digest(data))
        payload = {
            "id": correction_id,
            "case_id": case_id,
            "labels": labels,
            "expected_revision": expected_revision,
            "reason": reason,
        }
        _record(
            payload,
            {
                "id": str,
                "case_id": str,
                "labels": list,
                "expected_revision": int,
                "reason": str,
            },
        )
        if expected_revision < 0:
            raise ValueError("expected revision must be nonnegative")
        payload["payload_hash"] = _digest(payload)
        for prior in state["history"]:
            if prior["id"] == correction_id:
                if prior != payload:
                    raise ValueError("correction replay conflict")
                return state
        if state["revision"] != expected_revision:
            raise ValueError("expected revision mismatch")
        case = next((c for c in data["cases"] if c["id"] == case_id), None)
        if case is None:
            raise ValueError("unknown case")
        _historical_case({**case, "labels": labels}, repo)
        state["history"].append(payload)
        state["revision"] += 1
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=state_path.parent,
                prefix=state_path.name + ".",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(state, stream, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, state_path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return state


def main() -> int:
    """Offline validation and reviewer-input export."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "export", "bind", "correct", "freshness"):
        command = commands.add_parser(name)
        command.add_argument("corpus", type=Path)
        command.add_argument("--repo", type=Path, required=True)
        if name != "validate":
            command.add_argument("--case", required=True)
        if name == "export":
            command.add_argument("--out", type=Path, required=True)
        elif name != "validate":
            command.add_argument("--state", type=Path, required=True)
        if name == "correct":
            command.add_argument("--id", required=True)
            command.add_argument("--labels", type=Path, required=True)
            command.add_argument("--expected-revision", type=int, required=True)
            command.add_argument("--reason", required=True)
        if name == "freshness":
            command.add_argument("--binding", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "validate":
            result = {"cases": len(load_corpus(args.corpus, args.repo)["cases"])}
        elif args.command == "export":
            result = export_case(args.corpus, args.repo, args.case, args.out)
        elif args.command == "bind":
            result = evidence_binding(args.corpus, args.repo, args.case, args.state)
        elif args.command == "correct":
            result = correct_labels(
                args.corpus,
                args.repo,
                args.state,
                args.id,
                args.case,
                _read_json(args.labels),
                expected_revision=args.expected_revision,
                reason=args.reason,
            )
        else:
            require_fresh_evidence(
                args.corpus,
                args.repo,
                args.case,
                args.state,
                _read_json(args.binding),
            )
            result = {"fresh": True}
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
