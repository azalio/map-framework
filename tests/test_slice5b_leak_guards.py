"""Kill-switch / off-ramp leak-guard proof suite (updated for Slice 6, ST-008).

Five non-tautological guards proving MAP_EFFICIENT_SEQUENTIAL_ONLY=1 (the
global kill-switch) suppresses all concurrent behavior — equivalent to the
old default-off premise but now pinned to the off-ramp rather than the default:

(a) prompt confinement guard — fanout instruction tokens exist ONLY inside the
    prose-gated 'Slice 5b' section, NOT in default/sequential paragraphs.
(b) monkeypatch-fail guard — concurrent runner verbs do NOT fire under the kill-switch.
(c) AST/static-import guard — sequential walker + flag-false branch contain NO
    references to concurrent runner verbs.
(d) no-telemetry guard — no parallelism.json is created when the kill-switch is set.
(e) kill-switch baseline — get_wave_step returns dispatch_mode=='sequential' with
    the kill-switch reason code; concurrency_enabled==False.

Slice 6 change: the DEFAULT config now routes to concurrent for parallel-ready plans.
The kill-switch (MAP_EFFICIENT_SEQUENTIAL_ONLY=1) is the new behavioral gate these
guards protect — they go RED if the kill-switch leaks concurrency.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path
from typing import ClassVar

import pytest

# ---------------------------------------------------------------------------
# Suppress bytecode pollution in generated trees (learned rule).
# ---------------------------------------------------------------------------
sys.dont_write_bytecode = True

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_PATH = (
    _REPO_ROOT / "src" / "mapify_cli" / "templates" / "map" / "scripts"
)
_ORCHESTRATOR_PATH = _SCRIPTS_PATH / "map_orchestrator.py"
_RUNNER_PATH = _SCRIPTS_PATH / "map_step_runner.py"
_REFERENCE_PATH = (
    _REPO_ROOT / ".claude" / "skills" / "map-efficient" / "efficient-reference.md"
)

# ---------------------------------------------------------------------------
# Add scripts dir so "import map_step_runner" inside map_orchestrator resolves.
# ---------------------------------------------------------------------------
if str(_SCRIPTS_PATH) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_PATH))

import map_orchestrator  # pyright: ignore[reportMissingImports]

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def branch_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Minimal .map/<branch>/ directory with MAP_EFFICIENT_SEQUENTIAL_ONLY=1.

    Slice 6: defaults are now ON. This fixture engages the kill-switch so the
    guards protect the off-ramp path (not the old default-off path).
    """
    branch = "test-leak-guards"
    map_branch_dir = tmp_path / ".map" / branch
    map_branch_dir.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAP_EFFICIENT_SEQUENTIAL_ONLY", "1")
    monkeypatch.setattr(map_orchestrator, "get_branch_name", lambda: branch)
    return branch


def _write_parallel_blueprint(branch: str) -> str:
    """Write a blueprint in the correct list-of-dicts format and call set_waves.

    Returns the branch name.  The blueprint has two waves:
      wave 0: [ST-001]         (single, sequential)
      wave 1: [ST-002, ST-003] (parallel group)
    """
    bp_file = Path(f".map/{branch}/blueprint.json")
    blueprint = {
        "subtasks": [
            {"id": "ST-001", "dependencies": [], "affected_files": ["models.py"]},
            {"id": "ST-002", "dependencies": ["ST-001"], "affected_files": ["views.py"]},
            {"id": "ST-003", "dependencies": ["ST-001"], "affected_files": ["urls.py"]},
        ]
    }
    bp_file.write_text(json.dumps(blueprint), encoding="utf-8")
    map_orchestrator.set_waves(branch, str(bp_file))
    return branch


@pytest.fixture
def branch_with_waves(branch_workspace: str) -> str:
    """branch_workspace extended with parallel waves."""
    return _write_parallel_blueprint(branch_workspace)


# ===========================================================================
# Guard (a): Prompt confinement guard
# ===========================================================================

