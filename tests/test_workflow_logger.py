"""
Tests for MapWorkflowLogger

Validates workflow logging functionality for MAP Framework Phase 1.2.
"""

import json

import pytest

from mapify_cli.workflow_logger import MapWorkflowLogger


@pytest.fixture
def temp_project(tmp_path):
    """Create a temporary project directory"""
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    return project_dir


@pytest.fixture
def logger_enabled(temp_project):
    """Create an enabled logger instance"""
    return MapWorkflowLogger(temp_project, enabled=True)


@pytest.fixture
def logger_disabled(temp_project):
    """Create a disabled logger instance"""
    return MapWorkflowLogger(temp_project, enabled=False)


class TestLoggerInitialization:
    """Test logger initialization and configuration"""

    def test_enabled_logger_creates_logs_directory(self, logger_enabled):
        """Enabled logger creates .map/logs/ directory"""
        logs_dir = logger_enabled.logs_dir
        assert logs_dir.exists()
        assert logs_dir.is_dir()
        assert logs_dir.name == "logs"

    def test_disabled_logger_no_directory_creation(self, logger_disabled, temp_project):
        """Disabled logger doesn't create logs directory"""
        logs_dir = temp_project / ".map" / "logs"
        assert not logs_dir.exists()

    def test_logger_enabled_flag(self, logger_enabled, logger_disabled):
        """is_enabled() returns correct flag"""
        assert logger_enabled.is_enabled() is True
        assert logger_disabled.is_enabled() is False

    def test_logger_initial_state(self, logger_enabled):
        """Logger starts with clean state"""
        assert logger_enabled.current_log_file is None
        assert logger_enabled.session_start_time is None
        assert logger_enabled.task_id is None


class TestSessionManagement:
    """Test session start/end functionality"""

    def test_start_session_creates_log_file(self, logger_enabled):
        """start_session() creates timestamped log file"""
        log_file = logger_enabled.start_session(task_id="test_task_123")

        assert log_file is not None
        assert log_file.exists()
        assert log_file.parent == logger_enabled.logs_dir
        assert log_file.name.startswith("workflow_")
        assert log_file.name.endswith(".log")

    def test_start_session_writes_start_marker(self, logger_enabled):
        """start_session() writes session_start event"""
        logger_enabled.start_session(task_id="test_task_123")

        assert logger_enabled.current_log_file is not None
        content = logger_enabled.current_log_file.read_text()
        first_line = content.strip().split("\n")[0]
        entry = json.loads(first_line)

        assert entry["event"] == "session_start"
        assert entry["task_id"] == "test_task_123"
        assert "timestamp" in entry
        assert "project_root" in entry

    def test_end_session_writes_end_marker(self, logger_enabled):
        """end_session() writes session_end event with duration"""
        log_file = logger_enabled.start_session(task_id="test_task_123")
        logger_enabled.end_session()

        content = log_file.read_text()
        lines = content.strip().split("\n")
        last_entry = json.loads(lines[-1])

        assert last_entry["event"] == "session_end"
        assert last_entry["task_id"] == "test_task_123"
        assert "duration_seconds" in last_entry
        assert isinstance(last_entry["duration_seconds"], float)

    def test_end_session_cleans_state(self, logger_enabled):
        """end_session() resets logger state"""
        logger_enabled.start_session(task_id="test_task_123")
        logger_enabled.end_session()

        assert logger_enabled.current_log_file is None
        assert logger_enabled.session_start_time is None
        assert logger_enabled.task_id is None

    def test_disabled_logger_start_session_returns_none(self, logger_disabled):
        """Disabled logger start_session() is no-op"""
        log_file = logger_disabled.start_session(task_id="test_task")
        assert log_file is None
        assert logger_disabled.current_log_file is None


