"""
Workflow Logger for MAP Framework

Implements comprehensive workflow logging for debugging and analysis.
Part of Phase 1.2 (Подробное логирование) from Context Engineering improvements.

Based on: "Context Engineering for AI Agents: Lessons from Building Manus"
and CONTEXT-ENGINEERING-IMPROVEMENTS.md
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any


@dataclass
class AgentInvocation:
    """Represents a single agent invocation in the workflow"""

    agent_name: str
    timestamp: str
    prompt_preview: str  # Truncated prompt for readability
    response_preview: str  # Truncated response
    duration_ms: Optional[float] = None
    status: str = "success"  # 'success', 'error', 'timeout'
    error_message: Optional[str] = None
    task_id: Optional[str] = None  # For correlation with RecitationManager
    subtask_id: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class MapWorkflowLogger:
    """
    Manages detailed workflow logging for MAP Framework.

    Key features:
    1. JSON Lines format (one JSON object per line) for easy parsing
    2. Logs agent invocations with timestamps, prompts, responses, timing
    3. Optional enable/disable flag for production vs debug mode
    4. Integration with RecitationManager via task_id correlation
    5. All methods are no-ops when disabled

    Storage location: .map/logs/workflow_TIMESTAMP.log
    """

    def __init__(self, project_root: Path, enabled: bool = False):
        """
        Initialize the workflow logger.

        Args:
            project_root: Root directory of the project
            enabled: Whether logging is enabled (default: False for production)
        """
        self.project_root = Path(project_root)
        self.enabled = enabled
        self.map_dir = self.project_root / ".map"
        self.logs_dir = self.map_dir / "logs"
        self.current_log_file: Optional[Path] = None
        self.session_start_time: Optional[datetime] = None
        self.task_id: Optional[str] = None

        # Create .map/logs directory if logging is enabled
        if self.enabled:
            self.logs_dir.mkdir(parents=True, exist_ok=True)

    def start_session(self, task_id: Optional[str] = None) -> Optional[Path]:
        """
        Start a new logging session with a timestamped log file.

        Args:
            task_id: Optional task identifier for correlation with RecitationManager

        Returns:
            Path to the log file if enabled, None otherwise
        """
        if not self.enabled:
            return None

        self.session_start_time = datetime.now()
        self.task_id = task_id

        # Create log file with timestamp
        timestamp = self.session_start_time.strftime("%Y%m%d_%H%M%S")
        log_filename = f"workflow_{timestamp}.log"
        self.current_log_file = self.logs_dir / log_filename

        # Write session start marker
        session_info = {
            "event": "session_start",
            "timestamp": self.session_start_time.isoformat(),
            "task_id": task_id,
            "project_root": str(self.project_root),
        }
        self._write_log_entry(session_info)

        return self.current_log_file

    def end_session(self) -> None:
        """
        End the current logging session.

        Writes session summary and cleans up state.
        """
        if not self.enabled or not self.current_log_file:
            return

        session_end_time = datetime.now()
        duration_seconds = (
            (session_end_time - self.session_start_time).total_seconds()
            if self.session_start_time
            else None
        )

        # Write session end marker
        session_info = {
            "event": "session_end",
            "timestamp": session_end_time.isoformat(),
            "task_id": self.task_id,
            "duration_seconds": duration_seconds,
        }
        self._write_log_entry(session_info)

        # Clean up state
        self.current_log_file = None
        self.session_start_time = None
        self.task_id = None

    def log_agent_invocation(
        self,
        agent_name: str,
        prompt: str,
        response: str,
        duration_ms: Optional[float] = None,
        status: str = "success",
        error_message: Optional[str] = None,
        subtask_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Log an agent invocation with full details.

        Args:
            agent_name: Name of the agent (e.g., 'actor', 'monitor')
            prompt: Full prompt sent to the agent
            response: Full response from the agent
            duration_ms: Execution time in milliseconds
            status: Invocation status ('success', 'error', 'timeout')
            error_message: Error message if status is 'error'
            subtask_id: Current subtask ID for correlation
            metadata: Additional metadata to log
        """
        if not self.enabled:
            return

        # Truncate prompt and response for preview (first 500 chars)
        prompt_preview = self._truncate_text(prompt, max_length=500)
        response_preview = self._truncate_text(response, max_length=1000)

        invocation = AgentInvocation(
            agent_name=agent_name,
            timestamp=datetime.now().isoformat(),
            prompt_preview=prompt_preview,
            response_preview=response_preview,
            duration_ms=duration_ms,
            status=status,
            error_message=error_message,
            task_id=self.task_id,
            subtask_id=subtask_id,
            metadata=metadata or {},
        )

        # Convert to dict and write as JSON line
        log_entry = {
            "event": "agent_invocation",
            "agent_name": invocation.agent_name,
            "timestamp": invocation.timestamp,
            "prompt_preview": invocation.prompt_preview,
            "response_preview": invocation.response_preview,
            "duration_ms": invocation.duration_ms,
            "status": invocation.status,
            "error_message": invocation.error_message,
            "task_id": invocation.task_id,
            "subtask_id": invocation.subtask_id,
            "metadata": invocation.metadata,
        }

        self._write_log_entry(log_entry)

    def log_error(
        self,
        error_message: str,
        agent_name: Optional[str] = None,
        subtask_id: Optional[int] = None,
        stack_trace: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Log an error that occurred during workflow execution.

        Args:
            error_message: Human-readable error message
            agent_name: Name of the agent where error occurred (if applicable)
            subtask_id: Current subtask ID (if applicable)
            stack_trace: Full stack trace (if available)
            metadata: Additional error context
        """
        if not self.enabled:
            return

        log_entry = {
            "event": "error",
            "timestamp": datetime.now().isoformat(),
            "error_message": error_message,
            "agent_name": agent_name,
            "subtask_id": subtask_id,
            "task_id": self.task_id,
            "stack_trace": (
                self._truncate_text(stack_trace, max_length=2000)
                if stack_trace
                else None
            ),
            "metadata": metadata or {},
        }

        self._write_log_entry(log_entry)

    def log_timing(
        self,
        operation_name: str,
        duration_ms: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Log timing information for performance analysis.

        Args:
            operation_name: Name of the operation being timed
            duration_ms: Duration in milliseconds
            metadata: Additional timing context
        """
        if not self.enabled:
            return

        log_entry = {
            "event": "timing",
            "timestamp": datetime.now().isoformat(),
            "operation_name": operation_name,
            "duration_ms": duration_ms,
            "task_id": self.task_id,
            "metadata": metadata or {},
        }

        self._write_log_entry(log_entry)

    def log_event(
        self, event_type: str, message: str, metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log a custom workflow event.

        Args:
            event_type: Type of event (e.g., 'subtask_start', 'decomposition_complete')
            message: Human-readable event message
            metadata: Additional event data
        """
        if not self.enabled:
            return

        log_entry = {
            "event": event_type,
            "timestamp": datetime.now().isoformat(),
            "message": message,
            "task_id": self.task_id,
            "metadata": metadata or {},
        }

        self._write_log_entry(log_entry)

    def _write_log_entry(self, entry: Dict[str, Any]) -> None:
        """
        Write a log entry as a JSON line.

        Args:
            entry: Dictionary to write as JSON
        """
        if not self.enabled or not self.current_log_file:
            return

        try:
            with open(self.current_log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            # Don't fail workflow execution if logging fails
            # Just print to stderr for debugging
            import sys

            print(f"Warning: Failed to write log entry: {e}", file=sys.stderr)

    def _truncate_text(
        self, text: Optional[str], max_length: int = 500
    ) -> Optional[str]:
        """
        Truncate text to maximum length with ellipsis.

        Args:
            text: Text to truncate
            max_length: Maximum length before truncation

        Returns:
            Truncated text or None if input is None
        """
        if text is None:
            return None

        if len(text) <= max_length:
            return text

        return text[:max_length] + "..."

    def get_log_file_path(self) -> Optional[Path]:
        """
        Get the path to the current log file.

        Returns:
            Path to current log file if logging is enabled and session started, None otherwise
        """
        return self.current_log_file if self.enabled else None

    def is_enabled(self) -> bool:
        """
        Check if logging is currently enabled.

        Returns:
            True if logging is enabled, False otherwise
        """
        return self.enabled


# CLI interface for testing and manual log inspection
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python -m mapify_cli.workflow_logger test")
        print("  python -m mapify_cli.workflow_logger parse <log_file>")
        print("\nExamples:")
        print("  # Test logger functionality")
        print("  python -m mapify_cli.workflow_logger test")
        print("\n  # Parse and display log file")
        print(
            "  python -m mapify_cli.workflow_logger parse .map/logs/workflow_20251018_143022.log"
        )
        sys.exit(1)

    command = sys.argv[1]

    if command == "test":
        # Test logger functionality
        logger = MapWorkflowLogger(Path.cwd(), enabled=True)
        log_file = logger.start_session(task_id="test_task_123")
        print(f"Started logging session: {log_file}")

        # Log some test events
        logger.log_event("test_start", "Testing workflow logger")
        logger.log_agent_invocation(
            agent_name="test-agent",
            prompt="This is a test prompt" * 50,  # Long prompt to test truncation
            response="This is a test response" * 50,
            duration_ms=123.45,
            status="success",
            subtask_id=1,
            metadata={"test_key": "test_value"},
        )
        logger.log_error(
            error_message="Test error message",
            agent_name="test-agent",
            subtask_id=1,
            metadata={"error_code": "TEST_001"},
        )
        logger.log_timing("test_operation", 456.78, metadata={"step": "initialization"})
        logger.end_session()

        print(f"\nLog file created: {log_file}")
        print("\nContents:")
        if log_file and log_file.exists():
            print(log_file.read_text())

    elif command == "parse":
        if len(sys.argv) < 3:
            print("Error: parse requires <log_file>")
            sys.exit(1)

        log_file_path = Path(sys.argv[2])
        if not log_file_path.exists():
            print(f"Error: Log file not found: {log_file_path}")
            sys.exit(1)

        # Parse and pretty-print log file
        print(f"Parsing log file: {log_file_path}\n")
        with open(log_file_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                try:
                    entry = json.loads(line)
                    print(f"--- Entry {line_num} ---")
                    print(json.dumps(entry, indent=2, ensure_ascii=False))
                    print()
                except json.JSONDecodeError as e:
                    print(f"Error parsing line {line_num}: {e}")
                    print(f"Line content: {line}")
                    print()

    else:
        print(f"Error: Unknown command '{command}'")
        print("Run without arguments to see usage")
        sys.exit(1)
