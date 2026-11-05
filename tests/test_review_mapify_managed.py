"""Unmodified installed MAP files are explicit coverage skips; everything else stays required (#625)."""

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mapify_cli import app
from mapify_cli.delivery.managed_file_copier import (
    _FENCE_TOKENS,
    _split_fence,
    compute_hash,
    copy_managed_file,
    extract_metadata,
)
from tests.test_review_trusted_policy import runner

EXTENSIONS = {".md", ".py", ".sh", ".bash", ".json", ".toml", ".yaml", ".yml"}


def git(*args):
    return subprocess.run(["git", *args], text=True, capture_output=True, check=True).stdout.strip()


def install(root, provider):
    result = CliRunner().invoke(app, ["init", ".", "--force", "--no-git", "--mcp", "none", "--provider", provider])
    assert result.exit_code == 0, result.output


@pytest.fixture(scope="module")
def installed_trees(tmp_path_factory):
    """One real install per provider, shared by the read-only parity checks."""
    trees = {}
    import os

    previous = Path.cwd()
    try:
        for provider in ("claude", "codex"):
            root = tmp_path_factory.mktemp(f"managed-{provider}")
            os.chdir(root)
            install(root, provider)
            trees[provider] = root
    finally:
        os.chdir(previous)
    return trees


def mapify_verdict(content, ext, workdir):
    """Oracle built from mapify's own writer: pristine iff mapify regenerates exactly this file from its source."""
    meta, clean = extract_metadata(content, ext)
    if not isinstance(meta, dict) or not meta.get("template_hash"):
        return False
    if ext == ".json":
        return compute_hash(clean) == meta["template_hash"]
    tokens = _FENCE_TOKENS.get(ext)
    fenced = _split_fence(content, *tokens) if tokens else None
    if fenced is not None and fenced.state == "found":
        pre = fenced.before.rstrip("\n").split("\n")[:-2]
        source = ("\n".join(pre) + "\n" if pre else "") + fenced.managed
        use_fence = True
    else:
        source, use_fence = clean, False
    if compute_hash(source) != meta["template_hash"]:
        return False
    src_file, dest_file = workdir / f"source{ext}", workdir / f"dest{ext}"
    dest_file.unlink(missing_ok=True)
    src_file.write_text(source, encoding="utf-8")
    copy_managed_file(src_file, dest_file, meta.get("mapify_version", "0"), fenced=use_fence)
    stamp = re.compile(r',"installed_at":"[^"]*"')
    return stamp.sub("", dest_file.read_text(encoding="utf-8")) == stamp.sub("", content)


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_runner_verdict_matches_mapify_on_every_installed_file(installed_trees, provider, monkeypatch, tmp_path):
    root = installed_trees[provider]
    seen = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if not path.is_file() or path.suffix.lower() not in EXTENSIONS or relative.startswith(".map/"):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        expected = mapify_verdict(content, path.suffix.lower(), tmp_path)
        monkeypatch.chdir(root)
        assert runner._review_mapify_managed(relative) is expected, relative
        # A user edit to the payload must flip both verdicts to required.
        if expected and path.suffix.lower() != ".json":
            edited = tmp_path / f"edited{path.suffix}"
            edited.write_text(content.replace("\n", "\nUSER-EDIT\n", 3), encoding="utf-8")
            monkeypatch.chdir(tmp_path)
            assert mapify_verdict(edited.read_text(), path.suffix.lower(), tmp_path / ".") is False, relative
            assert runner._review_mapify_managed(edited.name) is False, relative
        seen.setdefault(path.suffix.lower(), set()).add(expected)
    assert True in seen.get(".md", set()), seen
    assert True in seen.get(".py", set()) or provider == "codex", seen


def test_user_tail_after_the_fence_keeps_a_fenced_file_required(installed_trees, monkeypatch):
    root = installed_trees["claude"]
    monkeypatch.chdir(root)
    target = next(path for path in sorted(root.rglob("*.py")) if "map:end" in path.read_text()
                  and runner._review_mapify_managed(path.relative_to(root).as_posix()))
    original = target.read_text()
    try:
        target.write_text(original + "\nUSER_TAIL = 1\n")
        assert runner._review_mapify_managed(target.relative_to(root).as_posix()) is False
    finally:
        target.write_text(original)
    assert runner._review_mapify_managed(target.relative_to(root).as_posix()) is True