class TestAgentInvocationLogging:
    """Test agent invocation logging"""

    def test_log_agent_invocation_basic(self, logger_enabled):
        """log_agent_invocation() writes correct JSON Lines entry"""
        logger_enabled.start_session(task_id="test_task")
        logger_enabled.log_agent_invocation(
            agent_name="test-agent",
            prompt="Test prompt",
            response="Test response",
            duration_ms=123.45,
            status="success",
            subtask_id=1,
        )

        content = logger_enabled.current_log_file.read_text()
        lines = content.strip().split("\n")
        agent_entry = json.loads(lines[1])  # Second line (first is session_start)

        assert agent_entry["event"] == "agent_invocation"
        assert agent_entry["agent_name"] == "test-agent"
        assert agent_entry["prompt_preview"] == "Test prompt"
        assert agent_entry["response_preview"] == "Test response"
        assert agent_entry["duration_ms"] == 123.45
        assert agent_entry["status"] == "success"
        assert agent_entry["task_id"] == "test_task"
        assert agent_entry["subtask_id"] == 1

    def test_prompt_truncation_at_500_chars(self, logger_enabled):
        """Prompts truncated to 500 chars with ellipsis"""
        logger_enabled.start_session()
        long_prompt = "A" * 600  # 600 chars

        logger_enabled.log_agent_invocation(
            agent_name="test-agent", prompt=long_prompt, response="Short response"
        )

        content = logger_enabled.current_log_file.read_text()
        lines = content.strip().split("\n")
        entry = json.loads(lines[1])

        assert len(entry["prompt_preview"]) == 503  # 500 + "..."
        assert entry["prompt_preview"].endswith("...")
        assert entry["prompt_preview"][:500] == long_prompt[:500]

    def test_response_truncation_at_1000_chars(self, logger_enabled):
        """Responses truncated to 1000 chars with ellipsis"""
        logger_enabled.start_session()
        long_response = "B" * 1200  # 1200 chars

        logger_enabled.log_agent_invocation(
            agent_name="test-agent", prompt="Short prompt", response=long_response
        )

        content = logger_enabled.current_log_file.read_text()
        lines = content.strip().split("\n")
        entry = json.loads(lines[1])

        assert len(entry["response_preview"]) == 1003  # 1000 + "..."
        assert entry["response_preview"].endswith("...")

    def test_log_agent_invocation_with_error(self, logger_enabled):
        """log_agent_invocation() handles error status"""
        logger_enabled.start_session()
        logger_enabled.log_agent_invocation(
            agent_name="failing-agent",
            prompt="Prompt",
            response="Error output",
            status="error",
            error_message="Test error occurred",
        )

        content = logger_enabled.current_log_file.read_text()
        lines = content.strip().split("\n")
        entry = json.loads(lines[1])

        assert entry["status"] == "error"
        assert entry["error_message"] == "Test error occurred"

    def test_log_agent_invocation_with_metadata(self, logger_enabled):
        """log_agent_invocation() includes custom metadata"""
        logger_enabled.start_session()
        logger_enabled.log_agent_invocation(
            agent_name="test-agent",
            prompt="Prompt",
            response="Response",
            metadata={"custom_key": "custom_value", "attempt": 2},
        )

        content = logger_enabled.current_log_file.read_text()
        lines = content.strip().split("\n")
        entry = json.loads(lines[1])

        assert entry["metadata"]["custom_key"] == "custom_value"
        assert entry["metadata"]["attempt"] == 2


class TestErrorLogging:
    """Test error logging functionality"""

    def test_log_error_basic(self, logger_enabled):
        """log_error() writes error event"""
        logger_enabled.start_session(task_id="test_task")
        logger_enabled.log_error(
            error_message="Test error occurred", agent_name="test-agent", subtask_id=3
        )

        content = logger_enabled.current_log_file.read_text()
        lines = content.strip().split("\n")
        entry = json.loads(lines[1])

        assert entry["event"] == "error"
        assert entry["error_message"] == "Test error occurred"
        assert entry["agent_name"] == "test-agent"
        assert entry["subtask_id"] == 3
        assert entry["task_id"] == "test_task"

    def test_log_error_with_stack_trace(self, logger_enabled):
        """log_error() handles stack trace truncation"""
        logger_enabled.start_session()
        long_stack_trace = "Line\n" * 500  # Very long stack trace

        logger_enabled.log_error(
            error_message="Error with stack", stack_trace=long_stack_trace
        )

        content = logger_enabled.current_log_file.read_text()
        lines = content.strip().split("\n")
        entry = json.loads(lines[1])

        assert "stack_trace" in entry
        assert entry["stack_trace"].endswith("...")
        assert len(entry["stack_trace"]) <= 2003  # 2000 + "..."


class TestTimingLogging:
    """Test timing/performance logging"""

    def test_log_timing_basic(self, logger_enabled):
        """log_timing() writes timing event"""
        logger_enabled.start_session(task_id="test_task")
        logger_enabled.log_timing(
            operation_name="database_query",
            duration_ms=456.78,
            metadata={"query": "SELECT *"},
        )

        content = logger_enabled.current_log_file.read_text()
        lines = content.strip().split("\n")
        entry = json.loads(lines[1])

        assert entry["event"] == "timing"
        assert entry["operation_name"] == "database_query"
        assert entry["duration_ms"] == 456.78
        assert entry["task_id"] == "test_task"
        assert entry["metadata"]["query"] == "SELECT *"


class TestCustomEventLogging:
    """Test custom event logging"""

    def test_log_event_basic(self, logger_enabled):
        """log_event() writes custom events"""
        logger_enabled.start_session(task_id="test_task")
        logger_enabled.log_event(
            event_type="custom_event",
            message="Something interesting happened",
            metadata={"detail": "value"},
        )

        content = logger_enabled.current_log_file.read_text()
        lines = content.strip().split("\n")
        entry = json.loads(lines[1])

        assert entry["event"] == "custom_event"
        assert entry["message"] == "Something interesting happened"
        assert entry["task_id"] == "test_task"
        assert entry["metadata"]["detail"] == "value"


