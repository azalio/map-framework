"""Shared pytest fixtures for all test files."""

import os
import sys

import pytest


sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")


@pytest.fixture(autouse=True)
def _restore_cwd():
    """Restore working directory after each test.

    Many tests call os.chdir(tmp_path) without cleanup. This fixture
    ensures the CWD is always restored so subsequent tests (especially
    those using relative paths like .claude/hooks/) are not affected.
    """
    original = os.getcwd()
    yield
    os.chdir(original)
