"""
Unit tests for inject_playbook_bullets.py helper script.

Tests keyword extraction, playbook querying, bullet formatting,
and integration flow with mocked subprocess calls.
"""

import json
import pytest
import subprocess
from unittest.mock import Mock, patch, ANY
import sys
import os

# Add helpers directory to path
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", ".claude", "hooks", "helpers")
)

from inject_playbook_bullets import (
    extract_keywords,
    query_playbook,
    format_bullets_as_markdown,
    main,
)


class TestExtractKeywords:
    """Test keyword extraction from user messages"""

    def test_empty_string(self):
        """Empty string returns empty keywords"""
        result = extract_keywords("")
        assert result == ""

    def test_all_stop_words(self):
        """Message with only stop words returns empty"""
        result = extract_keywords("the and or but in on at to for of with")
        assert result == ""

    def test_special_characters_removed(self):
        """Special characters and punctuation are stripped"""
        result = extract_keywords("hello, world! test?")
        assert "hello" in result
        assert "world" in result
        assert "test" in result
        assert "," not in result
        assert "!" not in result
        assert "?" not in result

    def test_long_message(self):
        """Long messages are truncated to max_keywords"""
        words = " ".join([f"keyword{i}" for i in range(20)])
        result = extract_keywords(words, max_keywords=5)
        keywords = result.split()
        assert len(keywords) == 5

    def test_mixed_case_handling(self):
        """Mixed case is normalized to lowercase"""
        result = extract_keywords("PyTest Testing Framework")
        assert "pytest" in result
        assert "testing" in result
        assert "framework" in result

    def test_unicode_characters(self):
        """Unicode characters are preserved"""
        result = extract_keywords("тест привет мир")
        assert "тест" in result
        assert "привет" in result
        assert "мир" in result

    def test_duplicate_words_deduplicated(self):
        """Duplicate words appear only once"""
        result = extract_keywords("test test test function function")
        keywords = result.split()
        assert keywords.count("test") == 1
        assert keywords.count("function") == 1

    def test_max_keywords_limit_enforced(self):
        """Max keywords limit is enforced"""
        message = "one two three four five six seven eight"
        result = extract_keywords(message, max_keywords=3)
        keywords = result.split()
        assert len(keywords) == 3
        assert keywords == ["one", "two", "three"]

    def test_short_words_filtered(self):
        """Words with 2 or fewer characters are filtered"""
        result = extract_keywords("a be cat dog ok yes")
        keywords = result.split()
        assert "a" not in keywords
        assert "be" not in keywords
        assert "ok" not in keywords
        assert "cat" in keywords
        assert "dog" in keywords
        assert "yes" in keywords

    def test_realistic_user_message(self):
        """Realistic user message extracts meaningful keywords"""
        message = "Please help me implement JWT authentication with refresh tokens"
        result = extract_keywords(message)
        keywords = result.split()
        assert "implement" in keywords
        assert "jwt" in keywords
        assert "authentication" in keywords
        assert "refresh" in keywords
        assert "tokens" in keywords
        # Stop words should be filtered
        assert "help" not in keywords
        assert "with" not in keywords


