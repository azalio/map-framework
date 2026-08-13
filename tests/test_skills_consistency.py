"""
Consistency tests: declared requires-* in skill-rules.json ⊇ scanner-detected deps.

VC1: per-skill, declared requires-* ⊇ scanner-detected; under-declaration FAILS.
VC2: GREEN on all 14 existing skills (map-state git detected + declared; others empty).
VC3: each requires-* sub-block validates vs SKILL_REQUIREMENTS_SCHEMA; no dangling
     requires-skills targets.
VC4: reuses skill_rules fixture; scanner ignores os.getenv(x, default) and comments.
"""

from __future__ import annotations

import ast
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from mapify_cli.schemas import (
    SKILL_REQUIREMENTS_KEYS,
    SKILL_REQUIREMENTS_SCHEMA,
    validate_artifact,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# POSIX/shell built-ins that are safe to ignore during command scanning.
# Deliberately broad and conservative to avoid false positives.
_SHELL_BUILTINS: frozenset[str] = frozenset(
    {
        # flow control keywords
        "if",
        "else",
        "elif",
        "fi",
        "then",
        "while",
        "for",
        "do",
        "done",
        "case",
        "esac",
        "function",
        # builtins
        "echo",
        "printf",
        "read",
        "export",
        "local",
        "set",
        "unset",
        "shift",
        "eval",
        "exec",
        "source",
        ".",
        "exit",
        "return",
        "true",
        "false",
        "cd",
        "pwd",
        "test",
        "[",
        "[[",
        "]]",
        "]",
        # common POSIX utilities
        "grep",
        "sed",
        "awk",
        "mkdir",
        "cp",
        "mv",
        "rm",
        "touch",
        "ls",
        "cat",
        "head",
        "tail",
        "wc",
        "sort",
        "uniq",
        "tr",
        "cut",
        "xargs",
        "find",
        "env",
        "date",
        "sleep",
        "dirname",
        "basename",
        "tee",
        # bash-specific
        "declare",
        "typeset",
        "readonly",
        "hash",
        "type",
        "command",
        "builtin",
        "getopts",
        "trap",
        "wait",
        "jobs",
        "kill",
        "disown",
        "mapfile",
        "readarray",
    }
)

# Standard-library top-level module names, sourced from the running
# interpreter (sys.stdlib_module_names, available since Python 3.10; the
# project targets 3.11+). Only third-party imports are flagged for
# requires-pip. Deriving from the interpreter avoids the drift a
# hand-maintained list incurs on every Python upgrade.
_STDLIB_MODULES: frozenset[str] = sys.stdlib_module_names

# ALL_CAPS tokens are shell variable references (e.g. BRANCH, PLAN_FILE), not commands.
_ALL_CAPS_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")

# Here-document opener: <<WORD, <<'WORD', <<"WORD", and the <<- indented variant.
_HEREDOC_RE = re.compile(r"<<(-?)\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")

# Scannable requires-* keys: keys whose values can be detected by static analysis.
# requires-skills is intentionally excluded — no automated scanner can detect
# cross-skill dependencies from source code alone.
SCANNABLE_KEYS: tuple[str, ...] = tuple(
    k for k in SKILL_REQUIREMENTS_KEYS if k != "requires-skills"
)

# Command-position regex: first word after start-of-line, ;, |, &&, ||, (, {
_CMD_POSITION_RE = re.compile(
    r"(?:^|[;|{(&]|&&|\|\|)\s*([A-Za-z0-9_./-]+)",
    re.MULTILINE,
)

# ---------------------------------------------------------------------------
# Project root + parametrize list (evaluated at collection time)
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _skill_names_from_dir() -> list[str]:
    """Collect skill folder names from .claude/skills/ at import time."""
    skills_path = _PROJECT_ROOT / ".claude" / "skills"
    if not skills_path.exists():
        return []
    return sorted(
        d.name
        for d in skills_path.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    )


_ALL_SKILL_NAMES: list[str] = _skill_names_from_dir()

# ---------------------------------------------------------------------------
# Module-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def skills_dir() -> Path:
    d = _PROJECT_ROOT / ".claude" / "skills"
    if not d.exists():
        pytest.skip(".claude/skills/ directory doesn't exist")
    return d


@pytest.fixture(scope="module")
def skill_rules(skills_dir: Path) -> dict[str, Any]:
    rules_file = skills_dir / "skill-rules.json"
    if not rules_file.exists():
        pytest.skip("skill-rules.json doesn't exist")
    return json.loads(rules_file.read_text())


@pytest.fixture(scope="module")
def skill_names(skill_rules: dict[str, Any]) -> list[str]:
    return list(skill_rules.get("skills", {}).keys())


# ---------------------------------------------------------------------------
# Shell command scanner
# ---------------------------------------------------------------------------


def _scan_sh_commands(path: Path) -> set[str]:
    """Return non-builtin command names invoked in a shell script.

    Conservative scanner that avoids false positives:
    - Skips pure comment lines (first non-space char is '#').
    - Strips inline ' # ...' tail comments.
    - Strips double-quoted strings FIRST (may contain embedded apostrophes).
    - Tracks multi-line single-quoted blocks (awk/sed programs) via a state
      machine; lines inside such blocks are skipped entirely.
    - Strips single-line single-quoted strings.
    - Filters ALL_CAPS tokens (shell variable references, not commands).
    - Filters locally defined shell function names.
    - Filters _SHELL_BUILTINS, variable assignments, $ expansions, and paths.
    """
    detected: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return detected

    # Collect locally defined function names to exclude their call-sites.
    defined_functions: set[str] = set()
    for m in re.finditer(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*\)", text, re.MULTILINE):
        defined_functions.add(m.group(1))
    for m in re.finditer(
        r"^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)", text, re.MULTILINE
    ):
        defined_functions.add(m.group(1))

    in_sq_block = False  # True while inside a multi-line single-quoted string
    in_heredoc = False   # True while inside a here-document body
    heredoc_term = ""    # Terminator word (bare, unquoted) to watch for
    heredoc_indented = False  # True for <<- variant (tab-stripped terminator)

    for line in text.splitlines():
        stripped = line.strip()

        if in_heredoc:
            # Inside a here-document body — skip scanning entirely.
            # For <<- the terminator may be tab-indented; strip tabs before compare.
            compare = line.lstrip("\t") if heredoc_indented else line
            if compare.rstrip("\n") == heredoc_term:
                in_heredoc = False
            continue

        if in_sq_block:
            # Inside a multi-line single-quoted block — skip scanning.
            # Strip double-quoted content before counting bare ' to avoid
            # embedded apostrophes in "won't" style strings confusing the count.
            dq_clean = re.sub(r'"[^"]*"', '""', line)
            bare_sq = len(re.findall(r"(?<!\\)'", dq_clean))
            if bare_sq % 2 == 1:
                in_sq_block = False
            continue

        # Skip pure comment lines.
        if stripped.startswith("#"):
            continue

        # Strip inline tail comment (conservative: only ' #' with leading whitespace).
        line_no_comment = re.sub(r"\s#.*$", "", line)

        # Detect a here-document opener (<<WORD / <<'WORD' / <<"WORD" / <<-WORD)
        # on the comment-stripped line, but ONLY when the `<<` is not inside a
        # quoted string. We require an even count of bare single AND double quotes
        # before the match, so a `<<WORD` token living in a comment or any quoted
        # string (e.g. an awk program `awk '... <<X ...'`, or echo "... <<X ...")
        # cannot falsely open a here-doc and swallow the rest of the file — which
        # would make the consistency check vacuous (a real undeclared command
        # after such a line would go undetected). Detection runs before quote
        # stripping so quoted delimiters like <<'EOF' / <<"EOF" still register.
        # The body is on the next line: set state but still scan this line (the
        # command precedes `<<`).
        hd_match = _HEREDOC_RE.search(line_no_comment)
        if hd_match:
            before = line_no_comment[: hd_match.start()]
            sq_before = len(re.findall(r"(?<!\\)'", before))
            dq_before = len(re.findall(r'(?<!\\)"', before))
            if sq_before % 2 == 0 and dq_before % 2 == 0:
                in_heredoc = True
                heredoc_indented = hd_match.group(1) == "-"
                heredoc_term = hd_match.group(2)

        # Strip double-quoted strings FIRST — they may contain embedded ' chars
        # (e.g. "won't_do") that would confuse the single-quote counter.
        clean = re.sub(r'"[^"]*"', '""', line_no_comment)

        # Count bare (non-backslash-preceded) single quotes to detect block open.
        bare_sq = len(re.findall(r"(?<!\\)'", clean))

        if bare_sq % 2 == 1:
            # An odd number of bare single quotes means a multi-line block opens here.
            in_sq_block = True
            # Scan only the portion BEFORE the opening quote.
            sq_pos = clean.index("'") if "'" in clean else len(clean)
            scan_target = clean[:sq_pos]
        else:
            # Even: strip any remaining single-line single-quoted strings.
            clean = re.sub(r"'[^']*'", "''", clean)
            scan_target = clean

        for m in _CMD_POSITION_RE.finditer(scan_target):
            token = m.group(1)
            if not token:
                continue
            # Skip $VARIABLE references
            if token.startswith("$"):
                continue
            # Skip variable assignments (TOKEN= or TOKEN+=)
            if "=" in token:
                continue
            # Skip numeric tokens
            if token.isdigit():
                continue
            # Skip absolute paths
            if token.startswith("/"):
                continue
            # Skip shell builtins
            if token in _SHELL_BUILTINS:
                continue
            # Skip ALL_CAPS (shell variable references, not external commands)
            if _ALL_CAPS_RE.match(token):
                continue
            # Skip locally defined functions
            if token in defined_functions:
                continue
            detected.add(token)

    return detected


# ---------------------------------------------------------------------------
# Python AST scanner
# ---------------------------------------------------------------------------


def _check_call_node(
    node: ast.Call, result: dict[str, set[str]]
) -> None:
    """Inspect a Call AST node for os.getenv (env) and subprocess calls (cmd)."""
    func = node.func

    # os.getenv('KEY') → requires-env, but ONLY when there is no default.
    # os.getenv('KEY', 'fallback') is intentionally ignored.
    if (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "os"
        and func.attr == "getenv"
    ):
        args = node.args
        has_default = len(args) >= 2 or any(
            kw.arg == "default" for kw in node.keywords
        )
        if not has_default and args:
            key_node = args[0]
            if isinstance(key_node, ast.Constant) and isinstance(
                key_node.value, str
            ):
                result["requires-env"].add(key_node.value)
        return

    _SUBPROCESS_ATTRS = frozenset(
        {"run", "Popen", "call", "check_output", "check_call"}
    )
    _OS_PROC_ATTRS = frozenset({"system", "popen"})

    is_subprocess_call = (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "subprocess"
        and func.attr in _SUBPROCESS_ATTRS
    )
    is_os_proc = (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "os"
        and func.attr in _OS_PROC_ATTRS
    )

    if not (is_subprocess_call or is_os_proc):
        return

    if not node.args:
        return
    first_arg = node.args[0]

    if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
        # String form: subprocess.run("git status")
        cmd_token = first_arg.value.split()[0] if first_arg.value.strip() else None
        if cmd_token:
            result["requires-cmd"].add(cmd_token)
    elif isinstance(first_arg, ast.List) and first_arg.elts:
        # List form: subprocess.run(["git", "status"])
        first_elt = first_arg.elts[0]
        if isinstance(first_elt, ast.Constant) and isinstance(
            first_elt.value, str
        ):
            result["requires-cmd"].add(first_elt.value)


def _scan_py_deps(path: Path) -> dict[str, set[str]]:
    """Scan a Python file for requires-pip / requires-env / requires-cmd.

    requires-pip: top-level imports whose root module is NOT in _STDLIB_MODULES.
    requires-env: os.environ['KEY'] or os.getenv('KEY') with NO default.
    requires-cmd: subprocess.* / os.system / os.popen with a literal command.
    """
    result: dict[str, set[str]] = {
        "requires-pip": set(),
        "requires-env": set(),
        "requires-cmd": set(),
    }
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError):
        return result

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in _STDLIB_MODULES:
                    result["requires-pip"].add(root)

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root = node.module.split(".")[0]
                if root and root not in _STDLIB_MODULES:
                    result["requires-pip"].add(root)

        # os.environ['KEY'] → requires-env
        elif isinstance(node, ast.Subscript):
            if (
                isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "os"
                and node.value.attr == "environ"
            ):
                key_node = node.slice
                if isinstance(key_node, ast.Constant) and isinstance(
                    key_node.value, str
                ):
                    result["requires-env"].add(key_node.value)

        elif isinstance(node, ast.Call):
            _check_call_node(node, result)

    return result


