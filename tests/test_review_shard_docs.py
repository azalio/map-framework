"""Every runnable map-review example that builds prompts or captures output carries the shard hook (#625)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / ".claude/skills/map-review"
COMMAND = re.compile(r"map_step_runner\.py (build_(?:review|role_review|adversarial_review)_prompts|capture_review_output)\b")


def test_runnable_examples_pass_the_shard_hook():
    checked = 0
    for path in sorted(SKILLS.glob("*.md")):
        lines = path.read_text().splitlines()
        for index, line in enumerate(lines):
            if not COMMAND.search(line) or "`" in line or line.lstrip().startswith(("-", "|")):
                continue  # Prose mentions are not runnable examples.
            window = " ".join(lines[index:index + 3])
            assert "--shard" in window, f"{path.name}:{index + 1}: {line.strip()}"
            checked += 1
    assert checked >= 5, checked
