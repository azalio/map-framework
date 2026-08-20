"""Report an unsupported interpreter by name, not as an ``ImportError``.

``mapify_cli`` uses Python 3.11+ constructs (``datetime.UTC``, PEP 604 unions in
evaluated annotations). ``pyproject.toml`` declares ``requires-python = ">=3.11"``,
which stops every PEP-517-aware installer -- but not ``python3 -m mapify_cli`` from
a source clone, nor an install forced with ``--ignore-requires-python``. Without
this module those paths die on ``ImportError: cannot import name 'UTC' from
'datetime'``, which never mentions a Python version.

``mapify_cli/__init__.py`` imports this module BEFORE any 3.11-only import, so the
check runs first. Everything here must stay parsable and runnable on old
interpreters: no PEP 604 unions, no ``datetime.UTC``, no walrus in a comprehension.

The version floor is duplicated here on purpose (importing
:mod:`mapify_cli.python_runtime` would itself have to be version-safe);
``tests/test_python_version_requirement.py`` asserts every copy agrees.
"""

import sys

# UP036 is suppressed on purpose: the project targets 3.11, but this check exists
# precisely for interpreters older than the target.
if sys.version_info < (3, 11):  # noqa: UP036
    sys.stderr.write(
        f"mapify requires Python 3.11 or newer, but {sys.executable} is "
        f"Python {sys.version_info[0]}.{sys.version_info[1]}.\n"
        "Install Python 3.11+ (brew install python@3.12, uv python install 3.12,\n"
        "or pyenv install), then re-install mapify with that interpreter --\n"
        "for example: uv tool install --python 3.12 mapify-cli\n"
    )
    raise SystemExit(1)