class TestGuardA_PromptConfinement:
    """Fanout instruction tokens must appear ONLY inside the prose-gated Slice 5b
    section of efficient-reference.md, NOT in default/sequential paragraphs.

    What break turns this red:
      - If "one assistant message" (the core fanout instruction) leaks outside the
        gated section into the sequential-dispatch docs, the test fires.
      - If "emit all N Task" (the canonical fanout verb) leaks outside the gate, the
        second test fires.
      - Guard is non-tautological: we first prove the tokens ARE inside the gate, so
        a vacuous pass (tokens missing from both inside and outside) is impossible.
    """

    def _extract_gated_section(self, content: str) -> tuple[str, str]:
        """Split content into (inside_gated_section, rest_of_doc).

        The gated section starts at the '### Concurrent Actor dispatch — **Slice 5b**'
        heading and ends at the next '###' heading at the same level (or EOF).
        """
        start_match = re.search(
            r"^### Concurrent Actor dispatch.*Slice 5b.*$",
            content,
            re.MULTILINE,
        )
        assert start_match is not None, (
            "Slice 5b gated section heading not found in efficient-reference.md. "
            "The gate marker was removed — guard (a) cannot validate confinement."
        )
        start = start_match.start()

        next_h3 = re.search(r"^### ", content[start_match.end():], re.MULTILINE)
        if next_h3 is None:
            end = len(content)
        else:
            end = start_match.end() + next_h3.start()

        inside = content[start:end]
        outside = content[:start] + content[end:]
        return inside, outside

    def test_vc1a_one_assistant_message_inside_gated_section(self) -> None:
        """'one assistant message' must appear inside the Slice 5b gated section.

        Non-tautological: proves the token IS in the gate so the outside-check
        cannot pass vacuously.
        """
        if not _REFERENCE_PATH.exists():
            pytest.skip(f"Reference file not found: {_REFERENCE_PATH}")

        content = _REFERENCE_PATH.read_text(encoding="utf-8")
        inside, _ = self._extract_gated_section(content)

        assert "one assistant message" in inside, (
            "Expected 'one assistant message' not found inside the Slice 5b gated "
            "section. Was the fanout instruction removed from the gate?"
        )

    def test_vc1a_one_assistant_message_not_in_sequential_docs(self) -> None:
        """'one assistant message' must NOT appear outside the Slice 5b gate.

        Failure scenario: if this token leaks into a sequential-dispatch paragraph,
        operators following default config get concurrent instructions — HC-1 violation.
        """
        if not _REFERENCE_PATH.exists():
            pytest.skip(f"Reference file not found: {_REFERENCE_PATH}")

        content = _REFERENCE_PATH.read_text(encoding="utf-8")
        _, outside = self._extract_gated_section(content)

        assert "one assistant message" not in outside, (
            "Fanout instruction 'one assistant message' found OUTSIDE the Slice 5b "
            "gated section — it leaked into sequential/default instructions (HC-1)."
        )

    def test_vc1a_emit_all_n_task_inside_not_outside(self) -> None:
        """'emit all N `Task' (the canonical fanout verb) must be inside, not outside.

        The exact phrase from the reference: 'emit all N `Task(actor)` calls'.
        Failure scenario: fanout instruction bleeds into the 5a sequential section.
        """
        if not _REFERENCE_PATH.exists():
            pytest.skip(f"Reference file not found: {_REFERENCE_PATH}")

        content = _REFERENCE_PATH.read_text(encoding="utf-8")
        inside, outside = self._extract_gated_section(content)

        # The literal phrase in the reference file; N is the word not a digit.
        fanout_phrase = "emit all N"

        # Non-tautological: prove the phrase IS inside the gate.
        assert fanout_phrase in inside, (
            f"Expected fanout phrase {fanout_phrase!r} not found inside the Slice 5b "
            "gated section — was the fanout instruction renamed or removed?"
        )

        # Now prove it does NOT appear outside the gate.
        assert fanout_phrase not in outside, (
            f"Fanout phrase {fanout_phrase!r} found OUTSIDE the Slice 5b gate. "
            "Fanout instructions must be confined to the gated section only."
        )