class TestQueryPlaybook:
    """Test playbook querying via mapify CLI"""

    @patch("subprocess.run")
    def test_successful_query(self, mock_run):
        """Successful query returns parsed JSON"""
        mock_response = {
            "results": [
                {
                    "id": "impl-0001",
                    "section": "IMPLEMENTATION_PATTERNS",
                    "content": "Test pattern",
                    "quality_score": 5,
                    "relevance_score": 0.85,
                }
            ]
        }

        mock_run.return_value = Mock(
            returncode=0, stdout=json.dumps(mock_response), stderr=""
        )

        result = query_playbook("test query", limit=5)

        assert result is not None
        assert "results" in result
        assert len(result["results"]) == 1
        assert result["results"][0]["id"] == "impl-0001"

        # Verify command called correctly
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "mapify"
        assert args[1] == "playbook"
        assert args[2] == "query"
        assert args[3] == "test query"
        assert "--format" in args
        assert "json" in args
        assert "--limit" in args
        assert "5" in args

    @patch("subprocess.run")
    def test_cli_failure(self, mock_run):
        """CLI failure returns None"""
        mock_run.return_value = Mock(
            returncode=1, stdout="", stderr="Error: playbook not found"
        )

        result = query_playbook("test query")
        assert result is None

    @patch("subprocess.run")
    def test_timeout_exception(self, mock_run):
        """Timeout exception returns None"""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["mapify"], timeout=10)

        result = query_playbook("test query")
        assert result is None

    @patch("subprocess.run")
    def test_json_parse_error(self, mock_run):
        """Invalid JSON returns None"""
        mock_run.return_value = Mock(
            returncode=0, stdout="This is not valid JSON", stderr=""
        )

        result = query_playbook("test query")
        assert result is None

    @patch("subprocess.run")
    def test_empty_results(self, mock_run):
        """Empty results list is valid"""
        mock_response = {"results": []}

        mock_run.return_value = Mock(
            returncode=0, stdout=json.dumps(mock_response), stderr=""
        )

        result = query_playbook("test query")
        assert result is not None
        assert result["results"] == []

    @patch("subprocess.run")
    def test_timeout_parameter(self, mock_run):
        """Timeout parameter is passed to subprocess"""
        mock_run.return_value = Mock(returncode=0, stdout='{"results": []}', stderr="")

        query_playbook("test", limit=3)

        # Check timeout was set
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["timeout"] == 10


class TestFormatBulletsAsMarkdown:
    """Test bullet formatting for injection"""

    def test_empty_results(self):
        """Empty results returns empty string"""
        result = format_bullets_as_markdown([])
        assert result == ""

    def test_single_result(self):
        """Single result is formatted correctly"""
        results = [
            {
                "id": "impl-0001",
                "section": "IMPLEMENTATION_PATTERNS",
                "content": "Test pattern content",
                "quality_score": 5,
                "relevance_score": 0.85,
            }
        ]

        markdown = format_bullets_as_markdown(results)

        assert "# Relevant Playbook Patterns" in markdown
        assert "[impl-0001]" in markdown
        assert "IMPLEMENTATION_PATTERNS" in markdown
        assert "Test pattern content" in markdown
        assert "Quality: 5/10" in markdown
        assert "Relevance: 0.85" in markdown

    def test_multiple_results(self):
        """Multiple results are numbered and separated"""
        results = [
            {
                "id": "impl-0001",
                "section": "IMPLEMENTATION_PATTERNS",
                "content": "Pattern 1",
                "quality_score": 5,
                "relevance_score": 0.85,
            },
            {
                "id": "sec-0002",
                "section": "SECURITY_PATTERNS",
                "content": "Pattern 2",
                "quality_score": 8,
                "relevance_score": 0.92,
            },
        ]

        markdown = format_bullets_as_markdown(results)

        assert "## 1. [impl-0001]" in markdown
        assert "## 2. [sec-0002]" in markdown
        assert "Pattern 1" in markdown
        assert "Pattern 2" in markdown
        assert markdown.count("---") == 2  # Separators

    def test_missing_fields_handled(self):
        """Missing fields use defaults"""
        results = [
            {
                # Missing id, section, quality_score, relevance_score
                "content": "Test content"
            }
        ]

        markdown = format_bullets_as_markdown(results)

        assert "[unknown]" in markdown
        assert "GENERAL" in markdown
        assert "Test content" in markdown
        assert "Quality: 0/10" in markdown
        assert "Relevance: 0.00" in markdown

    def test_with_code_example(self):
        """Code example is included when present"""
        results = [
            {
                "id": "impl-0001",
                "section": "IMPLEMENTATION_PATTERNS",
                "content": "Pattern with code",
                "code_example": "def foo():\n    return 42",
                "quality_score": 5,
                "relevance_score": 0.85,
            }
        ]

        markdown = format_bullets_as_markdown(results)

        assert "**Example:**" in markdown
        assert "def foo():" in markdown
        assert "return 42" in markdown

    def test_without_code_example(self):
        """No code example section when missing"""
        results = [
            {
                "id": "impl-0001",
                "section": "IMPLEMENTATION_PATTERNS",
                "content": "Pattern without code",
                "quality_score": 5,
                "relevance_score": 0.85,
            }
        ]

        markdown = format_bullets_as_markdown(results)

        assert "**Example:**" not in markdown

    def test_empty_code_example_ignored(self):
        """Empty code example is not displayed"""
        results = [
            {
                "id": "impl-0001",
                "section": "IMPLEMENTATION_PATTERNS",
                "content": "Pattern",
                "code_example": "",
                "quality_score": 5,
                "relevance_score": 0.85,
            }
        ]

        markdown = format_bullets_as_markdown(results)

        assert "**Example:**" not in markdown

    def test_quality_and_relevance_formatting(self):
        """Quality and relevance scores are formatted correctly"""
        results = [
            {
                "id": "impl-0001",
                "section": "IMPLEMENTATION_PATTERNS",
                "content": "Test",
                "quality_score": 7,
                "relevance_score": 0.9234,
            }
        ]

        markdown = format_bullets_as_markdown(results)

        assert "Quality: 7/10" in markdown
        assert "Relevance: 0.92" in markdown  # Two decimal places


