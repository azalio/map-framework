"""One installed plan checks two Git checkouts and exercises the client against the server."""

import json
import os
import subprocess
import sys


def test_installed_feature_keeps_work_open_until_client_reads_server(tmp_path):
    server, client = tmp_path / "server", tmp_path / "client"

    def run(root, *args, check=True):
        result = subprocess.run(args, cwd=root, capture_output=True, text=True, check=False,
                                env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)})
        if check:
            assert result.returncode == 0, (args, result.stdout, result.stderr)
        return result

    for repo in (server, client):
        repo.mkdir()
        run(repo, "git", "init", "-q", "-b", "feature")
        run(repo, "git", "config", "user.name", "Feature Test")
        run(repo, "git", "config", "user.email", "test@example.invalid")
        (repo / ".gitignore").write_text(".map/\n__pycache__/\n")
    run(server, sys.executable, "-m", "mapify_cli", "init", ".", "--force", "--provider", "codex", "--no-git", "--mcp", "none")
    (server / "api.py").write_text("print('{}')\n")
    (client / "client.py").write_text("def read(data):\n    return data['old']\n")
    (server / "compat.py").write_text(
        "import json, subprocess, sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path('../client').resolve()))\n"
        "from client import read\n"
        "payload = subprocess.check_output([sys.executable, 'api.py'])\n"
        "assert read(json.loads(payload)) == 2\n"
    )
    for repo in (server, client):
        run(repo, "git", "add", ".")
        run(repo, "git", "commit", "-qm", "baseline")
    api_check = [sys.executable, "-B", "-c", "import api"]
    client_check = [sys.executable, "-B", "-c", "from client import read"]
    task = {"id": "ST-001", "title": "Read API version", "aag_contract": "client -> read(api()) -> version",
            "affected_files": ["api.py", "../client/client.py"], "dependencies": [],
            "validation_criteria": ["VC1 [AC-1]: client reads the version returned by the server"],
            "expected_diff_size": "small", "one_logical_step": True, "concern_type": "api",
            "repository_checks": {
                ".": {"base": run(server, "git", "rev-parse", "HEAD").stdout.strip(), "command": api_check},
                "../client": {"base": run(client, "git", "rev-parse", "HEAD").stdout.strip(), "command": client_check}},
            "joint_check": [sys.executable, "-B", "compat.py"]}
    branch = server / ".map/feature"
    branch.mkdir(exist_ok=True)
    (branch / "blueprint.json").write_text(json.dumps({
        "summary": "Expose the API version", "hard_constraints": [], "soft_constraints": [],
        "coverage_map": {"AC-1": "ST-001"}, "subtasks": [task]}))
    (branch / "task_plan_feature.md").write_text("### ST-001: Read API version\n- **Status:** pending\n")

    def cli(script, *args, check=True):
        result = run(server, sys.executable, "-B", str(server / ".map/scripts" / script), *args, check=check)
        assert result.stdout, result.stderr
        return json.loads(result.stdout)

    def workflow(*args):
        return cli("map_orchestrator.py", *args, "--branch", "feature", check=False)

    def verify(*args, check=True):
        return cli("map_step_runner.py", "feature_check", "feature", "ST-001", *args, check=check)

    plan = cli("map_step_runner.py", "validate_blueprint_contract")
    assert plan["valid"], plan
    assert workflow("resume_from_plan")["status"] == "success"
    assert workflow("set_plan_approved", "true")["plan_approved"]
    (server / "api.py").write_text("print('{\"version\": 2}')\n")
    local = verify("--repository", ".")
    assert local["repositories"]["."]["status"] == "passed", local
    assert local["repositories"]["../client"]["status"] == "pending"
    assert not (client / ".map/scripts/map_step_runner.py").exists()
    assert not workflow("get_next_step")["is_complete"]
    scoped = cli("map_step_runner.py", "validate_mutation_boundary", "feature", "ST-001", "--repository", "../client")
    assert scoped["expected"] == ["client.py"] and scoped["actual"] == []
    approved = (branch / "blueprint.json").read_bytes()
    refresh = cli("map_step_runner.py", "refresh_blueprint_affected_files", "feature", "ST-001")
    assert refresh["current"] == task["affected_files"]
    assert (branch / "blueprint.json").read_bytes() == approved
    assert workflow("mark_subtask_complete", "ST-001", "--reason", "server done")["status"] == "error"
    assert verify("--joint", check=False)["status"] != "complete"

    (client / "client.py").write_text("def read(data):\n    return data['wrong']\n")
    assert verify("--repository", "../client")["repositories"]["../client"]["status"] == "passed"
    assert verify("--joint", check=False)["status"] == "error"
    (client / "client.py").write_text("def read(data):\n    return data['version']\n")
    status = verify()
    assert status["repositories"]["."]["status"] == "passed" and status["status"] == "pending"
    assert verify("--repository", "../client")["status"] == "pending"
    assert verify("--joint")["status"] == "complete"
    assert workflow("mark_subtask_complete", "ST-001", "--reason", "compatibility verified")["workflow_complete"]
    assert workflow("get_next_step")["is_complete"]
    (server / "api.py").write_text("print('{}')\n")
    assert not workflow("get_next_step")["is_complete"]
    cli("map_step_runner.py", "write_run_health_report", "map-efficient")
    assert json.loads((branch / "run_health_report.json").read_bytes())["terminal_status"] == "pending"
