"""Shared pytest fixtures for all test files."""

import os

import pytest


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
