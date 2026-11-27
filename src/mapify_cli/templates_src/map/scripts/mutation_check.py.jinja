"""Measure a bounded set of changes against selected pytest assertions in disposable copies."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import marshal
import math
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

from map_utils import atomic_write_text

HERE = Path(__file__).resolve().parent
PROBE = HERE / "mutation_pytest_probe.py"


def remaining(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError("Total mutation-check budget exhausted")
    return seconds


def git_env():
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def git(root, *args, timeout=30):
    return subprocess.run(["git", "--no-optional-locks", *args], cwd=root, env=git_env(),
                          capture_output=True, timeout=timeout, check=True).stdout


def relative(name):
    if not isinstance(name, str) or not name:
        raise ValueError("Expected a repository-relative path")
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] in (".map", ".git"):
        raise ValueError(f"Expected a product path inside the checkout: {name}")
    return path


def snapshot(root, deadline, destination=None):
    """Hash the same checkout bytes and modes that are copied into the baseline."""
    names = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z",
                "--", ".", ":(exclude,top).map", timeout=min(30, remaining(deadline)))
    digest = hashlib.sha256()
    for raw in sorted(set(names.split(b"\0")) - {b""}):
        remaining(deadline)
        path = root / os.fsdecode(raw)
        if path.parent.resolve() != path.parent:
            raise ValueError(f"Checkout path passes through a symlink: {path.relative_to(root)}")
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            continue  # A tracked deletion is absent from the candidate.
        target = destination / os.fsdecode(raw) if destination else None
        if target:
            target.parent.mkdir(parents=True, exist_ok=True)
        if stat.S_ISLNK(mode):
            link = os.readlink(path)
            depth = len(path.parent.relative_to(root).parts)
            for part in Path(link).parts:
                depth += -1 if part == ".." else 1
                if depth < 0:
                    raise ValueError(f"Link leaves the temporary checkout: {path.relative_to(root)}")
            if os.path.isabs(link) or not path.resolve().is_relative_to(root):
                raise ValueError(f"Link cannot be reproduced inside the snapshot: {path.relative_to(root)}")
            entry = os.fsencode(link)
            if target:
                target.symlink_to(link)
        elif stat.S_ISREG(mode):
            content = hashlib.sha256()
            with path.open("rb") as source:
                out = target.open("wb") if target else None
                try:
                    while block := source.read(1024 * 1024):
                        remaining(deadline)
                        content.update(block)
                        if out:
                            out.write(block)
                finally:
                    if out:
                        out.close()
            entry = content.digest()
            if target:
                target.chmod(stat.S_IMODE(mode))
        else:
            raise ValueError(f"Unsupported checkout entry: {path.relative_to(root)}")
        digest.update(raw + b"\0" + str(mode).encode() + b"\0" + hashlib.sha256(entry).digest())
    return digest.hexdigest()


def load_plan(path):
    data = path.read_bytes()
    plan = json.loads(data)
    if not isinstance(plan, dict) or not isinstance(plan.get("criterion"), str) or not plan["criterion"].strip():
        raise ValueError("A plan needs a behavior criterion")
    tests = plan.get("tests")
    if not isinstance(tests, list) or not tests:
        raise ValueError("Select at least one pytest file or node ID")
    for test in tests:
        if not isinstance(test, str):
            raise ValueError("Invalid pytest selector")
        relative(test.split("::", 1)[0])
    mutants = plan.get("mutations")
    if not isinstance(mutants, list):
        raise ValueError("mutations must be a list")
    for m in mutants:
        if not isinstance(m, dict) or any(not isinstance(m.get(k), str) for k in ("path", "before", "after", "effect")):
            raise ValueError("Each mutation needs path, before, after and effect strings")
        relative(m["path"])
        if not m["before"] or not m["effect"].strip():
            raise ValueError("Each mutation needs a nonempty original snippet and intended effect")
    return plan, hashlib.sha256(data).hexdigest()


def prepare(seed, case, protected):
    name = relative(case["path"])
    path = seed / name
    if path.resolve() != path or not path.is_file() or str(name) in protected:
        raise ValueError(f"Target must be an implementation file in the snapshot: {name}")
    raw = path.read_bytes()
    before, after = case["before"].encode(), case["after"].encode()
    if raw.count(before) != 1 or before == after:
        raise ValueError("The original snippet must match once and the replacement must change it")
    changed = raw.replace(before, after, 1)
    case["patch"] = "".join(difflib.unified_diff(raw.decode().splitlines(True), changed.decode().splitlines(True),
                                               fromfile="a/" + str(name), tofile="b/" + str(name)))
    equivalent = None
    if path.suffix == ".py":
        old_code = marshal.dumps(compile(raw, str(name), "exec", dont_inherit=True))
        new_code = marshal.dumps(compile(changed, str(name), "exec", dont_inherit=True))
        if new_code == old_code:
            equivalent = {"basis": "identical compiled Python code including source positions",
                          "sha256": hashlib.sha256(new_code).hexdigest(), "interpreter": sys.version}
    return name, changed, equivalent


def trial(seed, root, tests, timeout, deadline, replacement=None):
    start = time.monotonic()
    with tempfile.TemporaryDirectory(dir=seed.parent) as tmp:
        attempt = Path(tmp)
        tree = attempt / "repo"

        def copy_file(source, dest):
            remaining(deadline)
            return shutil.copy2(source, dest)

        shutil.copytree(seed, tree, symlinks=True, copy_function=copy_file)
        if replacement:
            name, changed = replacement
            target = tree / name
            mode = target.stat().st_mode
            target.chmod(mode | stat.S_IWUSR)
            target.write_bytes(changed)
            target.chmod(stat.S_IMODE(mode))
        evidence = attempt / "pytest.json"
        argv = [sys.executable, "-I", "-B", str(PROBE), str(evidence), str(root), *tests]
        env = git_env()
        env.pop("PYTEST_ADDOPTS", None)
        env.pop("PYTEST_PLUGINS", None)
        env.pop("PYTHONPATH", None)
        env["PWD"] = str(tree)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        # The shared supervisor owns and reaps the check's whole process group.
        with open(os.devnull, "rb") as lease:
            seconds = min(timeout, remaining(deadline))
            command = [sys.executable, str(HERE / "review_check_supervisor.py"), "supervise",
                       str(attempt), str(lease.fileno()), str(seconds), *argv]
            owner = subprocess.Popen(command, cwd=tree, env=env, stdin=subprocess.DEVNULL,
                                     start_new_session=True, pass_fds=(lease.fileno(),))
            try:
                owner.wait()
            except BaseException:
                owner.send_signal(signal.SIGINT)
                owner.wait()
                raise
        execution = json.loads((attempt / "supervisor.json").read_bytes())
        result = {"argv": argv, "execution": execution["status"], "exit_code": execution.get("exit_code"),
                  "duration_seconds": round(time.monotonic() - start, 3)}
        if execution["status"] == "success" and evidence.is_file():
            result.update(json.loads(evidence.read_bytes()))
            for filename in result["test_files"]:
                live = tree / filename
                original = seed / filename
                if not live.is_file() or not original.is_file() or live.read_bytes() != original.read_bytes():
                    result["problems"].append([filename, "test input changed", ""])
        if result["exit_code"] != 0 or result.get("problems") or not result.get("items"):
            for stream in ("stdout", "stderr"):
                logfile = attempt / stream
                if logfile.exists():
                    with logfile.open("rb") as handle:
                        handle.seek(max(0, logfile.stat().st_size - 2048))
                        result[stream] = handle.read().decode(errors="replace")
        return result


def verdict(run, items):
    seen = run.get("items", {})
    if (run["execution"] != "success" or not seen or seen.keys() != items or run["problems"]):
        return "inconclusive"
    if run["exit_code"] == 0 and all(s == "passed" for s in seen.values()) and not run["assertions"]:
        return "passed"
    failures = {node for node, state in seen.items() if state == "failed"}
    if (run["exit_code"] == 1 and failures and failures == {a[0] for a in run["assertions"]}
            and all(s in ("failed", "passed") for s in seen.values())):
        return "detected"
    return "inconclusive"


def measure(report, seed, root, limit, timeout, deadline, save):
    tests = report["tests"]
    if not report["mutations"]:
        return "no_measurement"
    for test in tests:
        selected = seed / relative(test.split("::", 1)[0])
        if not selected.is_file() or not selected.resolve().is_relative_to(seed):
            raise ValueError(f"Test file is missing from snapshot: {test}")
    baseline = report["baseline"] = trial(seed, root, tests, timeout, deadline)
    nodes = baseline.get("items", {}).keys()
    if verdict(baseline, nodes) != "passed":
        return "baseline_failed"
    save()
    for case in report["mutations"][:limit]:
        remaining(deadline)
        try:
            name, changed, equivalent = prepare(seed, case, baseline["test_files"])
        except (OSError, ValueError, SyntaxError) as exc:
            case.update(outcome="invalid", reason=str(exc))
            save()
            continue
        case["outcome"] = "inconclusive"
        save()  # Publish the exact patch before executing it.
        runs = case["runs"] = [trial(seed, root, tests, timeout, deadline, (name, changed))]
        save()
        result = verdict(runs[0], nodes)
        if result == "passed":
            case["outcome"] = "equivalent" if equivalent else "survived"
            if equivalent:
                case["equivalence"] = equivalent
        elif result == "detected":
            # Replay clean and mutant with independent working copies before crediting the assertion.
            clean = trial(seed, root, tests, timeout, deadline)
            runs.append(clean)
            save()
            again = trial(seed, root, tests, timeout, deadline, (name, changed))
            runs.append(again)
            def witnesses(run):
                return {(node, line) for node, line, _ in run.get("assertions", [])}

            confirmed = (not equivalent and verdict(clean, nodes) == "passed"
                         and verdict(again, nodes) == "detected" and witnesses(runs[0]) == witnesses(again))
            case["outcome"] = "detected" if confirmed else "inconclusive"
        else:
            case["outcome"] = "inconclusive"
        save()
    outcomes = {c["outcome"] for c in report["mutations"]}
    if "survived" in outcomes:
        return "gaps"
    if "detected" in outcomes and outcomes <= {"detected", "equivalent"}:
        return "all_detected"
    return "incomplete"


def check(args):
    root = Path.cwd().resolve()
    if Path(os.fsdecode(git(root, "rev-parse", "--show-toplevel").rstrip(b"\n"))).resolve() != root:
        raise ValueError("Run from the root of the candidate checkout")
    deadline = time.monotonic() + args.total_timeout
    if args.check_report:
        report = json.loads(args.check_report.read_bytes())
        if not isinstance(report, dict) or any(not isinstance(report.get(k), str)
                                               for k in ("plan", "plan_sha256", "root", "snapshot", "status")):
            raise ValueError("The report has no complete input snapshot")
        plan_hash = hashlib.sha256(Path(report["plan"]).read_bytes()).hexdigest()
        current = (str(root) == report["root"] and plan_hash == report["plan_sha256"]
                   and snapshot(root, deadline) == report["snapshot"])
        return {"current": current, "status": report["status"]}, 0 if current else 1

    plan, plan_hash = load_plan(args.plan)
    folder = root / ".map" / "mutation-checks"
    if folder.resolve() != folder:
        raise ValueError("Mutation report directory must be inside the checkout")
    folder.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(dir=folder)) / "report.json"
    report = {"root": str(root), "plan": str(args.plan.resolve()), "plan_sha256": plan_hash,
              "report": str(output), "criterion": plan["criterion"], "tests": plan["tests"],
              "command": [sys.executable, "-m", "pytest", "-q", "-o", "addopts=", "-p", "no:cacheprovider", "--", *plan["tests"]],
              "limit": args.limit, "timeout": args.timeout, "total_timeout": args.total_timeout,
              "snapshot": None, "baseline": None, "status": "running",
              "mutations": [{**{k: m[k] for k in ("path", "before", "after", "effect")}, "outcome": "not_run"}
                            for m in plan["mutations"]]}

    def save():
        counts = Counter(c["outcome"] for c in report["mutations"])
        report["summary"] = ", ".join(f"{count} {outcome}" for outcome, count in sorted(counts.items())) or "No mutations"
        survivors = [f"{m['path']}: {m['effect']}" for m in report["mutations"] if m["outcome"] == "survived"]
        if survivors:
            report["summary"] += ". Surviving changes: " + ", ".join(survivors)
        atomic_write_text(output, json.dumps(report, indent=2) + "\n")

    save()
    try:
        with tempfile.TemporaryDirectory() as temporary:
            seed = Path(temporary).resolve() / "snapshot"
            if seed.is_relative_to(root):
                raise ValueError("The temporary directory must be outside the candidate checkout")
            seed.mkdir()
            report["snapshot"] = snapshot(root, deadline, seed)
            report["status"] = measure(report, seed, root, args.limit, args.timeout, deadline, save)
            if (snapshot(root, deadline) != report["snapshot"]
                    or hashlib.sha256(args.plan.read_bytes()).hexdigest() != plan_hash):
                report["status"] = "stale"
    except KeyboardInterrupt:
        report["status"] = "interrupted"
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        report.update(status="incomplete", reason=str(exc))
    save()
    return report, 0 if report["status"] == "all_detected" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", nargs="?", type=Path)
    parser.add_argument("--check-report", type=Path)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--total-timeout", type=float, default=180)
    args = parser.parse_args()
    if bool(args.plan) == bool(args.check_report):
        parser.error("Choose a plan or --check-report")
    if args.limit < 1 or not all(math.isfinite(v) and v > 0 for v in (args.timeout, args.total_timeout)):
        parser.error("Budgets must be finite and positive")
    try:
        value, code = check(args)
    except (KeyError, OSError, ValueError, subprocess.SubprocessError) as exc:
        value, code = {"current": False, "error": str(exc)}, 2
    if "summary" in value:
        print(f"{value['status']}: {value['summary']}", file=sys.stderr)
    print(json.dumps(value, indent=2))
    return code


if __name__ == "__main__":
    def interrupt(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    sys.exit(main())