# ---------------------------------------------------------------------------
# Aggregate scanner
# ---------------------------------------------------------------------------


def detect_skill_deps(skill_dir: Path) -> dict[str, set[str]]:
    """Scan all scripts under <skill_dir>/scripts/ and return detected deps."""
    detected: dict[str, set[str]] = {k: set() for k in SCANNABLE_KEYS}
    scripts_dir = skill_dir / "scripts"
    if not scripts_dir.is_dir():
        return detected

    for script in sorted(scripts_dir.iterdir()):
        if not script.is_file():
            continue
        if script.suffix == ".sh":
            detected["requires-cmd"].update(_scan_sh_commands(script))
        elif script.suffix == ".py":
            py_deps = _scan_py_deps(script)
            for key in SCANNABLE_KEYS:
                detected[key].update(py_deps[key])

    return detected


# ---------------------------------------------------------------------------
# Discovery guard — non-vacuous sentinel (VC2)
# ---------------------------------------------------------------------------


def test_skill_discovery_non_empty(skill_names: list[str]) -> None:
    """Guard: skill-rules.json must list exactly 21 skills (prevents vacuous pass).

    21 = the 16 core MAP skills + map-so-search + map-understand + map-wayfind
         + map-architecture (#363) + map-prd-review (#413).
    """
    assert len(skill_names) == 21, (
        f"Expected 21 skills in skill-rules.json, found {len(skill_names)}: "
        f"{sorted(skill_names)}"
    )


