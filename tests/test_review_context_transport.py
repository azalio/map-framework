"""Parent-mediated review context is lossless, bounded and role/snapshot fenced."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mapify_cli import app
from tests.test_review_trusted_policy import runner

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src/mapify_cli/templates/map/scripts"
SOURCE = "".join(f"LINE_{i:04d} = 'original source content {i:04d}'\n" for i in range(220))


def git(root, *args):
    """Run literal Git arguments in an isolated repository."""
    return subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=True).stdout.strip()


def make_seed(root, count):
    """Create a real branch with individually small changed sources."""
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.invalid")
    (root / ".gitignore").write_text(".map/\n")
    for index in range(count):
        (root / f"source_{index:03d}.py").write_text(SOURCE)
    git(root, "add", ".")
    git(root, "commit", "-qm", "base")
    git(root, "checkout", "-qb", "feature")
    for path in root.glob("source_*.py"):
        path.write_text(SOURCE.replace("LINE_0000", "LINE_0000_CHANGED"))
    git(root, "commit", "-qam", "small changes")
    return root


@pytest.fixture(scope="module")
def seed(tmp_path_factory):
    """Keep aggregate overflow and fresh installs on a genuinely large source inventory."""
    return make_seed(tmp_path_factory.mktemp("review-context-seed"), 36)


@pytest.fixture(scope="module")
def small_seed(tmp_path_factory):
    """Identity/tamper tests need the same Git contract, not dozens of unrelated sources."""
    return make_seed(tmp_path_factory.mktemp("review-context-small-seed"), 3)


@pytest.fixture
def repo(seed, small_seed, tmp_path, monkeypatch, request):
    """Keep each admission and immutable context independent from other tests."""
    root = tmp_path / "repo"
    large_cases = {
        "test_aggregate_context_roundtrip_preserves_prompt_inventory_and_all_sources",
        "test_manifest_itself_is_chunkable_and_abandoned_context_is_unavailable",
    }
    source = seed if request.node.originalname in large_cases else small_seed
    shutil.copytree(source, root)
    monkeypatch.chdir(root)
    admission = runner.begin_review_run(branch="feature", round_id="context-round", provider="codex")
    assert admission["status"] == "success", admission
    bundle = runner.create_review_bundle(branch="feature")
    assert bundle["status"] == "success", bundle
    return root, admission, bundle


def request(entry, resource="manifest", offset=0):
    """Use only the opaque identifiers supplied by the prompt builder."""
    return {"type": "context_request", "context_id": entry["context_transport"]["context_id"],
            "resource_id": resource, "offset": offset}


def fetch(entry, reviewer, resource="manifest", chunk_bytes=65536):
    """Reassemble exact UTF-8 bytes using the protocol's offsets and digests."""
    chunks = []
    offset = 0
    while True:
        result = runner.serve_review_context(reviewer, json.dumps(request(entry, resource, offset)),
                                             "context-round", branch="feature", chunk_bytes=chunk_bytes)
        assert result["status"] == "context_response", result
        assert len(json.dumps(result, ensure_ascii=True).encode()) + 1 <= runner.REVIEW_PROMPT_MAX_BYTES
        raw = result["content"].encode("utf-8")
        assert hashlib.sha256(raw).hexdigest() == result["chunk_sha256"]
        assert result["offset"] == offset
        assert result["next_offset"] == offset + len(raw)
        chunks.append(raw)
        if result["eof"]:
            combined = b"".join(chunks)
            assert len(combined) == result["total_bytes"]
            assert hashlib.sha256(combined).hexdigest() == result["sha256"]
            return combined.decode("utf-8")
        assert result["next_offset"] > offset
        offset = result["next_offset"]


def test_undecodable_git_filename_roundtrips_through_context(tmp_path, monkeypatch):
    """A deleted Git path can contain bytes that the current filesystem cannot create."""
    monkeypatch.chdir(tmp_path)
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    Path(".gitignore").write_text(".map/\n")
    git(tmp_path, "add", ".gitignore")
    raw_name = b"deleted-\xff.py"
    name = os.fsdecode(raw_name)
    oid = subprocess.run(["git", "hash-object", "-w", "--stdin"], input=b"value = 1\n",
                         capture_output=True, check=True).stdout.decode().strip()
    git(tmp_path, "update-index", "--add", "--cacheinfo", f"100644,{oid},{name}")
    git(tmp_path, "commit", "-qm", "base with byte filename")
    git(tmp_path, "checkout", "-qb", "feature")
    assert runner.begin_review_run(branch="feature", round_id="context-round", provider="codex")["status"] == "success"
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    built = runner.build_review_prompts(branch="feature")
    assert built["status"] == "success", built
    entry = built["prompts"]["monitor"]
    manifest = json.loads(fetch(entry, "monitor"))
    inventory = json.loads(fetch(entry, "monitor", "inventory"))
    assert name in inventory["snapshot"]["required_files"]
    resource = next(key for key, item in manifest["resources"].items() if item.get("path") == name)
    source = json.loads(fetch(entry, "monitor", resource))
    assert os.fsencode(source["path"]) == raw_name
    assert source["base_content"] == "value = 1\n"
    assert source["current_content"] == ""