class TestJSONLinesFormat:
    """Test JSON Lines format compliance"""

    def test_each_entry_is_valid_json(self, logger_enabled):
        """Each line in log file is valid JSON"""
        log_file = logger_enabled.start_session()
        logger_enabled.log_event("event1", "Message 1")
        logger_enabled.log_event("event2", "Message 2")
        logger_enabled.log_event("event3", "Message 3")
        logger_enabled.end_session()

        content = log_file.read_text()
        lines = content.strip().split("\n")

        assert len(lines) == 5  # start + 3 events + end

        for line in lines:
            try:
                json.loads(line)  # Should not raise
            except json.JSONDecodeError:
                pytest.fail(f"Invalid JSON: {line}")

    def test_no_pretty_printing(self, logger_enabled):
        """Log uses compact JSON (no pretty printing)"""
        logger_enabled.start_session()
        logger_enabled.log_event("test", "Test message")

        content = logger_enabled.current_log_file.read_text()
        lines = content.strip().split("\n")

        # Compact JSON should not contain newlines within entries
        for line in lines:
            assert "\n" not in line.strip()


class TestNoOpBehavior:
    """Test that disabled logger is complete no-op"""

    def test_disabled_logger_no_file_creation(self, logger_disabled, temp_project):
        """Disabled logger never creates files"""
        logger_disabled.start_session(task_id="test")
        logger_disabled.log_event("event", "message")
        logger_disabled.log_agent_invocation("agent", "prompt", "response")
        logger_disabled.log_error("error")
        logger_disabled.log_timing("op", 123)
        logger_disabled.end_session()

        logs_dir = temp_project / ".map" / "logs"
        assert not logs_dir.exists()

    def test_disabled_logger_no_side_effects(self, logger_disabled):
        """Disabled logger methods are pure no-ops"""
        # Should all return None or do nothing
        assert logger_disabled.start_session() is None
        assert logger_disabled.log_agent_invocation("a", "p", "r") is None
        assert logger_disabled.log_error("e") is None
        assert logger_disabled.log_timing("o", 1) is None
        assert logger_disabled.log_event("e", "m") is None
        assert logger_disabled.end_session() is None

    def test_get_log_file_path_when_disabled(self, logger_disabled):
        """get_log_file_path() returns None when disabled"""
        assert logger_disabled.get_log_file_path() is None

        logger_disabled.start_session()
        assert logger_disabled.get_log_file_path() is None


class TestLogFileHandling:
    """Test log file path and access"""

    def test_get_log_file_path_when_enabled(self, logger_enabled):
        """get_log_file_path() returns path after start_session()"""
        assert logger_enabled.get_log_file_path() is None

        logger_enabled.start_session()
        log_path = logger_enabled.get_log_file_path()

        assert log_path is not None
        assert log_path.exists()
        assert log_path == logger_enabled.current_log_file

    def test_log_filename_format(self, logger_enabled):
        """Log filename follows workflow_YYYYMMDD_HHMMSS.log format"""
        log_file = logger_enabled.start_session()

        filename = log_file.name
        assert filename.startswith("workflow_")
        assert filename.endswith(".log")

        # Extract timestamp part: workflow_20251018_133022.log -> 20251018_133022
        timestamp_part = filename[9:-4]
        assert len(timestamp_part) == 15  # YYYYMMDD_HHMMSS
        assert timestamp_part[8] == "_"  # Separator


class TestEdgeCases:
    """Test edge cases and error handling"""

    def test_unicode_in_logs(self, logger_enabled):
        """Logger handles Unicode characters correctly"""
        logger_enabled.start_session()
        logger_enabled.log_event("test", "Тест сообщение with émojis 🎉")

        content = logger_enabled.current_log_file.read_text(encoding="utf-8")
        lines = content.strip().split("\n")
        entry = json.loads(lines[1])

        assert "Тест сообщение" in entry["message"]
        assert "🎉" in entry["message"]

    def test_empty_string_truncation(self, logger_enabled):
        """_truncate_text handles empty strings"""
        assert logger_enabled._truncate_text("", 100) == ""
        assert logger_enabled._truncate_text(None, 100) is None

    def test_exact_length_no_truncation(self, logger_enabled):
        """Text at exactly max_length is not truncated"""
        text_500 = "A" * 500
        result = logger_enabled._truncate_text(text_500, 500)
        assert result == text_500
        assert not result.endswith("...")

    def test_multiple_sessions_different_files(self, logger_enabled):
        """Multiple sessions create different log files"""
        import time

        log_file_1 = logger_enabled.start_session(task_id="task1")
        logger_enabled.end_session()

        time.sleep(1)  # Ensure different timestamp

        log_file_2 = logger_enabled.start_session(task_id="task2")
        logger_enabled.end_session()

        assert log_file_1 != log_file_2
        assert log_file_1.exists()
        assert log_file_2.exists()