# ---------------------------------------------------------------------------
# VC1 — declared requires-* ⊇ scanner-detected (parametrized per skill)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skill_name", _ALL_SKILL_NAMES)
def test_declared_superset_of_detected(
    skill_name: str,
    skill_rules: dict[str, Any],
    skills_dir: Path,
) -> None:
    """VC1: declared requires-* ⊇ scanner-detected; under-declaration FAILS."""
    skill_entry: dict[str, Any] = skill_rules.get("skills", {}).get(skill_name, {})
    skill_dir = skills_dir / skill_name
    detected = detect_skill_deps(skill_dir)

    undeclared: list[str] = []

    for key in SCANNABLE_KEYS:
        detected_vals = detected[key]
        if not detected_vals:
            continue
        declared_vals: set[str] = set(skill_entry.get(key) or [])
        missing = detected_vals - declared_vals
        if missing:
            undeclared.append(
                f"  {key}: detected {sorted(missing)} but not declared"
            )

    assert not undeclared, (
        f"Skill '{skill_name}' has under-declared requirements:\n"
        + "\n".join(undeclared)
        + "\n\nCurrent declared entry:\n"
        + json.dumps(
            {k: skill_entry.get(k) for k in SKILL_REQUIREMENTS_KEYS}, indent=2
        )
    )