def test_aggregate_context_roundtrip_preserves_prompt_inventory_and_all_sources(repo, monkeypatch):
    """The full pre-transport prompt and admitted source evidence survive without clipping."""
    root, admission, bundle = repo
    assert Path(bundle["bundle_path_md"]).stat().st_size > runner.REVIEW_PROMPT_MAX_BYTES
    with monkeypatch.context() as patch:
        patch.setattr(runner, "_prepare_review_context", lambda *args, **kwargs: {"status": "success"})
        patch.setattr(runner, "_review_prompt_size_error", lambda *args: None)
        original = runner.build_review_prompts(branch="feature")["prompts"]["monitor"]["prompt"]
    result = runner.build_review_prompts(branch="feature")
    assert result["status"] == "success", result
    assert all(len(entry["prompt"].encode()) < 30_000 for entry in result["prompts"].values())
    entry = result["prompts"]["monitor"]
    assert entry["truncated"] is False and entry["clipped_sections"] == []
    manifest = json.loads(fetch(entry, "monitor"))
    assert fetch(entry, "monitor", "prompt") == original
    inventory = json.loads(fetch(entry, "monitor", "inventory"))
    assert inventory["snapshot"]["required_files"] == admission["required_files"]
    assert inventory["snapshot"]["target"] == admission["target"]
    assert inventory["attribution"]["base"] == git(root, "rev-parse", "main")
    source_resources = {key: value for key, value in manifest["resources"].items() if key.startswith("source_")}
    assert len(source_resources) == 36
    for key, metadata in source_resources.items():
        source = json.loads(fetch(entry, "monitor", key))
        assert source["base_content"] == SOURCE
        assert source["current_content"] == (root / source["path"]).read_text()
        assert source["line_mapping"]
        assert hashlib.sha256(source["base_content"].encode()).hexdigest() == metadata["base_sha256"]
        assert hashlib.sha256(source["current_content"].encode()).hexdigest() == metadata["current_sha256"]
    ledger = json.loads((root / ".map/feature/review-verdict-ledger.json").read_text())
    assert ledger["convergence"]["rounds"][-1]["capability"]["status"] == "unverified"
    assert not ledger.get("code_approval", {}).get("approved", False)


@pytest.mark.parametrize("builder,reviewer", [("build_review_prompts", "monitor"),
    ("build_role_review_prompts", "maintainer"), ("build_adversarial_review_prompts", "blind")])
def test_all_builders_deliver_large_unicode_diff_without_message_overflow(repo, builder, reviewer):
    """UTF-8 and JSON escaping count toward the unchanged per-message cap."""
    del repo
    diff = "diff --git a/x b/x\n+" + ('🙂\\"\x00\n' * 80_000) + "END_OF_DIFF"
    result = getattr(runner, builder)(branch="feature", git_diff_text=diff)
    assert result["status"] == "success", result
    entry = result["prompts"][reviewer]
    original = fetch(entry, reviewer, "prompt")
    assert len(original.encode()) > runner.REVIEW_PROMPT_MAX_BYTES
    assert diff in original
    assert "END_OF_DIFF" in original
    assert len(entry["prompt"].encode()) < 30_000


def test_role_access_and_peer_independence_survive_transport(repo):
    """Blind cannot fetch repository inventory or another role's context; edge cannot see spec."""
    root, _, _ = repo
    (root / ".map/feature/review-agent-maintainer.json").write_text('{"private_peer":"PEER_SECRET"}')
    result = runner.build_adversarial_review_prompts(branch="feature", spec_text="SPEC_SECRET")
    prompts = result["prompts"]
    blind = json.loads(fetch(prompts["blind"], "blind"))
    assert set(blind["resources"]) == {"prompt"}
    assert "SPEC_SECRET" not in fetch(prompts["blind"], "blind", "prompt")
    assert "SPEC_SECRET" not in fetch(prompts["edge_case"], "edge_case", "prompt")
    assert "SPEC_SECRET" in fetch(prompts["acceptance"], "acceptance", "prompt")
    for entry, resource in [(prompts["blind"], "inventory"), (prompts["acceptance"], "prompt")]:
        denied = runner.serve_review_context("blind", json.dumps(request(entry, resource)),
                                             "context-round", branch="feature")
        assert denied["status"] == "error"
        assert "SPEC_SECRET" not in json.dumps(denied)
    for role in ("blind", "edge_case", "acceptance"):
        assert "PEER_SECRET" not in fetch(prompts[role], role, "prompt")


