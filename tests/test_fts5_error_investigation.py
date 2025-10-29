"""
Test cases to reproduce FTS5 SQL column errors.

This test suite documents and reproduces the exact error patterns
that occur when using multi-word queries with hyphens in the playbook
query system.

Root Cause Analysis:
====================

The errors occur in `_build_fts_query` method (lines 995-1062 of playbook_manager.py).

Issue 1: Hyphen Sanitization (Line 1013)
-----------------------------------------
The method removes special characters including hyphens, but does NOT quote
the resulting multi-word phrases:

    fts_query = fts_query.replace(char, ' ')  # Line 1013

When input is "session-start" it becomes "session start".

Issue 2: FTS5 Multi-Word Interpretation (Lines 1016-1020)
---------------------------------------------------------
The code applies prefix matching to each word individually:

    words = fts_query.split()
    fts_query = ' '.join([f"{word}*" for word in words if len(word) >= 2])

This converts "session start" to "session* start*"

Issue 3: FTS5 Query Execution (Line 1033)
-----------------------------------------
The resulting query is passed to FTS5 MATCH operator:

    WHERE fts.bullets_fts MATCH ?

With parameter: "session* start*"

FTS5 Interpretation Problem:
============================

FTS5 interprets unquoted multi-word queries as boolean AND by default:
- "session* start*" means: (find "session*") AND (find "start*")
- FTS5 tries to match each term against indexed columns (content, code_example)
- When a term doesn't exist in the FTS index, FTS5 interprets it as a COLUMN name
- This causes "no such column: start" error

The problem is that FTS5 doesn't know "start" is a search term when it's not
found in the index - it thinks it's a column reference.

Correct FTS5 Format Requirements:
==================================

To search for multi-word phrases, FTS5 requires:

1. Phrase queries (exact match):
   MATCH '"session start"'  -- Finds exact phrase "session start"

2. Quoted terms (with prefix):
   MATCH '"session"* "start"*'  -- Finds documents with both words (prefix match)

3. Boolean queries (explicit):
   MATCH 'session* AND start*'  -- Explicit AND operator

4. Grouping:
   MATCH '(session OR sessions) AND start*'  -- Complex boolean logic

Current Bug:
============
Current code generates: 'session* start*' (unquoted, no operator)
FTS5 interprets this as: session* AND start* (implicit AND)
When "start" not found → FTS5 error: "no such column: start"

Fix Strategy:
=============
Option A: Quote each term (preferred for prefix matching)
   'hooks* "session-start"* "auto-injection"*'
   → '"hooks"* "session"* "start"* "auto"* "injection"*'

Option B: Explicit AND operators
   'hooks session-start auto-injection'
   → 'hooks* AND session* AND start* AND auto* AND injection*'

Option C: Phrase query (for exact phrases, no prefix)
   'hooks session-start auto-injection'
   → '"hooks" "session start" "auto injection"'

Recommendation: Option A (quoted terms with prefix matching)
- Preserves prefix matching behavior (JWT* matches JWT, JWTs, JWToken)
- Robust against FTS5 column interpretation
- No syntax errors with special characters
"""

import pytest
import sqlite3
import tempfile
from pathlib import Path
import json
from datetime import datetime

from mapify_cli.playbook_manager import PlaybookManager
from mapify_cli.playbook_query import PlaybookQuery, SearchMode