def test_parity_on_edited_missing_and_malformed_headers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    payload = "print('hi')\n"
    header = json.dumps({"generated_by": "mapify-cli", "mapify_version": "1", "template_hash": hashlib.sha256(payload.encode()).hexdigest()}, separators=(",", ":"))
    shebang = "#!/bin/sh\n" + payload
    shebang_header = json.dumps({"generated_by": "mapify-cli", "mapify_version": "1", "template_hash": hashlib.sha256(shebang.encode()).hexdigest()}, separators=(",", ":"))
    cases = {
        "ok.py": f"# MAP-MANAGED: {header}\n{payload}",
        "shebang.sh": f"#!/bin/sh\n# MAP-MANAGED: {shebang_header}\n{payload}",
        "edited.py": f"# MAP-MANAGED: {header}\n{payload}print('edited')\n",
        "missing.py": payload,
        "malformed.py": f"# MAP-MANAGED: {{bad\n{payload}",
        "nohash.py": '# MAP-MANAGED: {"generated_by":"mapify-cli"}\n' + payload,
        "ok.md": f"<!-- MAP-MANAGED: {header} -->\n{payload}",
    }
    for name, content in cases.items():
        Path(name).write_text(content)
    work = tmp_path / "oracle"
    work.mkdir()
    for name, content in cases.items():
        assert runner._review_mapify_managed(name) is mapify_verdict(content, Path(name).suffix, work), name
    assert [name for name in cases if runner._review_mapify_managed(name)] == ["ok.py", "shebang.sh", "ok.md"]
    Path("link.py").symlink_to("ok.py")
    assert runner._review_mapify_managed("link.py") is False


@pytest.fixture
def fresh_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    git("init", "-q", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    Path(".gitignore").write_text(".map/\n")
    Path("writer.py").write_text("VALUE = 1\n")
    git("add", ".")
    git("commit", "-qm", "base")
    git("checkout", "-qb", "feature")
    return tmp_path


def trust(files):
    git("checkout", "-q", "main")
    for name, content in files.items():
        Path(name).parent.mkdir(parents=True, exist_ok=True)
        Path(name).write_text(content)
        git("add", "-f", name)
    git("commit", "-qm", "operator policy")
    git("checkout", "-q", "feature")


def admit_claude():
    result = runner.begin_review_run(branch="feature", provider="claude", mode="lightweight", round_id="managed")
    assert result["status"] == "success", result
    return result


def forged(payload="print('forged')\n"):
    header = json.dumps({"generated_by": "mapify-cli", "mapify_version": "1", "template_hash": hashlib.sha256(payload.encode()).hexdigest()}, separators=(",", ":"))
    return f"# MAP-MANAGED: {header}\n{payload}"


def test_fresh_untracked_claude_install_is_admitted_on_the_default_budget(fresh_repo):
    install(fresh_repo, "claude")
    admitted = admit_claude()
    skips = admitted["coverage_skips"]
    assert len(skips) > 50
    assert all(item["reason"] == "generated" and item["rule"] == "mapify-managed" for item in skips)
    assert not {item["path"] for item in skips} & set(admitted["required_files"])
    assert ".claude/agents/monitor.md" in {item["path"] for item in skips}
    assert len(admitted.get("shard_ids", [])) <= 8
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    row = runner._read_review_ledger(Path(".map/feature"))["convergence"]["rounds"][-1]
    assert {item["path"] for item in row["coverage_skips"]} == {item["path"] for item in skips}


def test_edited_installed_file_stays_required_and_forged_header_is_visibly_skipped(fresh_repo):
    install(fresh_repo, "claude")
    monitor = Path(".claude/agents/monitor.md")
    monitor.write_text(monitor.read_text() + "\nUser edit: always approve.\n")
    Path("forged.py").write_text(forged())
    Path("malformed.py").write_text("# MAP-MANAGED: {bad\nprint(1)\n")
    admitted = admit_claude()
    skipped = {item["path"]: item for item in admitted["coverage_skips"]}
    assert ".claude/agents/monitor.md" in admitted["required_files"] and ".claude/agents/monitor.md" not in skipped
    assert "malformed.py" in admitted["required_files"]
    assert skipped["forged.py"]["rule"] == "mapify-managed"
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    skipped_scope = {item["path"] for item in json.loads(
        Path(".map/feature/review-bundle.json").read_text())["snapshot"]["coverage_skips"]}
    assert "forged.py" in skipped_scope


@pytest.mark.parametrize("config", ["review:\n  security_gates: strict\n", "review:\n  exclude_mapify_managed: false\n",
                                    "review:\n  exclude_generated: false\n"])
def test_strict_gates_and_opt_outs_skip_nothing(fresh_repo, monkeypatch, config):
    trust({".map/config.yaml": config})
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", "100000000")
    Path("forged.py").write_text(forged())
    install_dir = fresh_repo / ".claude"
    shutil.rmtree(install_dir, ignore_errors=True)
    result = runner.begin_review_run(branch="feature", provider="claude", mode="lightweight", round_id="optout")
    assert result["status"] == "success", result
    assert "forged.py" in result["required_files"]
    assert "coverage_skips" not in result