@pytest.mark.parametrize("resource", ["manifest", "prompt", "source_000000"])
def test_tampered_or_symlinked_resource_is_never_delivered(repo, resource):
    """Content hashes and path ownership are checked before emitting source text."""
    root, _, _ = repo
    entry = runner.build_review_prompts(branch="feature")["prompts"]["monitor"]
    context_id = entry["context_transport"]["context_id"]
    manifest = json.loads(fetch(entry, "monitor"))
    digest = context_id if resource == "manifest" else manifest["resources"][resource]["sha256"]
    path = root / ".map/feature/review-context-objects" / digest
    original = path.read_bytes()
    path.write_bytes(b"TAMPERED_SECRET")
    result = runner.serve_review_context("monitor", json.dumps(request(entry, resource)),
                                         "context-round", branch="feature")
    assert result["status"] == "error" and "TAMPERED_SECRET" not in json.dumps(result)
    path.unlink()
    outside = root.parent / "outside"
    outside.write_bytes(original)
    path.symlink_to(outside)
    result = runner.serve_review_context("monitor", json.dumps(request(entry, resource)),
                                         "context-round", branch="feature")
    assert result["status"] == "error"


@pytest.mark.parametrize("mutation", ["round", "source", "bundle", "policy"])
def test_stale_context_is_rejected(repo, mutation):
    """A request cannot cross an admission or silently read a changed source snapshot."""
    root, _, _ = repo
    entry = runner.build_review_prompts(branch="feature")["prompts"]["monitor"]
    round_id = "context-round"
    if mutation == "round":
        round_id = "other-round"
    elif mutation == "source":
        (root / "source_000.py").write_text("changed after admission\n")
    elif mutation == "bundle":
        ledger = json.loads((root / ".map/feature/review-verdict-ledger.json").read_text())
        artifact = ledger["convergence"]["rounds"][-1]["bundle_receipt"]["artifact"]
        (root / ".map/feature" / artifact).write_text("{}")
    else:
        (root / ".map/config.yaml").write_text("minimality: strict\n")
    result = runner.serve_review_context("monitor", json.dumps(request(entry)), round_id, branch="feature")
    assert result["status"] == "error", result


@pytest.mark.parametrize("field,value", [("offset", -1), ("offset", True), ("offset", 10**12),
    ("offset", "0"), ("resource_id", "../../secret"), ("context_id", "../secret"), ("extra", 1)])
def test_invalid_request_fails_closed(repo, field, value):
    """No caller-controlled path or ambiguous offset reaches the object store."""
    del repo
    entry = runner.build_review_prompts(branch="feature")["prompts"]["monitor"]
    payload = request(entry)
    payload[field] = value
    result = runner.serve_review_context("monitor", json.dumps(payload), "context-round", branch="feature")
    assert result["status"] == "error", result


def test_intermediate_request_is_not_captured_or_counted_as_final_review(repo):
    """Context delivery leaves ledger/capture state intact; existing final validation still applies."""
    root, _, _ = repo
    assert runner.capture_review_output("monitor", '{"verdict":"approved","issues":[]}',
                                        "context-round", branch="feature")["status"] == "success"
    entry = runner.build_review_prompts(branch="feature")["prompts"]["monitor"]
    directory = root / ".map/feature"
    before = {name: (directory / name).read_bytes() for name in ("review-verdict-ledger.json", "review-agent-monitor.json")}
    payload = json.dumps(request(entry))
    assert runner.serve_review_context("monitor", payload, "context-round", branch="feature")["status"] == "context_response"
    assert runner.capture_review_output("monitor", payload, "context-round", branch="feature")["status"] == "error"
    assert {name: (directory / name).read_bytes() for name in before} == before
    for final in ('{"verdict":"approved","issues":[]}', "malformed JSON", "Lean already. Ship."):
        assert runner.serve_review_context("monitor", final, "context-round", branch="feature") == {"status": "not_context_request"}