# ---------------------------------------------------------------------------
# VC3a — requires-* sub-block validates vs SKILL_REQUIREMENTS_SCHEMA
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skill_name", _ALL_SKILL_NAMES)
def test_requires_block_schema_valid(
    skill_name: str,
    skill_rules: dict[str, Any],
) -> None:
    """VC3: Each requires-* sub-block validates against SKILL_REQUIREMENTS_SCHEMA."""
    skill_entry: dict[str, Any] = skill_rules.get("skills", {}).get(skill_name, {})

    requires_block = {
        k: skill_entry[k] for k in SKILL_REQUIREMENTS_KEYS if k in skill_entry
    }

    is_valid, errors = validate_artifact(requires_block, SKILL_REQUIREMENTS_SCHEMA)
    assert is_valid, (
        f"Skill '{skill_name}' requires-* sub-block is schema-invalid:\n"
        + "\n".join(f"  - {e}" for e in errors)
        + f"\n\nSub-block: {json.dumps(requires_block, indent=2)}"
    )


# ---------------------------------------------------------------------------
# VC3b — no dangling requires-skills references
# ---------------------------------------------------------------------------


def test_no_dangling_requires_skills(skill_rules: dict[str, Any]) -> None:
    """VC3: Every requires-skills target must be a real key in the catalog."""
    catalog: dict[str, Any] = skill_rules.get("skills", {})
    catalog_keys = set(catalog.keys())
    dangling: list[str] = []

    for skill_name, entry in catalog.items():
        targets: list[str] = entry.get("requires-skills") or []
        for target in targets:
            if target not in catalog_keys:
                dangling.append(
                    f"  '{skill_name}' requires-skills -> '{target}' (not in catalog)"
                )

    assert not dangling, (
        "Dangling requires-skills references found:\n" + "\n".join(dangling)
    )


