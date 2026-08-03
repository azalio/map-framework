"""classify_scope.py — Scale-adaptive scope classifier for MAP workflows (#287).

Reads scale thresholds from .map/config.yaml (dotted-key notation) and
classifies a change estimate into one of four brackets: trivial, small,
medium, or large, then returns the recommended MAP workflow depth.

Usage:
    python3 .map/scripts/classify_scope.py --files 5 --lines 120

Output (JSON, exit 0):
    {"bracket": "small", "recommended_workflow": "map-plan-light",
     "estimated_files": 5, "estimated_lines": 120, "auto_enabled": true}

Config keys read from .map/config.yaml (dotted notation):
    scale.auto                         (default: true)
    scale.thresholds.trivial.max_files (default: 3)
    scale.thresholds.trivial.max_lines (default: 50)
    scale.thresholds.small.max_files   (default: 10)
    scale.thresholds.small.max_lines   (default: 200)
    scale.thresholds.medium.max_files  (default: 30)
    scale.thresholds.medium.max_lines  (default: 1000)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_BRACKET_WORKFLOW: dict[str, str] = {
    "trivial": "map-fast",
    "small": "map-plan-light",
    "medium": "map-efficient",
    "large": "map-efficient+map-tdd",
}

_DEFAULTS: dict[str, str] = {
    "scale.auto": "true",
    "scale.thresholds.trivial.max_files": "3",
    "scale.thresholds.trivial.max_lines": "50",
    "scale.thresholds.small.max_files": "10",
    "scale.thresholds.small.max_lines": "200",
    "scale.thresholds.medium.max_files": "30",
    "scale.thresholds.medium.max_lines": "1000",
}


_SNAKE_ALIASES: dict[str, str] = {
    "scale_auto": "scale.auto",
    "scale_trivial_max_files": "scale.thresholds.trivial.max_files",
    "scale_trivial_max_lines": "scale.thresholds.trivial.max_lines",
    "scale_small_max_files": "scale.thresholds.small.max_files",
    "scale_small_max_lines": "scale.thresholds.small.max_lines",
    "scale_medium_max_files": "scale.thresholds.medium.max_files",
    "scale_medium_max_lines": "scale.thresholds.medium.max_lines",
}


def _read_config(project_dir: Path) -> dict[str, str]:
    """Read .map/config.yaml scalar values without external dependencies.

    Supports both the dotted-key form used in the config template (e.g.
    ``scale.thresholds.trivial.max_files``) and the snake_case form that
    ``load_map_config()`` aliases (e.g. ``scale_trivial_max_files``).
    """
    config_path = project_dir / ".map" / "config.yaml"
    if not config_path.is_file():
        return {}
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    values: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if not key or not re.fullmatch(r"[A-Za-z0-9_.]+", key):
            continue
        value = value.split("#", 1)[0].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    # Accept snake_case aliases (e.g. scale_trivial_max_files) in addition to
    # the canonical dotted form so both config styles are honoured.
    for snake, dotted in _SNAKE_ALIASES.items():
        if snake in values and dotted not in values:
            values[dotted] = values[snake]
    return values


def classify(
    estimated_files: int,
    estimated_lines: int,
    project_dir: Path | None = None,
) -> dict[str, object]:
    """Classify scope and return a result dict matching ScopeClassification fields."""
    raw = _read_config(project_dir or Path("."))

    def _int(key: str) -> int:
        raw_val = raw.get(key, _DEFAULTS[key])
        try:
            return int(raw_val)
        except ValueError:
            print(
                f"warning: classify_scope: invalid integer {raw_val!r} for config "
                f"key {key!r}; using default {_DEFAULTS[key]}",
                file=sys.stderr,
            )
            return int(_DEFAULTS[key])

    def _bool(key: str) -> bool:
        return raw.get(key, _DEFAULTS[key]).lower() not in {"false", "0", "no"}

    auto = _bool("scale.auto")
    trivial_files = _int("scale.thresholds.trivial.max_files")
    trivial_lines = _int("scale.thresholds.trivial.max_lines")
    small_files = _int("scale.thresholds.small.max_files")
    small_lines = _int("scale.thresholds.small.max_lines")
    medium_files = _int("scale.thresholds.medium.max_files")
    medium_lines = _int("scale.thresholds.medium.max_lines")

    if estimated_files <= trivial_files and estimated_lines <= trivial_lines:
        bracket = "trivial"
    elif estimated_files <= small_files and estimated_lines <= small_lines:
        bracket = "small"
    elif estimated_files <= medium_files and estimated_lines <= medium_lines:
        bracket = "medium"
    else:
        bracket = "large"

    return {
        "bracket": bracket,
        "recommended_workflow": _BRACKET_WORKFLOW[bracket],
        "estimated_files": estimated_files,
        "estimated_lines": estimated_lines,
        "auto_enabled": auto,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Classify MAP workflow scope from estimated change size.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--files", type=int, required=True,
                        help="Estimated number of files to change (>= 0)")
    parser.add_argument("--lines", type=int, required=True,
                        help="Estimated lines to add/modify (>= 0)")
    parser.add_argument("--project-dir", default=".",
                        help="Project root (default: current directory)")
    args = parser.parse_args(argv)

    if args.files < 0 or args.lines < 0:
        print("error: --files and --lines must be >= 0", file=sys.stderr)
        return 1

    result = classify(args.files, args.lines, Path(args.project_dir))
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