def test_mid_codepoint_offset_is_rejected(repo):
    """UTF-8 offsets cannot start inside a multi-byte character."""
    del repo
    entry = runner.build_review_prompts(branch="feature", review_preferences="🙂")["prompts"]["monitor"]
    original = fetch(entry, "monitor", "prompt").encode()
    offset = original.index("🙂".encode()) + 1
    result = runner.serve_review_context("monitor", json.dumps(request(entry, "prompt", offset)),
                                         "context-round", branch="feature")
    assert result["status"] == "error"


def test_parent_chunk_override_cannot_exceed_the_transport_limit(repo):
    """Output capture tuning cannot raise the cap or stop UTF-8 progress."""
    del repo
    entry = runner.build_review_prompts(branch="feature")["prompts"]["monitor"]
    for chunk_bytes in (0, 3, True, "1024", 65537):
        result = runner.serve_review_context("monitor", json.dumps(request(entry)),
                                             "context-round", branch="feature", chunk_bytes=chunk_bytes)
        assert result["status"] == "error", result


def test_manifest_itself_is_chunkable_and_abandoned_context_is_unavailable(repo):
    """A large inventory uses the same protocol and cannot outlive its admission."""
    del repo
    entry = runner.build_review_prompts(branch="feature")["prompts"]["monitor"]
    manifest = json.loads(fetch(entry, "monitor", chunk_bytes=2048))
    assert len(manifest["resources"]) == 38
    abandoned = runner.abandon_review_round("context-round", reason="source changed", branch="feature")
    assert abandoned["status"] == "success", abandoned
    result = runner.serve_review_context("monitor", json.dumps(request(entry)), "context-round", branch="feature")
    assert result["status"] == "error"


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_fresh_install_routes_intermediate_context_before_final_validation(seed, tmp_path, monkeypatch, provider):
    """Installed CLI and provider instructions preserve same-agent continuation and final gating."""
    root = tmp_path / provider
    shutil.copytree(seed, root)
    monkeypatch.chdir(root)
    installed = CliRunner().invoke(app, ["init", ".", "--force", "--no-git", "--mcp", "none", "--provider", provider])
    assert installed.exit_code == 0, installed.output
    git(root, "add", ".")
    git(root, "commit", "-qm", "install provider")
    script = root / ".map/scripts/map_step_runner.py"

    def invoke(*args, payload=None):
        """Run the actual installed entry point, including stdin protocol parsing."""
        completed = subprocess.run([sys.executable, str(script), *args], input=payload,
                                   text=True, capture_output=True, timeout=60, check=False)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        return json.loads(completed.stdout)

    assert invoke("begin_review_run", "--provider", provider, "--round-id", "installed-round")["status"] == "success"
    assert invoke("create_review_bundle")["status"] == "success"
    built = invoke("build_review_prompts")
    assert built["status"] == "success", built
    entry = built["prompts"]["monitor"]
    assert len(entry["prompt"].encode()) < 30_000
    binding = invoke("bind_review_context", "--reviewer", "monitor", "--agent-id", "installed-native-agent",
                     "--context-id", entry["context_transport"]["context_id"], "--round-id", "installed-round")
    assert binding["status"] == "context_pending"
    response = invoke("serve_review_context", "--reviewer", "monitor", "--round-id", "installed-round", "--chunk-bytes", "1024",
                      "--session-id", binding["session_id"], "--agent-id", "installed-native-agent",
                      payload=json.dumps(request(entry)))
    assert response["status"] == "context_response"
    assert len(response["content"].encode()) <= 1024
    assert len(json.dumps(response).encode()) < 10_000
    assert response["context_id"] == entry["context_transport"]["context_id"]
    acknowledged = invoke("ack_review_context", "--session-id", binding["session_id"],
                          "--agent-id", "installed-native-agent", "--round-id", "installed-round",
                          payload=json.dumps(response))
    assert acknowledged["status"] == "context_pending"
    assert invoke("review_context_status", "--session-id", binding["session_id"],
                  "--round-id", "installed-round") == acknowledged
    assert invoke("serve_review_context", "--reviewer", "monitor", "--round-id", "installed-round",
                  payload='{"verdict":"approved","issues":[]}') == {"status": "not_context_request"}
    skill = root / (".claude/skills/map-review/SKILL.md" if provider == "claude" else ".agents/skills/map-review/SKILL.md")
    instructions = skill.read_text()
    assert instructions.index("### Step A.2a:") < instructions.index("### Step A.2b:")
    assert "serve_review_context" in instructions
    continuation = "Task(resume=<same agent_id>" if provider == "claude" else "followup_task(target=<same agent_id>"
    assert continuation in (skill.parent / "review-reference.md").read_text()