# ---------------------------------------------------------------------------
# VC4 — scanner unit tests
# ---------------------------------------------------------------------------


def test_scanner_ignores_getenv_with_default(tmp_path: Path) -> None:
    """VC4: os.getenv('KEY', 'default') must NOT be flagged as a required env var."""
    script = tmp_path / "test_getenv.py"
    script.write_text(
        "import os\n"
        "x = os.getenv('WITH_DEFAULT', 'fallback')  # must be ignored\n"
        "y = os.getenv('NO_DEFAULT')                # must be detected\n"
        "z = os.environ['DIRECT_KEY']               # must be detected\n",
        encoding="utf-8",
    )
    deps = _scan_py_deps(script)
    assert "WITH_DEFAULT" not in deps["requires-env"], (
        "getenv with default must be ignored as a required env var"
    )
    assert "NO_DEFAULT" in deps["requires-env"], (
        "getenv without default must be detected as a required env var"
    )
    assert "DIRECT_KEY" in deps["requires-env"], (
        "os.environ['KEY'] must be detected as a required env var"
    )


def test_scanner_ignores_sh_comments(tmp_path: Path) -> None:
    """VC4: Comment lines and inline comments in shell scripts must not yield commands."""
    script = tmp_path / "test_comments.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "# docker run something  <-- full comment line, must be ignored\n"
        "echo hello  # kubectl get pods  <-- inline comment, must be ignored\n"
        "git status  # real command follows\n",
        encoding="utf-8",
    )
    cmds = _scan_sh_commands(script)
    assert "docker" not in cmds, "Command in full comment line must be ignored"
    assert "kubectl" not in cmds, "Command in inline comment must be ignored"
    assert "git" in cmds, "git must still be detected on a real command line"


def test_scanner_ignores_posix_builtins(tmp_path: Path) -> None:
    """VC4: POSIX builtins must not appear in detected requires-cmd."""
    script = tmp_path / "test_builtins.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "mkdir -p /tmp/x\n"
        "cp src dst\n"
        "grep pattern file\n"
        "git rev-parse HEAD\n",
        encoding="utf-8",
    )
    cmds = _scan_sh_commands(script)
    for builtin in ("set", "mkdir", "cp", "grep"):
        assert builtin not in cmds, f"Builtin '{builtin}' must not appear in requires-cmd"
    assert "git" in cmds, "git must be detected (not a builtin)"


def test_scanner_ignores_multiline_awk_program(tmp_path: Path) -> None:
    """VC4: Tokens inside a multi-line awk program must not be flagged as commands."""
    script = tmp_path / "test_awk.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "RESULT=$(\n"
        "    awk '\n"
        "        /pattern/ { getline; print; next }\n"
        "        in_section { print }\n"
        "    ' \"$INFILE\"\n"
        ")\n"
        "git log --oneline\n",
        encoding="utf-8",
    )
    cmds = _scan_sh_commands(script)
    for awk_token in ("getline", "print", "next", "in_section"):
        assert awk_token not in cmds, (
            f"awk token '{awk_token}' inside awk program must not be flagged"
        )
    assert "git" in cmds, "git outside awk block must still be detected"


def test_scanner_ignores_won_t_do_in_echo(tmp_path: Path) -> None:
    """VC4: Apostrophe inside a double-quoted string (won't_do) must not open sq block."""
    script = tmp_path / "test_wontdo.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "echo \"won't_do count: $COUNT\"\n"
        "git status\n",
        encoding="utf-8",
    )
    cmds = _scan_sh_commands(script)
    assert "git" in cmds, "git must be detected after double-quoted string with apostrophe"