# ===========================================================================
# Guard (b): Monkeypatch-fail guard
# ===========================================================================

class TestGuardB_MonkeypatchFail:
    """Concurrent runner verbs must NOT be called when the kill-switch is set.

    What break turns this red:
      - If compute_dispatch_gate (or get_wave_step) calls begin_wave_group /
        abort_wave_group / run_concurrent_wave / record_dispatch_actual when
        MAP_EFFICIENT_SEQUENTIAL_ONLY=1, the monkeypatched stub raises
        AssertionError and the test fails — catching the kill-switch leak.
    """

    _CONCURRENT_VERBS: ClassVar[list] = [
        "begin_wave_group",
        "abort_wave_group",
        "record_dispatch_actual",
        "run_concurrent_wave",
    ]

    def _make_failing_stub(self, name: str):  # type: ignore[return]
        """Return a def-style callable that raises AssertionError if called."""
        def _stub(*_args: object, **_kw: object) -> None:
            del _args, _kw  # suppress pyright unused-parameter; del valid in def
            raise AssertionError(
                f"Concurrent runner verb {name!r} must NOT be called "
                "when MAP_EFFICIENT_SEQUENTIAL_ONLY=1 (kill-switch engaged)."
            )
        return _stub

    def test_vc1b_no_concurrent_verbs_fire_on_kill_switch(
        self,
        branch_with_waves: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Under MAP_EFFICIENT_SEQUENTIAL_ONLY=1 none of the four concurrent
        runner verbs fire when get_wave_step / compute_dispatch_gate are called.

        Stubs raise AssertionError on any call → a kill-switch leak is
        immediately visible as a test failure.
        """
        import importlib
        try:
            msr = importlib.import_module("map_step_runner")
        except ModuleNotFoundError:
            msr = None

        for verb in self._CONCURRENT_VERBS:
            stub = self._make_failing_stub(verb)
            # Patch on orchestrator module (covers any top-level alias).
            if hasattr(map_orchestrator, verb):
                monkeypatch.setattr(map_orchestrator, verb, stub)
            # Patch on the runner module if loaded.
            if msr is not None and hasattr(msr, verb):
                monkeypatch.setattr(msr, verb, stub)

        # Call get_wave_step (calls compute_dispatch_gate internally).
        result = map_orchestrator.get_wave_step(branch_with_waves)

        # Also call compute_dispatch_gate directly.
        gate = map_orchestrator.compute_dispatch_gate(branch_with_waves, Path("."))

        # Confirm sequential path taken (stubs had no effect = no verb fired).
        assert result["dispatch_mode"] == "sequential", (
            f"Expected sequential dispatch_mode, got: {result['dispatch_mode']!r}"
        )
        assert gate["dispatch_mode"] == "sequential", (
            f"Expected sequential gate, got: {gate['dispatch_mode']!r}"
        )


# ===========================================================================
# Guard (c): AST/static-import guard
# ===========================================================================

class TestGuardC_ASTImport:
    """Sequential walker + flag-false branch of orchestrator must not reference
    the concurrent runner verbs that live in map_step_runner.py.

    What break turns this red:
      - If get_next_step or the flag-false early-return branch of
        compute_dispatch_gate contains a Call/Attribute referencing any of the
        four concurrent verbs, the test fails.
      - Non-tautological: we first prove the verbs ARE present in the runner file
        (not just absent from the orchestrator by accident of deletion), so a
        vacuous pass from orphaned names is impossible.
    """

    _CONCURRENT_VERBS = frozenset([
        "run_concurrent_wave",
        "begin_wave_group",
        "abort_wave_group",
        "record_dispatch_actual",
    ])

    def _collect_call_names(self, node: ast.AST) -> set[str]:
        """Collect all Call function-names and Attribute names from an AST subtree."""
        names: set[str] = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                func = child.func
                if isinstance(func, ast.Name):
                    names.add(func.id)
                elif isinstance(func, ast.Attribute):
                    names.add(func.attr)
            elif isinstance(child, ast.Attribute):
                names.add(child.attr)
        return names

    def _extract_function(
        self, tree: ast.Module, func_name: str
    ) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == func_name
            ):
                return node
        return None

    def _extract_flag_false_body(
        self, func_node: ast.FunctionDef
    ) -> list[ast.stmt]:
        """Extract the HC-1 early-return branch: 'if not flag_on: return {...}'.

        Looks for the first If whose test is a UnaryOp(Not, ...) and whose body
        contains a Return — this is the flag-false short-circuit in compute_dispatch_gate.
        """
        for node in ast.walk(func_node):
            if not isinstance(node, ast.If):
                continue
            test = node.test
            is_not_expr = isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)
            has_return = any(isinstance(s, ast.Return) for s in node.body)
            if is_not_expr and has_return:
                return node.body
        return []

    def test_vc1c_ast_parse_succeeds_functions_exist(self) -> None:
        """Orchestrator parses cleanly and contains the expected functions.

        Non-tautological baseline: if the parse fails or functions are absent, the
        sequential-path absence checks would be vacuously true.
        """
        if not _ORCHESTRATOR_PATH.exists():
            pytest.skip(f"Orchestrator not found: {_ORCHESTRATOR_PATH}")

        src = _ORCHESTRATOR_PATH.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(_ORCHESTRATOR_PATH))

        assert self._extract_function(tree, "get_next_step") is not None, (
            "get_next_step missing from parsed orchestrator — AST guard is vacuous."
        )
        assert self._extract_function(tree, "compute_dispatch_gate") is not None, (
            "compute_dispatch_gate missing from parsed orchestrator — AST guard is vacuous."
        )

    def test_vc1c_verbs_present_in_runner_not_on_sequential_orchestrator_paths(
        self,
    ) -> None:
        """The concurrent verbs ARE defined in map_step_runner.py (non-tautological)
        but do NOT appear in get_next_step or the flag-false branch of
        compute_dispatch_gate in map_orchestrator.py.

        Failure scenarios:
          - Verbs absent from runner entirely → 'present in runner' assert fires (vacuous guard).
          - Verbs referenced on the sequential orchestrator paths → leak assert fires.
        """
        if not _ORCHESTRATOR_PATH.exists():
            pytest.skip(f"Orchestrator not found: {_ORCHESTRATOR_PATH}")
        if not _RUNNER_PATH.exists():
            pytest.skip(f"Runner not found: {_RUNNER_PATH}")

        # --- Non-tautological: verify concurrent verbs ARE defined in the runner ---
        runner_src = _RUNNER_PATH.read_text(encoding="utf-8")
        runner_tree = ast.parse(runner_src, filename=str(_RUNNER_PATH))

        verbs_in_runner = {
            node.name
            for node in ast.walk(runner_tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in self._CONCURRENT_VERBS
        }
        # record_dispatch_actual lives in mapify_cli.parallelism_observability, not the runner,
        # so only check the three runner-defined verbs here.
        runner_verbs = self._CONCURRENT_VERBS - {"record_dispatch_actual"}
        missing_runner_verbs = runner_verbs - verbs_in_runner
        assert not missing_runner_verbs, (
            f"Concurrent verbs {missing_runner_verbs} not defined in map_step_runner.py. "
            "The AST guard would be vacuous. Were the verbs renamed?"
        )

        # --- Now check the orchestrator sequential paths ---
        orch_src = _ORCHESTRATOR_PATH.read_text(encoding="utf-8")
        orch_tree = ast.parse(orch_src, filename=str(_ORCHESTRATOR_PATH))

        # Check get_next_step (sequential walker).
        gns = self._extract_function(orch_tree, "get_next_step")
        assert gns is not None
        gns_names = self._collect_call_names(gns)
        leaked_in_gns = self._CONCURRENT_VERBS & gns_names
        assert not leaked_in_gns, (
            f"Concurrent verbs {leaked_in_gns} referenced in get_next_step "
            "(sequential walker). Sequential path must not call concurrent primitives (HC-1)."
        )

        # Check compute_dispatch_gate's flag-false early-return branch.
        cdg = self._extract_function(orch_tree, "compute_dispatch_gate")
        assert cdg is not None
        assert isinstance(cdg, ast.FunctionDef)  # narrow type
        flag_false_body = self._extract_flag_false_body(cdg)
        assert flag_false_body, (
            "Could not locate the flag-false early-return branch in compute_dispatch_gate. "
            "The HC-1 short-circuit structure may have changed."
        )
        ff_names = self._collect_call_names(
            ast.Module(body=flag_false_body, type_ignores=[])
        )
        leaked_in_ff = self._CONCURRENT_VERBS & ff_names
        assert not leaked_in_ff, (
            f"Concurrent verbs {leaked_in_ff} referenced in compute_dispatch_gate "
            "flag-false branch. The HC-1 short-circuit must return immediately with "
            "no concurrency primitives (HC-1)."
        )


# ===========================================================================
# Guard (d): No-telemetry guard
# ===========================================================================

class TestGuardD_NoTelemetry:
    """record_dispatch_actual must not create parallelism.json when the kill-switch is set.

    What break turns this red:
      - If any code path under MAP_EFFICIENT_SEQUENTIAL_ONLY=1 creates parallelism.json
        (which record_dispatch_actual writes only on the DISPATCH_OUTCOME_CONCURRENT_OBSERVED
        path), the file-existence assertion fires — the kill-switch leaked concurrency.
    """

    def test_vc1d_no_parallelism_json_created_on_kill_switch_path(
        self,
        branch_with_waves: str,
    ) -> None:
        """Running get_wave_step + compute_dispatch_gate under MAP_EFFICIENT_SEQUENTIAL_ONLY=1
        must NOT create any parallelism.json file.
        """
        expected_telemetry = Path(f".map/{branch_with_waves}/parallelism.json")
        map_dir = Path(f".map/{branch_with_waves}")

        # Capture existing json files BEFORE the default-config flow.
        before: set[Path] = set(map_dir.rglob("*.json"))

        # Execute the default-config flow (return values unused — we assert on the
        # filesystem side effect, i.e. that no telemetry file is written).
        map_orchestrator.get_wave_step(branch_with_waves)
        map_orchestrator.compute_dispatch_gate(branch_with_waves, Path("."))

        # parallelism.json must not be created.
        assert not expected_telemetry.exists(), (
            "parallelism.json was created under default config. "
            "record_dispatch_actual must be a no-op on the sequential path (HC-1)."
        )

        # Broad check: no new parallelism-related json files appeared.
        after: set[Path] = set(map_dir.rglob("*.json"))
        new_files = after - before
        parallelism_new = {p for p in new_files if "parallelism" in p.name}
        assert not parallelism_new, (
            f"New parallelism-related file(s) created under MAP_EFFICIENT_SEQUENTIAL_ONLY=1: "
            f"{parallelism_new}. Only step_state.json should be updated."
        )


# ===========================================================================
# Guard (e): Default-off baseline
# ===========================================================================

class TestGuardE_KillSwitchBaseline:
    """Under MAP_EFFICIENT_SEQUENTIAL_ONLY=1, gate and wave step must be sequential
    with the kill-switch reason code.

    What break turns this red:
      - If the kill-switch is ignored and the concurrent path executes, the
        dispatch_mode assertion fires.
      - If the reason code drifts from WAVE_REASON_SEQUENTIAL_ONLY_ENV, the reason
        assertion fires — catching a silent rename or path change.
      - concurrency_enabled==False is a corollary: also asserted.

    Slice 6 change: the DEFAULT is now concurrent for parallel-ready plans.
    The kill-switch is the behavioral gate these guards prove.
    """

    def test_vc1e_compute_dispatch_gate_sequential_on_kill_switch(
        self, branch_with_waves: str
    ) -> None:
        """compute_dispatch_gate returns dispatch_mode=='sequential' and the
        kill-switch reason code when MAP_EFFICIENT_SEQUENTIAL_ONLY=1.

        The reason must equal WAVE_REASON_SEQUENTIAL_ONLY_ENV — not a fallback from
        later gate steps — proving the kill-switch short-circuit is the path that fires.
        """
        gate = map_orchestrator.compute_dispatch_gate(branch_with_waves, Path("."))

        assert gate["dispatch_mode"] == "sequential", (
            f"compute_dispatch_gate returned {gate['dispatch_mode']!r} under kill-switch. "
            "Expected 'sequential' (MAP_EFFICIENT_SEQUENTIAL_ONLY=1)."
        )
        assert gate["reason"] == map_orchestrator.WAVE_REASON_SEQUENTIAL_ONLY_ENV, (
            f"Gate reason {gate['reason']!r} != "
            f"WAVE_REASON_SEQUENTIAL_ONLY_ENV "
            f"({map_orchestrator.WAVE_REASON_SEQUENTIAL_ONLY_ENV!r}). "
            "Kill-switch must fire before any concurrency probe."
        )

    def test_vc1e_get_wave_step_concurrency_disabled_on_kill_switch(
        self, branch_with_waves: str
    ) -> None:
        """get_wave_step returns concurrency_enabled==False and dispatch_mode==
        'sequential' when MAP_EFFICIENT_SEQUENTIAL_ONLY=1.
        """
        result = map_orchestrator.get_wave_step(branch_with_waves)

        assert result["dispatch_mode"] == "sequential", (
            f"get_wave_step returned dispatch_mode={result['dispatch_mode']!r}. "
            "Expected 'sequential' under MAP_EFFICIENT_SEQUENTIAL_ONLY=1."
        )
        assert result.get("concurrency_enabled") is False, (
            f"get_wave_step returned concurrency_enabled="
            f"{result.get('concurrency_enabled')!r}. Must be False under kill-switch."
        )

    def test_vc1e_get_wave_step_reason_is_kill_switch_code(
        self, branch_with_waves: str
    ) -> None:
        """The reason in get_wave_step must be WAVE_REASON_SEQUENTIAL_ONLY_ENV when
        MAP_EFFICIENT_SEQUENTIAL_ONLY=1.

        Failure scenario: if compute_dispatch_gate's wiring changed and the reason
        was overwritten or swallowed, a different (or missing) reason code appears.
        """
        result = map_orchestrator.get_wave_step(branch_with_waves)

        assert result.get("reason") == map_orchestrator.WAVE_REASON_SEQUENTIAL_ONLY_ENV, (
            f"get_wave_step reason={result.get('reason')!r} != "
            f"WAVE_REASON_SEQUENTIAL_ONLY_ENV={map_orchestrator.WAVE_REASON_SEQUENTIAL_ONLY_ENV!r}. "
            "The kill-switch reason code is the stable contract under MAP_EFFICIENT_SEQUENTIAL_ONLY=1."
        )

    def test_vc1e_select_execution_strategy_concurrency_not_allowed_on_kill_switch(
        self, branch_with_waves: str
    ) -> None:
        """select_execution_strategy returns concurrency_allowed==False when
        MAP_EFFICIENT_SEQUENTIAL_ONLY=1 (kill-switch engaged).

        This covers the 'concurrency_allowed==False' clause of guard (e).
        Slice 6: the DEFAULT config no longer implies False here — the kill-switch does.
        """
        strategy = map_orchestrator.select_execution_strategy(branch_with_waves, Path("."))

        assert strategy.get("concurrency_allowed") is False, (
            f"select_execution_strategy returned concurrency_allowed="
            f"{strategy.get('concurrency_allowed')!r}. "
            "Must be False under MAP_EFFICIENT_SEQUENTIAL_ONLY=1 (kill-switch)."
        )
