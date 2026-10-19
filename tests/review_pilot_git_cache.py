"""Test-only historical reads; never cache corpus validation or mutable run state."""

import json
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CORPUS = REPO / "tests/skills_eval/review_corpus"
GitRead = Callable[..., bytes]


def historical_commands() -> frozenset[tuple[str, ...]]:
    """Exact argv allowlist from the checked-in pinned corpus, not caller input."""
    data = json.loads((CORPUS / "corpus.json").read_text())
    commands: set[tuple[str, ...]] = {
        ("cat-file", "-e", f"{data['audit_cutoff']['commit']}^{{commit}}")
    }
    for case in data["cases"]:
        base, head = case["base"], case["head"]
        commands.add(("show", "-s", "--format=%P", head))
        for file in case["files"]:
            for side, commit in (("base", base), ("head", head)):
                commands.add(("ls-tree", commit, "--", file["path"]))
                if blob := file.get(f"{side}_blob"):
                    commands.add(("cat-file", "blob", blob))
        for label in case["labels"]:
            for item, commit in ((label, head), (label["fix_mapping"], case["fix"])):
                commands.add(("rev-parse", f"{commit}:{item['path']}"))
                commands.add(("cat-file", "blob", item["blob"]))
        if case["kind"] == "bug":
            commands.add(("merge-base", "--is-ancestor", head, case["fix"]))
        else:
            audit = case["control_audit"]
            commands.add(("merge-base", "--is-ancestor", head, audit["cutoff"]))
            for commit in audit["examined_commits"]:
                commands.add(("cat-file", "-e", f"{commit}^{{commit}}"))
        for context in ((), ("-U30",)):
            commands.add((
                "diff", "--no-ext-diff", "--no-textconv", "--no-renames",
                "--src-prefix=base/", "--dst-prefix=head/", *context, base, head,
                "--", *(file["path"] for file in case["files"]),
            ))
    return frozenset(commands)


@contextmanager
def historical_git_cache(delegate: GitRead) -> Generator[GitRead]:
    """Share successful bytes only while the fixture owns this cache.

    Assumes this repository's object DB and Git configuration remain fixed for the
    module. No caching for other repositories or unknown argv. The pilot tests
    mutate only tmp_path run/evidence state, which is always reread/validated.
    """
    allowed = historical_commands()
    values: dict[tuple[Path, tuple[str, ...]], bytes] = {}

    def read(repo: Path, *args: str) -> bytes:
        key = (repo.resolve(), args)
        if key[0] != REPO or args not in allowed:
            return delegate(repo, *args)
        if key not in values:
            values[key] = delegate(repo, *args)
        return values[key]

    try:
        yield read
    finally:
        values.clear()