def test_scanner_ignores_heredoc_body(tmp_path: Path) -> None:
    """VC4: Tokens inside a heredoc body must not be flagged as required commands."""
    script = tmp_path / "test_heredoc.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "cat <<'EOF'\n"
        "docker run something\n"
        "EOF\n"
        "git status\n",
        encoding="utf-8",
    )
    cmds = _scan_sh_commands(script)
    assert "docker" not in cmds, (
        "Command inside heredoc body must not be flagged as a required command"
    )
    assert "git" in cmds, "git outside the heredoc must still be detected"


def test_scanner_heredoc_token_in_comment_or_string_does_not_swallow(
    tmp_path: Path,
) -> None:
    """A `<<WORD` token in a comment or quoted string must NOT open a heredoc.

    Regression guard: if the heredoc detector runs on the raw line before
    comment/quote stripping, a stray `<<EOF` in a comment or string falsely
    enters heredoc mode and silently swallows every following line until a
    terminator that may never appear — making the consistency check vacuous
    (a real undeclared command after such a line would go undetected).
    """
    script = tmp_path / "tricky.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "# example: cat <<EOF writes a file\n"   # <<EOF in a COMMENT
        'echo "here is a <<EOF token in a string"\n'  # <<EOF in a DQ string
        "terraform apply\n"                      # real, undeclared command AFTER
        "awk '<<NOPE inside awk program'\n"      # <<NOPE inside a SQ string
        "kubectl get pods\n",                    # another real command AFTER
        encoding="utf-8",
    )
    cmds = _scan_sh_commands(script)
    assert "terraform" in cmds, (
        "a <<WORD in a comment/string must not swallow the following command"
    )
    assert "kubectl" in cmds, (
        "a <<WORD inside a single-quoted awk program must not swallow lines"
    )
    # And the fake delimiters themselves are never treated as commands.
    assert "EOF" not in cmds and "NOPE" not in cmds


def test_scanner_real_heredoc_with_quoted_and_indented_delimiters(
    tmp_path: Path,
) -> None:
    """Real heredocs with <<'EOF', <<"EOF", and <<- still suppress their bodies."""
    script = tmp_path / "real_heredocs.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        'cat <<"END1"\n'
        "docker run a\n"
        "END1\n"
        "cat <<-END2\n"
        "\tpodman run b\n"
        "\tEND2\n"
        "git status\n",
        encoding="utf-8",
    )
    cmds = _scan_sh_commands(script)
    assert "docker" not in cmds and "podman" not in cmds, (
        "bodies of <<\"END1\" and <<-END2 heredocs must be suppressed"
    )
    assert "git" in cmds


# ---------------------------------------------------------------------------
# Teeth self-test — under-declaration actually fails (not vacuously always-green)
# ---------------------------------------------------------------------------


def test_scanner_teeth_under_declaration_detected(
    skill_rules: dict[str, Any],
    skills_dir: Path,
) -> None:
    """Self-test: emptying map-state requires-cmd triggers under-declaration failure.

    Proves VC1 has actual teeth — the assertion is NOT vacuously always-green.
    """
    mutated_rules = copy.deepcopy(skill_rules)
    map_state_entry: dict[str, Any] = mutated_rules["skills"]["map-state"]

    original_requires_cmd: list[str] = map_state_entry.get("requires-cmd") or []
    assert original_requires_cmd, (
        "Pre-condition: map-state must have a non-empty requires-cmd in "
        "skill-rules.json for this self-test to be meaningful"
    )

    # Simulate under-declaration by clearing the declared list in-memory only.
    map_state_entry["requires-cmd"] = []

    skill_dir = skills_dir / "map-state"
    detected = detect_skill_deps(skill_dir)

    undeclared: list[str] = []

    for key in SCANNABLE_KEYS:
        detected_vals = detected[key]
        if not detected_vals:
            continue
        declared_vals: set[str] = set(map_state_entry.get(key) or [])
        missing = detected_vals - declared_vals
        if missing:
            undeclared.append(f"{key}: {sorted(missing)}")

    assert undeclared, (
        "Teeth self-test FAILED: clearing map-state requires-cmd did NOT trigger "
        "under-declaration detection.  The VC1 assertion may be vacuously green. "
        f"Scanner detected: {detected}"
    )
    print(
        f"\n[teeth-self-test] PASSED — under-declaration correctly detected: {undeclared}"
    )
