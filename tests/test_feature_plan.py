import json
import subprocess

import pytest

from tests.test_map_step_runner import _blueprint_with_requiredness, map_step_runner


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          check=True).stdout.strip()


@pytest.fixture
def plan(tmp_path, monkeypatch):
    server, client = tmp_path / "server", tmp_path / "client"
    for root in (server, client):
        root.mkdir()
        git(root, "init", "-qb", "main")
        (root / "README.md").write_text(root.name)
        git(root, "add", "README.md")
        git(root, "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-qm", root.name)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(server))
    monkeypatch.chdir(server)
    blueprint = _blueprint_with_requiredness()
    task = blueprint["subtasks"][0]
    task.update(affected_files=["README.md", "../client/README.md"],
                repository_checks={
                    ".": {"base": git(server, "rev-parse", "HEAD"), "command": ["make", "test"]},
                    "../client": {"base": git(client, "rev-parse", "HEAD"), "command": ["make", "check"]},
                }, joint_check=["make", "integration"])
    return server, client, blueprint


def validate(root, blueprint):
    path = root / "blueprint.json"
    path.write_text(json.dumps(blueprint))
    return map_step_runner.validate_blueprint_contract(str(path), branch="feature")


def test_feature_plan_projects_all_approved_paths(plan):
    from map_feature_plan import feature_projects

    server, client, blueprint = plan
    task = blueprint["subtasks"][0]
    (server / "link").symlink_to(client / "README.md")
    literal = "  notes\twith spaces  "
    task["affected_files"] += ["link", str(client / literal)]
    result = validate(server, blueprint)
    assert result["valid"], result
    assert not any("cross-repo affected_files" in warning for warning in result["warnings"])
    projects = feature_projects(server, task)
    assert projects == {
        ".": {**task["repository_checks"]["."], "root": server.resolve(), "files": ["README.md", "link"]},
        "../client": {**task["repository_checks"]["../client"], "root": client.resolve(),
                      "files": sorted(["README.md", literal])},
    }


@pytest.mark.parametrize("defect", [
    "missing-checks", "missing-joint", "empty-command", "moving-base", "other-base", "empty-scope",
    "unregistered-file", "link-escape", "traversal", "same-root", "nested-alias", "subdirectory",
    "nested-checkout", "undeclared-nested-checkout",
])
def test_feature_plan_rejects_incomplete_or_ambiguous_scope(plan, defect):
    server, client, blueprint = plan
    task = blueprint["subtasks"][0]
    configs = task["repository_checks"]
    if defect == "missing-checks":
        del task["repository_checks"]
        del task["joint_check"]
    elif defect == "missing-joint":
        del task["joint_check"]
    elif defect == "empty-command":
        configs["."]["command"] = []
    elif defect == "moving-base":
        configs["."]["base"] = "HEAD"
    elif defect == "other-base":
        configs["."]["base"] = configs["../client"]["base"]
    elif defect == "empty-scope":
        task["affected_files"] = ["README.md"]
    elif defect == "unregistered-file":
        task["affected_files"].append("../third/README.md")
    elif defect == "link-escape":
        (server / "link").symlink_to(client, target_is_directory=True)
        task["affected_files"].append("link/README.md")
    elif defect == "traversal":
        task["affected_files"].append("inside/../README.md")
    elif defect == "same-root":
        configs[str(client)] = configs["../client"]
    elif defect == "nested-alias":
        (server / "client-link").symlink_to(client, target_is_directory=True)
        configs["client-link"] = configs.pop("../client")
    elif defect == "subdirectory":
        (client / "subdir").mkdir()
        configs["../client/subdir"] = configs.pop("../client")
    elif defect in {"nested-checkout", "undeclared-nested-checkout"}:
        inner = server / "nested"
        git(server, "clone", "-q", str(client), str(inner))
        if defect == "undeclared-nested-checkout":
            del task["repository_checks"]
            del task["joint_check"]
            task["affected_files"] = ["README.md", "nested/README.md"]
        else:
            task["affected_files"].append("nested/README.md")
    result = validate(server, blueprint)
    assert not result["valid"], defect
    assert any("ST-001" in error for error in result["errors"]), result
    if defect == "missing-checks":
        assert any("repository_checks" in error and "joint_check" in error for error in result["errors"])


def test_feature_scope_keeps_only_proven_neighbor_changes(plan):
    from map_orchestrator import StepState

    server, _, blueprint = plan
    directory = server / ".map" / "feature"
    directory.mkdir(parents=True)
    other = "work [approved].txt"
    stray = "outside.txt"
    neighbor = {"id": "ST-002", "affected_files": [str(server / other)]}
    blueprint["subtasks"].append(neighbor)
    blueprint["subtasks"].append({"affected_files": [str(server / stray)]})
    (directory / "blueprint.json").write_text(json.dumps(blueprint))

    def scope():
        return map_step_runner.validate_mutation_boundary("feature", "ST-001", repository=".")

    for name in (other, stray):
        (server / name).write_text("neighbor\n")
    git(server, "add", "--", other, stray)
    git(server, "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-qm", "other work")
    commit = git(server, "rev-parse", "HEAD")
    assert set(scope()["unexpected"]) == {other, stray}
    state = StepState()
    state.record_subtask_result("ST-002", [other, stray], "valid", commit_sha=commit)
    state.save(directory / "step_state.json")
    report = scope()
    assert report["unexpected"] == [stray]
    assert report["attributed_files"] == {other: commit}
    actor = map_step_runner.detect_actor_files_changed_mismatch("feature", "ST-001", [other])
    assert actor["declared_not_written"] == [other]
    (server / other).write_text("additional edit\n")
    assert set(scope()["unexpected"]) == {other, stray}
    git(server, "add", "--", other)
    (server / other).write_text("neighbor\n")  # Worktree matches the approved commit, index differs.
    assert set(scope()["unexpected"]) == {other, stray}
    git(server, "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-qm", "unrecorded edit")
    (server / other).write_text("additional edit\n")
    assert set(scope()["unexpected"]) == {other, stray}


def test_actor_changed_files_checks_each_repository(plan):
    server, client, blueprint = plan
    directory = server / ".map" / "feature"
    directory.mkdir(parents=True)
    literal = " draft "
    blueprint["subtasks"][0]["affected_files"].append("../client/" + literal)
    (directory / "blueprint.json").write_text(json.dumps(blueprint))

    def report(names):
        return map_step_runner.detect_actor_files_changed_mismatch("feature", "ST-001", names)

    (client / "README.md").write_text("new client\n")
    git(client, "add", "README.md")
    git(client, "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-qm", "client")
    (client / literal).write_text("draft\n")
    sibling = "../client/README.md"
    first = report(["README.md", sibling, "../client/" + literal])
    assert first["declared_not_written"] == ["README.md"]
    assert set(first["actual"]) == {sibling, "../client/" + literal}
    (server / "README.md").write_text("new server\n")
    second = report(["README.md", str(client / "README.md")])
    assert second["status"] == "ok" and not second["status_mismatch"]
    assert set(second["actual"]) == {"README.md", sibling, "../client/" + literal}
