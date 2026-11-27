"""Record pytest phase, test identity and assertion location for a mutation trial."""

import ast
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import pytest


class Evidence:
    def __init__(self):
        self.items = {}
        self.test_files = set()
        self.problems = []
        self.assertions = []
        self.children = []
        self.unobserved_child = False
        self.launch = threading.local()

    def audit(self, event, args):
        if event in {"os.system", "os.spawn", "os.posix_spawn", "os.fork", "os.forkpty"} and not getattr(self.launch, "managed", False):
            self.unobserved_child = True

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_protocol(self, item, nextitem):
        self.children = []
        self.unobserved_child = False
        original = subprocess.Popen.__init__

        def start(process, *args, **kwargs):
            self.launch.managed = True
            try:
                original(process, *args, **kwargs)
            finally:
                self.launch.managed = False
            self.children.append(process)

        with patch.object(subprocess.Popen, "__init__", start):
            yield

    def pytest_collection_finish(self, session):
        if session.config.inipath is not None:
            self.test_files.add(str(session.config.inipath.resolve()))
        for item in session.items:
            self.items[item.nodeid] = "collected"
            self.test_files.add(str(item.path.resolve()))
        for plugin in session.config.pluginmanager.get_plugins():
            filename = getattr(plugin, "__file__", None)
            if isinstance(filename, str):
                self.test_files.add(str(Path(filename).resolve()))

    def pytest_fixture_setup(self, fixturedef):
        filename = getattr(getattr(fixturedef.func, "__code__", None), "co_filename", None)
        if filename:
            self.test_files.add(str(Path(filename).resolve()))

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        result = yield
        report = result.get_result()
        if report.when == "call":
            self.items[item.nodeid] = report.outcome
        if report.skipped or hasattr(report, "wasxfail"):
            self.problems.append([item.nodeid, report.when, "skipped or marked xfail"])
        elif report.failed:
            error = call.excinfo
            if report.when == "call" and error and error.type is AssertionError:
                if self.unobserved_child or any(child.poll() != 0 for child in self.children):
                    self.problems.append([item.nodeid, report.when, "child process failed or its exit was unverified"])
                    return
                frame = error.traceback[-1]
                line = frame.lineno + 1
                path = item.path.resolve()
                if Path(frame.path).resolve() == path and any(
                    isinstance(node, ast.Assert) and node.lineno <= line <= node.end_lineno
                    for node in ast.walk(ast.parse(path.read_bytes()))
                ):
                    self.assertions.append([item.nodeid, line, str(error.value)[:512]])
                    return
            self.problems.append([item.nodeid, report.when, str(error.typename) if error else "failure"])

    def pytest_collectreport(self, report):
        if report.failed:
            self.problems.append([report.nodeid, "collection", "error"])


def main():
    output, original, *targets = sys.argv[1:]
    sys.pycache_prefix = str(Path(output).parent / "cache")
    cwd = Path.cwd()
    entries = [str(p) for p in (cwd / "src", cwd) if p.is_dir()]
    sys.path[:0] = entries
    os.environ["PYTHONPATH"] = os.pathsep.join(entries)
    evidence = Evidence()
    sys.addaudithook(evidence.audit)
    code = pytest.main(["-q", "-o", "addopts=", "-p", "no:cacheprovider", "--", *targets], plugins=[evidence])
    # An editable installation can otherwise make pytest exercise the user's copy.
    root = Path(original)
    for module in tuple(sys.modules.values()):
        filename = getattr(module, "__file__", None)
        if isinstance(filename, str):
            path = Path(filename).resolve()
            if path.is_relative_to(root) and not path.is_relative_to(sys.prefix) and path != Path(__file__).resolve():
                evidence.problems.append(["import", "outside snapshot", str(path.relative_to(root))])
                break
    files = [str(Path(p).relative_to(cwd)) for p in evidence.test_files if Path(p).is_relative_to(cwd)]
    Path(output).write_text(json.dumps({"items": evidence.items, "test_files": sorted(files),
                                       "assertions": evidence.assertions, "problems": evidence.problems}))
    return code


if __name__ == "__main__":
    sys.exit(main())
