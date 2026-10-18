"""Exercise shipped handlers under macOS Bash 3.2 and modern PATH Bash."""

import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

HANDLERS = (
    Path(__file__).resolve().parents[1]
    / "src/mapify_cli/templates/map/static-analysis/handlers"
)


@pytest.fixture(params=["system-3.2", "path-modern"])
def bash(request: pytest.FixtureRequest, tmp_path: Path) -> str:
    executable = "/bin/bash" if request.param == "system-3.2" else shutil.which("bash")
    if not executable or not Path(executable).is_file():
        pytest.skip(f"{request.param}: Bash executable unavailable")
    result = subprocess.run(
        [executable, "-c", 'printf "%s" "$BASH_VERSION"'],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    version = tuple(int(part) for part in result.stdout.split(".")[:2])
    if request.param == "system-3.2" and version != (3, 2):
        pytest.skip(f"/bin/bash is {result.stdout}, not Bash 3.2")
    if request.param == "path-modern" and version[0] < 4:
        pytest.skip(f"PATH Bash is {result.stdout}, not Bash 4+")
    return executable


def run_shell(
    bash: str, script: str, tmp_path: Path, env: dict[str, str] | None = None
):
    return subprocess.run(
        [bash, "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize(
    "names", ["file line col msg", "input out_file out_line out_msg"]
)
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("fixture.go:1:2:message", ["fixture.go", "1", "2", "message"]),
        (
            "dir:with space/file.py:12: error: bad: value",
            ["dir:with space/file.py", "12", "0", " error: bad: value"],
        ),
        ("a.go:4:3:", ["a.go", "4", "3", ""]),
    ],
)
def test_parser_outputs(
    bash: str, tmp_path: Path, names: str, text: str, expected: list[str]
):
    variables = " ".join(f'"${name}"' for name in names.split())
    result = run_shell(
        bash,
        f"""set -eu
source {shlex.quote(str(HANDLERS / "common.sh"))}
parse_colon_delimited {shlex.quote(text)} {names}
printf '%s\\n' {variables}
""",
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.splitlines() == expected


def test_reported_public_reproduction(bash: str, tmp_path: Path):
    result = run_shell(
        bash,
        f"""source {shlex.quote(str(HANDLERS / "common.sh"))}
parse_colon_delimited "fixture.go:1:2:message" file line col msg
printf 'parser_exit=%s file=%s line=%s col=%s msg=%s\\n' "$?" "$file" "$line" "$col" "$msg"
""",
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "parser_exit=0 file=fixture.go line=1 col=2 msg=message\n"


def test_parser_assigns_caller_locals(bash: str, tmp_path: Path):
    result = run_shell(
        bash,
        f"""set -eu
source {shlex.quote(str(HANDLERS / "common.sh"))}
caller() {{
    local input=old out_file=old out_col=old out_msg=old
    parse_colon_delimited 'a.go:1:2:message' input out_file out_col out_msg
    printf '%s\\n' "$input" "$out_file" "$out_col" "$out_msg"
}}
caller
""",
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.splitlines() == ["a.go", "1", "2", "message"]


def test_parser_assignment_failure_is_not_success(bash: str, tmp_path: Path):
    result = run_shell(
        bash,
        f"""source {shlex.quote(str(HANDLERS / "common.sh"))}
readonly file=original
parse_colon_delimited 'a.go:1:2:message' file line col msg
""",
        tmp_path,
    )
    assert result.returncode != 0
    assert result.stderr == ""


@pytest.mark.parametrize("text", ["", "not a diagnostic", "a.go:no:message"])
def test_parser_rejects_malformed_without_mutation(
    bash: str, tmp_path: Path, text: str
):
    result = run_shell(
        bash,
        f"""source {shlex.quote(str(HANDLERS / "common.sh"))}
file=old; line=old; col=old; msg=old
if parse_colon_delimited {shlex.quote(text)} file line col msg; then exit 9; fi
printf '%s\\n' "$file" "$line" "$col" "$msg"
""",
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.splitlines() == ["old"] * 4


@pytest.mark.parametrize(
    "names",
    ["file line col", "file line col 'bad[index]'", "file line col __map_parse_input"],
)
def test_parser_rejects_invalid_output_names(bash: str, tmp_path: Path, names: str):
    result = run_shell(
        bash,
        f"""source {shlex.quote(str(HANDLERS / "common.sh"))}
if parse_colon_delimited 'a.go:1:2:message' {names}; then exit 9; fi
""",
        tmp_path,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("handler", "tool", "diagnostic", "message", "column"),
    [
        ("go", "go", "fixture.go:1:2: bad value", "bad value", 2),
        ("python", "mypy", "fixture.py:1: error: bad value", "bad value", 0),
    ],
)
@pytest.mark.parametrize("has_finding", [True, False])
def test_real_handler_fixture_output(
    bash: str,
    tmp_path: Path,
    handler: str,
    tool: str,
    diagnostic: str,
    message: str,
    column: int,
    has_finding: bool,
):
    # Restricted PATH prevents accidentally running installed linters on the host.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("jq", "dirname"):
        executable = shutil.which(name)
        if not executable:
            pytest.skip(f"handler integration requires {name}")
        (bin_dir / name).symlink_to(executable)
    timeout = bin_dir / "timeout"
    timeout.write_text(f'#!{bash}\nshift\nexec "$@"\n')
    timeout.chmod(0o755)
    linter = bin_dir / tool
    output = "unparseable banner\n" + (diagnostic if has_finding else "")
    linter.write_text(f"#!{bash}\nprintf '%s\\n' {shlex.quote(output)}\nexit 1\n")
    linter.chmod(0o755)
    result = run_shell(
        bash,
        f"source {shlex.quote(str(HANDLERS / (handler + '.sh')))} --files fixture",
        tmp_path,
        {**os.environ, "PATH": str(bin_dir)},
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["summary"] == {
        "total": int(has_finding),
        "errors": int(has_finding),
        "warnings": 0,
        "pass": not has_finding,
    }
    if has_finding:
        assert payload["findings"] == [
            {
                "tool": "go vet" if handler == "go" else "mypy",
                "file": "fixture.go" if handler == "go" else "fixture.py",
                "line": 1,
                "column": column,
                "severity": "error",
                "code": "vet" if handler == "go" else "mypy",
                "message": message,
                "fixable": False,
            }
        ]
    else:
        assert payload["findings"] == []
