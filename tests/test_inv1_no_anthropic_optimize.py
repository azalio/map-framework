"""Guard test: VC1 [INV-1/HC-2/AC-10] — no anthropic import / no ANTHROPIC_API_KEY
in the optimization pipeline modules.

ST-002: covers proposer.py.
ST-009: extend MODULES list to add optimizer.py, viewer.py, apply_patcher.py
        once those modules exist.

Structure: a single parametrized test over a MODULES list so ST-009 can extend
it with one line per new module.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Module list — extend here in ST-009
# ---------------------------------------------------------------------------

_SKILLS_EVAL_ROOT = (
    Path(__file__).parent.parent / "src" / "mapify_cli" / "skills_eval"
)

MODULES: list[Path] = [
    _SKILLS_EVAL_ROOT / "proposer.py",
    _SKILLS_EVAL_ROOT / "description_optimizer.py",
    _SKILLS_EVAL_ROOT / "viewer.py",
    _SKILLS_EVAL_ROOT / "apply_patcher.py",
]


# ---------------------------------------------------------------------------
# Sentinel: guard against an empty MODULES list producing a vacuous green run
# ---------------------------------------------------------------------------


def test_modules_list_is_non_empty() -> None:
    """Discovery sentinel: MODULES must contain at least one entry."""
    assert MODULES, "MODULES list is empty — guard test would pass vacuously"
    for mod in MODULES:
        assert mod.exists(), f"Module listed in MODULES does not exist: {mod}"


# ---------------------------------------------------------------------------
# Parametrized guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module_path", MODULES, ids=[m.name for m in MODULES])
def test_vc1_no_anthropic_import(module_path: Path) -> None:
    """VC1 [INV-1/HC-2]: no 'import anthropic' / 'from anthropic' in module source."""
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(module_path))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "anthropic" not in (alias.name or ""), (
                    f"Found 'import anthropic' in {module_path.name}: {alias.name!r}"
                )
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            assert "anthropic" not in module_name, (
                f"Found 'from anthropic' import in {module_path.name}: "
                f"from {module_name!r}"
            )


@pytest.mark.parametrize("module_path", MODULES, ids=[m.name for m in MODULES])
def test_vc1_no_anthropic_api_key(module_path: Path) -> None:
    """VC1 [AC-10]: no ANTHROPIC_API_KEY env access in module source.

    Checks os.environ["ANTHROPIC_API_KEY"], os.environ.get("ANTHROPIC_API_KEY"),
    and os.getenv("ANTHROPIC_API_KEY") via AST walk over all Call/Subscript nodes.
    """
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(module_path))

    for node in ast.walk(tree):
        # os.environ["ANTHROPIC_API_KEY"]
        if isinstance(node, ast.Subscript) and (isinstance(node.value, ast.Attribute) and node.value.attr == "environ"):
            key_node = node.slice
            if isinstance(key_node, ast.Constant) and isinstance(
                key_node.value, str
            ):
                assert "ANTHROPIC_API_KEY" not in key_node.value, (
                    f"Found ANTHROPIC_API_KEY env subscript in {module_path.name}"
                )

        # os.getenv("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        if isinstance(node, ast.Call):
            func = node.func
            is_env_get = isinstance(func, ast.Attribute) and func.attr in (
                "getenv",
                "get",
            )
            if is_env_get and node.args:
                first_arg = node.args[0]
                if isinstance(first_arg, ast.Constant) and isinstance(
                    first_arg.value, str
                ):
                    assert "ANTHROPIC_API_KEY" not in first_arg.value, (
                        f"Found ANTHROPIC_API_KEY env read in {module_path.name}"
                    )