class TestMainFunction:
    """Test main integration function"""

    @patch("sys.argv", ["inject_playbook_bullets.py", "--message", "test message"])
    @patch("inject_playbook_bullets.query_playbook")
    def test_full_flow_with_results(self, mock_query, capsys):
        """Full flow with results outputs correct JSON"""
        mock_query.return_value = {
            "results": [
                {
                    "id": "impl-0001",
                    "section": "IMPLEMENTATION_PATTERNS",
                    "content": "Test pattern",
                    "quality_score": 5,
                    "relevance_score": 0.85,
                }
            ]
        }

        exit_code = main()

        assert exit_code == 0

        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert output["continue"] is True
        assert "additionalContext" in output
        assert "Test pattern" in output["additionalContext"]

    @patch("sys.argv", ["inject_playbook_bullets.py", "--message", "a b c"])
    def test_empty_keywords_case(self, capsys):
        """Empty keywords returns continue without context"""
        exit_code = main()

        assert exit_code == 0

        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert output["continue"] is True
        assert "additionalContext" not in output

    @patch("sys.argv", ["inject_playbook_bullets.py", "--message", "test message"])
    @patch("inject_playbook_bullets.query_playbook")
    def test_no_query_results(self, mock_query, capsys):
        """No query results returns continue without context"""
        mock_query.return_value = None

        exit_code = main()

        assert exit_code == 0

        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert output["continue"] is True
        assert "additionalContext" not in output

    @patch("sys.argv", ["inject_playbook_bullets.py", "--message", "test message"])
    @patch("inject_playbook_bullets.query_playbook")
    def test_empty_results_list(self, mock_query, capsys):
        """Empty results list returns continue without context"""
        mock_query.return_value = {"results": []}

        exit_code = main()

        assert exit_code == 0

        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert output["continue"] is True
        assert "additionalContext" not in output

    @patch(
        "sys.argv",
        ["inject_playbook_bullets.py", "--message", "test message", "--limit", "3"],
    )
    @patch("inject_playbook_bullets.query_playbook")
    def test_custom_limit_parameter(self, mock_query):
        """Custom limit parameter is passed through"""
        mock_query.return_value = {"results": []}

        main()

        mock_query.assert_called_once_with(ANY, 3)

    @patch("sys.argv", ["inject_playbook_bullets.py", "--message", "test"])
    @patch("inject_playbook_bullets.query_playbook")
    def test_fatal_error_handling(self, mock_query, capsys):
        """Fatal errors are propagated from main() (caught by __main__ wrapper)"""
        mock_query.side_effect = Exception("Unexpected error")

        # main() doesn't catch exceptions internally - they're caught by __main__ wrapper
        # Test that exception propagates as expected
        with pytest.raises(Exception, match="Unexpected error"):
            main()