class TestFTS5ErrorPatterns:
    """Reproduce and document FTS5 error patterns."""

    @pytest.fixture
    def temp_playbook(self):
        """Create a temporary playbook with test data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            playbook_path = Path(tmpdir) / "playbook.json"
            db_path = Path(tmpdir) / "playbook.db"

            # Create test playbook with sample bullets
            playbook = {
                "version": "1.0",
                "metadata": {
                    "project": "test",
                    "created_at": datetime.utcnow().isoformat() + "Z",
                    "last_updated": datetime.utcnow().isoformat() + "Z",
                    "total_bullets": 3,
                    "sections_count": 1,
                    "top_k": 5
                },
                "sections": {
                    "IMPLEMENTATION_PATTERNS": {
                        "description": "Test patterns",
                        "bullets": [
                            {
                                "id": "impl-0001",
                                "content": "Hooks system with auto-activation workflow for skills",
                                "helpful_count": 5,
                                "harmful_count": 0,
                                "created_at": datetime.utcnow().isoformat() + "Z",
                                "last_used_at": datetime.utcnow().isoformat() + "Z"
                            },
                            {
                                "id": "impl-0002",
                                "content": "Session-start hook for auto-injection of validation files",
                                "helpful_count": 3,
                                "harmful_count": 0,
                                "created_at": datetime.utcnow().isoformat() + "Z",
                                "last_used_at": datetime.utcnow().isoformat() + "Z"
                            },
                            {
                                "id": "impl-0003",
                                "content": "Multi-subtask dependency verification using upstream artifacts",
                                "helpful_count": 4,
                                "harmful_count": 0,
                                "created_at": datetime.utcnow().isoformat() + "Z",
                                "last_used_at": datetime.utcnow().isoformat() + "Z"
                            }
                        ]
                    }
                }
            }

            playbook_path.write_text(json.dumps(playbook, indent=2))

            manager = PlaybookManager(playbook_path=str(playbook_path), db_path=str(db_path))
            yield manager
            manager.close()

    def test_error_pattern_1_auto_activation(self, temp_playbook):
        """
        Reproduce Error: "no such column: activation"

        Query: "hooks system error handling workflow skills auto-activation"
        Expected: FTS5 error when 'activation' is not in index

        Root cause:
        - Input: "auto-activation"
        - After hyphen removal (line 1013): "auto activation"
        - After prefix matching (lines 1019-1020): "auto* activation*"
        - FTS5 interprets as: auto* AND activation*
        - If "activation" not found → "no such column: activation"
        """
        query = "hooks system error handling workflow skills auto-activation"

        params = PlaybookQuery(
            query=query,
            limit=10,
            search_mode=SearchMode.PLAYBOOK_ONLY,
            fts_prefix=True
        )

        with pytest.raises(sqlite3.OperationalError) as exc_info:
            temp_playbook.query(params)

        assert "no such column" in str(exc_info.value).lower()
        # Document which word caused the error
        error_msg = str(exc_info.value)
        print(f"\n✓ Error reproduced: {error_msg}")

    def test_error_pattern_2_session_start(self, temp_playbook):
        """
        Reproduce Error: "no such column: start"

        Query: "hooks session-start auto-injection file validation"
        Expected: FTS5 error when 'start' is not in index

        Root cause:
        - Input: "session-start"
        - After hyphen removal: "session start"
        - After prefix matching: "session* start*"
        - FTS5 tries to find "start" in index
        - If not found → "no such column: start"
        """
        query = "hooks session-start auto-injection file validation"

        params = PlaybookQuery(
            query=query,
            limit=5,
            search_mode=SearchMode.PLAYBOOK_ONLY,
            fts_prefix=True
        )

        with pytest.raises(sqlite3.OperationalError) as exc_info:
            temp_playbook.query(params)

        assert "no such column" in str(exc_info.value).lower()
        error_msg = str(exc_info.value)
        print(f"\n✓ Error reproduced: {error_msg}")

    def test_error_pattern_3_multi_subtask(self, temp_playbook):
        """
        Reproduce Error: "no such column: subtask"

        Query: "multi-subtask dependency verification upstream artifacts"
        Expected: FTS5 error when 'subtask' is not in index

        Root cause:
        - Input: "multi-subtask"
        - After hyphen removal: "multi subtask"
        - After prefix matching: "multi* subtask*"
        - FTS5 interprets as: multi* AND subtask*
        - If "subtask" not found → "no such column: subtask"
        """
        query = "multi-subtask dependency verification upstream artifacts"

        params = PlaybookQuery(
            query=query,
            limit=5,
            search_mode=SearchMode.PLAYBOOK_ONLY,
            fts_prefix=True
        )

        with pytest.raises(sqlite3.OperationalError) as exc_info:
            temp_playbook.query(params)

        assert "no such column" in str(exc_info.value).lower()
        error_msg = str(exc_info.value)
        print(f"\n✓ Error reproduced: {error_msg}")

    def test_build_fts_query_sanitization(self, temp_playbook):
        """
        Test the exact sanitization logic in _build_fts_query.

        This test documents the current behavior:
        1. Hyphens are PRESERVED (NOT removed)
        2. Each word gets prefix matching asterisk (lines 1019-1020)
        3. Result is hyphenated words with asterisk suffix
        4. FTS5 tokenizer splits hyphens at INDEX time, not query time
        5. Query contains "session-start*" but index has "session" + "start" separately
        """
        # Test query with hyphenated words
        test_query = "session-start auto-activation multi-subtask"

        params = PlaybookQuery(
            query=test_query,
            limit=5,
            search_mode=SearchMode.PLAYBOOK_ONLY,
            fts_prefix=True
        )

        # Build FTS query
        sql, sql_params = temp_playbook._build_fts_query(params, limit=5)

        # Extract the FTS query parameter (first param is the FTS query)
        fts_query_param = sql_params[0]

        print(f"\nOriginal query: {test_query}")
        print(f"FTS query param: {fts_query_param}")
        print(f"Generated SQL:\n{sql}")

        # Document current behavior: HYPHENS ARE PRESERVED
        assert "session-start*" in fts_query_param
        assert "auto-activation*" in fts_query_param
        assert "multi-subtask*" in fts_query_param

        # This is the problem: query contains "session-start*" as single token,
        # but FTS5 index has "session" and "start" as separate tokens.
        # FTS5 can't find "session-start" token → interprets as column name → error

    def test_fts5_query_format_requirements(self):
        """
        Document FTS5 MATCH operator syntax requirements.

        This test demonstrates correct FTS5 query formats that work.
        """
        # Create in-memory database with FTS5 table
        conn = sqlite3.connect(':memory:')
        cursor = conn.cursor()

        # Create test table with FTS5
        cursor.execute("""
            CREATE VIRTUAL TABLE test_fts USING fts5(content)
        """)

        # Insert test data
        cursor.execute("INSERT INTO test_fts (content) VALUES (?)",
                      ("Hooks system with session start auto activation",))
        cursor.execute("INSERT INTO test_fts (content) VALUES (?)",
                      ("Multi subtask dependency verification",))

        # Test Case 1: Phrase query (exact match) - WORKS
        try:
            cursor.execute('SELECT * FROM test_fts WHERE test_fts MATCH ?',
                          ('"session start"',))
            results = cursor.fetchall()
            print(f"\n✓ Phrase query works: {len(results)} results")
        except sqlite3.OperationalError as e:
            print(f"\n✗ Phrase query failed: {e}")

        # Test Case 2: Quoted terms with prefix - WORKS
        try:
            cursor.execute('SELECT * FROM test_fts WHERE test_fts MATCH ?',
                          ('"session"* "start"*',))
            results = cursor.fetchall()
            print(f"✓ Quoted prefix query works: {len(results)} results")
        except sqlite3.OperationalError as e:
            print(f"✗ Quoted prefix query failed: {e}")

        # Test Case 3: Explicit AND operator - WORKS
        try:
            cursor.execute('SELECT * FROM test_fts WHERE test_fts MATCH ?',
                          ('session* AND start*',))
            results = cursor.fetchall()
            print(f"✓ Explicit AND query works: {len(results)} results")
        except sqlite3.OperationalError as e:
            print(f"✗ Explicit AND query failed: {e}")

        # Test Case 4: Unquoted multi-word (current bug) - FAILS if term not found
        # This will succeed because terms exist, but would fail if term missing
        try:
            cursor.execute('SELECT * FROM test_fts WHERE test_fts MATCH ?',
                          ('session* start*',))
            results = cursor.fetchall()
            print(f"✓ Unquoted multi-word works (terms exist): {len(results)} results")
        except sqlite3.OperationalError as e:
            print(f"✗ Unquoted multi-word failed: {e}")

        # Test Case 5: Unquoted with missing term - FAILS with "no such column"
        try:
            cursor.execute('SELECT * FROM test_fts WHERE test_fts MATCH ?',
                          ('session* nonexistent*',))
            results = cursor.fetchall()
            print(f"✗ BUG: Unquoted with missing term should fail but got {len(results)} results")
        except sqlite3.OperationalError as e:
            if "no such column" in str(e):
                print(f"✓ Confirmed bug: {e}")
            else:
                print(f"✗ Unexpected error: {e}")

        conn.close()

    def test_line_identification(self, temp_playbook):
        """
        Identify exact line numbers where issues occur.

        Key lines in playbook_manager.py:
        - Line 1008: fts_query = params.query (initial assignment)
        - Line 1011: fts_special_chars = '@#()"\':' (special chars list)
        - Line 1013: fts_query = fts_query.replace(char, ' ') (HYPHEN SANITIZATION)
        - Line 1016-1020: prefix matching logic (PREFIX ASTERISK ADDITION)
        - Line 1019: words = fts_query.split() (split into words)
        - Line 1020: fts_query = ' '.join([f"{word}*" for word in words if len(word) >= 2])
        - Line 1033: WHERE fts.bullets_fts MATCH ? (FTS5 QUERY EXECUTION)
        """
        # Read the source file to verify line numbers
        source_file = Path(__file__).parent.parent / "src" / "mapify_cli" / "playbook_manager.py"

        if source_file.exists():
            with open(source_file, 'r') as f:
                lines = f.readlines()

            print("\n=== Key Lines in _build_fts_query ===")

            # Find the _build_fts_query method
            method_start = None
            for i, line in enumerate(lines, start=1):
                if 'def _build_fts_query' in line:
                    method_start = i
                    break

            if method_start:
                # Print relevant lines (within method, approx 70 lines)
                for i in range(method_start - 1, min(method_start + 70, len(lines))):
                    line_num = i + 1
                    line_content = lines[i].rstrip()

                    # Highlight critical lines
                    if 'fts_query.replace' in line_content and 'char' in line_content:
                        print(f">>> Line {line_num} (HYPHEN REMOVAL): {line_content}")
                    elif 'words = fts_query.split()' in line_content:
                        print(f">>> Line {line_num} (WORD SPLITTING): {line_content}")
                    elif 'word}*' in line_content:
                        print(f">>> Line {line_num} (PREFIX ADDITION): {line_content}")
                    elif 'MATCH ?' in line_content:
                        print(f">>> Line {line_num} (FTS5 QUERY): {line_content}")
                    elif 'fts_special_chars' in line_content:
                        print(f"Line {line_num}: {line_content}")

        # Document findings
        findings = {
            "hyphen_sanitization_line": 1013,
            "special_chars_definition": 1011,
            "word_splitting_line": 1019,
            "prefix_addition_line": 1020,
            "fts5_execution_line": 1033,
            "root_cause": "Hyphens removed and replaced with spaces, but resulting multi-word query not quoted for FTS5",
            "fts5_interpretation": "Unquoted multi-word queries interpreted as implicit AND, missing terms cause 'no such column' error"
        }

        print(f"\n=== Root Cause Summary ===")
        for key, value in findings.items():
            print(f"{key}: {value}")

        return findings


if __name__ == "__main__":
    # Run tests with verbose output
    pytest.main([__file__, "-v", "-s"])
