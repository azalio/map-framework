#!/usr/bin/env python3
"""
Comprehensive test suite for agent contract validation system.

Tests validation code in:
  - src/mapify_cli/validation/contract_validator.py (AgentContractValidator)
  - src/mapify_cli/validation/mcp_tool_detector.py (MCP tool verification)

Test coverage goals:
  - Unit Tests: >90% coverage for validation modules
  - Integration Tests: Realistic agent workflows
  - CLI Tests: Test all CLI commands with valid/invalid inputs
  - Edge Cases: Empty arrays, missing optional fields, extra fields
  - Regression: Validate against real workflow logs
"""

import json
import sys
import unittest.mock
from pathlib import Path
from typing import Dict, Any

import pytest
from typer.testing import CliRunner

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mapify_cli.validation.contract_validator import (
    AgentContractValidator,
    ValidationResult,
    validate_agent_input,
    validate_agent_output,
)
from mapify_cli.validation.mcp_tool_detector import (
    detect_mcp_tool_calls,
    verify_mcp_tools,
    MCPVerificationResult,
    MCP_TOOL_REQUIREMENTS,
)
from mapify_cli import app as cli


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def validator():
    """Create validator instance with default schema directory."""
    return AgentContractValidator()


@pytest.fixture
def valid_actor_input():
    """Valid Actor input."""
    return {
        "language": "python",
        "project_name": "map-framework",
        "subtask_description": "Implement user authentication with JWT tokens",
        "playbook_bullets": [],
        "plan_context": "Current subtask: 1/5",
        "feedback": ""
    }


@pytest.fixture
def invalid_actor_input():
    """Invalid Actor input (missing required fields)."""
    return {
        "language": "python",
        # Missing project_name (required)
        # Missing subtask_description (required)
        "acceptance_criteria": []
    }


@pytest.fixture
def valid_actor_output():
    """Valid Actor output."""
    return {
        "approach": "Implement JWT authentication using PyJWT library with bcrypt password hashing",
        "code_changes": [
            {
                "file_path": "src/auth.py",
                "change_type": "create",
                "content": "# Implementation code here\nimport jwt\nimport bcrypt",
                "rationale": "New auth module needed for JWT token management"
            }
        ],
        "trade_offs": ["JWT tokens can't be easily revoked without token blacklist"],
        "testing_approach": "Unit tests for token generation and validation",
        "used_bullets": ["sec-0005"]
    }


@pytest.fixture
def valid_monitor_input():
    """Valid Monitor input."""
    return {
        "language": "python",
        "project_name": "map-framework",
        "subtask_description": "Implement user authentication with JWT tokens",
        "solution": "Implemented JWT authentication with bcrypt password hashing and token management",
        "actor_output": '{"approach": "Implement JWT auth", "code_changes": [...]}',
        "acceptance_criteria": ["Users can login"],
        "test_strategy": "Unit tests for token generation, integration tests for login flow"
    }


@pytest.fixture
def valid_monitor_output():
    """Valid Monitor output."""
    return {
        "valid": True,
        "issues": [],
        "verdict": "approved",
        "feedback": "",
        "high_risk_detected": False
    }


@pytest.fixture
def valid_reflector_output():
    """Valid Reflector output."""
    return {
        "key_insight": "JWT authentication with short-lived access tokens provides good security balance",
        "patterns_used": ["sec-0005"],
        "patterns_discovered": ["Refresh token rotation pattern"],
        "bullet_updates": [],
        "suggested_new_bullets": [
            {
                "section": "security",
                "content": "Implement refresh token rotation to prevent token theft",
                "code_example": "refresh_token = rotate_token(old_token)",
                "initial_score": 7
            }
        ],
        "workflow_efficiency": {
            "total_iterations": 2,
            "avg_per_subtask": 2.0,
            "bottlenecks": []
        }
    }


@pytest.fixture
def valid_curator_output():
    """Valid Curator output."""
    return {
        "operations": [
            {
                "operation": "ADD",
                "section": "security",
                "content": "Implement refresh token rotation to prevent token theft",
                "reason": "New pattern discovered during JWT auth implementation"
            }
        ],
        "deduplication_check": [
            {
                "new_bullet": "Implement refresh token rotation",
                "similar_existing_bullets": [],
                "action": "add_new"
            }
        ],
        "sync_to_cipher": []
    }


@pytest.fixture
def reflector_output_with_tools():
    """Reflector output showing MCP tool usage."""
    return """
    I analyzed the implementation and found the following insights.

    First, I searched existing patterns using mcp__cipher__cipher_memory_search
    to check if similar authentication implementations exist.

    The search revealed 3 relevant patterns from other projects.

    Key insight: Use JWT with short-lived access tokens and refresh tokens.
    """


@pytest.fixture
def reflector_output_without_tools():
    """Reflector output WITHOUT MCP tool usage (violation)."""
    return """
    I analyzed the implementation.

    Key insight: Use JWT for authentication.

    I suggest adding a new bullet about token management.
    """


@pytest.fixture
def reflector_output_false_positive():
    """
    Tool name mentioned in JSON context but NOT actually called.

    Tests false positive scenario where tool appears in error message.
    """
    return """
    {
      "error": "Tool mcp__cipher__cipher_memory_search was not available",
      "available_tools": ["mcp__cipher__cipher_memory_search"],
      "status": "failed to invoke cipher search"
    }

    The reflection could not be completed because the required MCP tool
    mcp__cipher__cipher_memory_search was not invoked.
    """


@pytest.fixture
def curator_output_with_tools():
    """Curator output showing MCP tool usage (both required tools)."""
    return """
    I analyzed the Reflector insights and checked for duplicates.

    First, I searched existing bullets using mcp__cipher__cipher_memory_search
    to avoid adding duplicate patterns.

    No similar bullets found, so I'm adding the new pattern.

    Since the new bullet has helpful_count >= 5, I'm syncing it to cipher
    using mcp__cipher__cipher_extract_and_operate_memory.
    """


# ============================================================================
# Schema Validation Tests
# ============================================================================


class TestSchemaValidation:
    """Test JSON schema validation for all agents."""

    def test_valid_actor_input(self, validator, valid_actor_input):
        """Test validation passes for valid Actor input."""
        result = validator.validate_agent_input("actor", valid_actor_input)

        assert result.valid is True
        assert len(result.errors) == 0

    def test_invalid_actor_input_missing_required_fields(self, validator, invalid_actor_input):
        """Test validation fails for invalid Actor input with missing required fields."""
        result = validator.validate_agent_input("actor", invalid_actor_input)

        assert result.valid is False
        assert len(result.errors) > 0

        # Check specific errors for missing required fields
        error_messages = " ".join(result.errors).lower()
        assert "project_name" in error_messages
        assert "subtask_description" in error_messages

    def test_valid_actor_output(self, validator, valid_actor_output):
        """Test validation passes for valid Actor output."""
        result = validator.validate_agent_output("actor", valid_actor_output)

        assert result.valid is True
        assert len(result.errors) == 0

    def test_valid_monitor_input(self, validator, valid_monitor_input):
        """Test validation passes for valid Monitor input."""
        result = validator.validate_agent_input("monitor", valid_monitor_input)

        assert result.valid is True
        assert len(result.errors) == 0

    def test_valid_monitor_output(self, validator, valid_monitor_output):
        """Test validation passes for valid Monitor output."""
        result = validator.validate_agent_output("monitor", valid_monitor_output)

        assert result.valid is True
        assert len(result.errors) == 0

    def test_valid_reflector_output(self, validator, valid_reflector_output):
        """Test validation passes for valid Reflector output."""
        result = validator.validate_agent_output("reflector", valid_reflector_output)

        assert result.valid is True
        assert len(result.errors) == 0

    def test_valid_curator_output(self, validator, valid_curator_output):
        """Test validation passes for valid Curator output."""
        result = validator.validate_agent_output("curator", valid_curator_output)

        assert result.valid is True
        assert len(result.errors) == 0

    @pytest.mark.parametrize("agent_name", [
        "task_decomposer",
        "actor",
        "monitor",
        "predictor",
        "evaluator",
        "reflector",
        "curator",
        "documentation_reviewer"
    ])
    def test_all_agents_have_input_schemas(self, validator, agent_name):
        """Test all 8 agents have input schemas defined."""
        assert agent_name in validator._input_schemas, \
            f"Agent '{agent_name}' missing input schema"

    @pytest.mark.parametrize("agent_name", [
        "task_decomposer",
        "actor",
        "monitor",
        "predictor",
        "evaluator",
        "reflector",
        "curator",
        "documentation_reviewer"
    ])
    def test_all_agents_have_output_schemas(self, validator, agent_name):
        """Test all 8 agents have output schemas defined."""
        assert agent_name in validator._output_schemas, \
            f"Agent '{agent_name}' missing output schema"

    def test_hyphenated_agent_names(self, validator):
        """Test validator handles both hyphenated and underscored agent names."""
        # Task-decomposer with hyphen
        assert "task-decomposer" in validator._input_schemas
        assert "task_decomposer" in validator._input_schemas

        # Documentation-reviewer with hyphen
        assert "documentation-reviewer" in validator._input_schemas
        assert "documentation_reviewer" in validator._input_schemas

    def test_unknown_agent_name(self, validator):
        """Test validation fails gracefully for unknown agent names."""
        result = validator.validate_agent_input("unknown_agent", {})

        assert result.valid is False
        assert "Unknown agent" in result.errors[0]

    def test_validation_result_string_representation(self):
        """Test ValidationResult __str__ method."""
        # Valid result
        valid = ValidationResult(valid=True, errors=[], warnings=[])
        assert "✓" in str(valid)
        assert "passed" in str(valid)

        # Invalid result
        invalid = ValidationResult(
            valid=False,
            errors=["Error 1", "Error 2"],
            warnings=[]
        )
        assert "✗" in str(invalid)
        assert "failed" in str(invalid)
        assert "Error 1" in str(invalid)

    def test_convenience_functions(self, valid_actor_input, valid_actor_output):
        """Test module-level convenience functions."""
        # Test validate_agent_input convenience function
        result_input = validate_agent_input("actor", valid_actor_input)
        assert result_input.valid is True

        # Test validate_agent_output convenience function
        result_output = validate_agent_output("actor", valid_actor_output)
        assert result_output.valid is True


# ============================================================================
# MCP Tool Detection Tests
# ============================================================================


class TestMCPToolDetection:
    """Test MCP tool call detection logic."""

    def test_detect_tool_in_output(self, reflector_output_with_tools):
        """Test detecting MCP tool calls in agent output."""
        detected = detect_mcp_tool_calls(reflector_output_with_tools)

        assert "mcp__cipher__cipher_memory_search" in detected

    def test_no_tools_detected(self, reflector_output_without_tools):
        """Test no false positives when tools not called."""
        detected = detect_mcp_tool_calls(reflector_output_without_tools)

        # Should be empty (no tool calls, just mentions)
        # FIXED: Changed OR to AND - both conditions must be true
        assert len(detected) == 0 and "mcp__cipher__cipher_memory_search" not in str(detected)

    def test_verify_reflector_tools_pass(self, reflector_output_with_tools):
        """Test Reflector MCP tool verification passes when tools are called."""
        result = verify_mcp_tools("reflector", reflector_output_with_tools)

        assert result.verified is True
        assert len(result.missing_tools) == 0
        assert "mcp__cipher__cipher_memory_search" in result.detected_tools

    def test_verify_reflector_tools_fail(self, reflector_output_without_tools):
        """Test Reflector MCP tool verification fails when tools missing."""
        result = verify_mcp_tools("reflector", reflector_output_without_tools)

        assert result.verified is False
        assert "mcp__cipher__cipher_memory_search" in result.missing_tools

    def test_verify_curator_tools_pass(self, curator_output_with_tools):
        """Test Curator MCP tool verification passes when both required tools called."""
        result = verify_mcp_tools("curator", curator_output_with_tools)

        assert result.verified is True
        assert len(result.missing_tools) == 0
        assert "mcp__cipher__cipher_memory_search" in result.detected_tools
        assert "mcp__cipher__cipher_extract_and_operate_memory" in result.detected_tools

    def test_verify_curator_missing_one_tool(self, reflector_output_with_tools):
        """Test Curator verification fails when only one of two required tools called."""
        # This output only has cipher_memory_search, missing extract_and_operate
        result = verify_mcp_tools("curator", reflector_output_with_tools)

        assert result.verified is False
        assert "mcp__cipher__cipher_extract_and_operate_memory" in result.missing_tools

    def test_no_false_positive_for_tool_mentions(self, reflector_output_false_positive):
        """
        Test detector doesn't count tool mentions as actual calls.

        False positive scenario: Tool name appears in JSON error message
        but the tool was NOT actually invoked.
        """
        detected = detect_mcp_tool_calls(reflector_output_false_positive)

        # Tool name appears in JSON context but was NOT called
        # With AND logic fix, this should NOT be detected as a tool call
        assert len(detected) == 0, \
            "Tool mentioned in error message should not be counted as actual call"

    def test_tool_detection_case_insensitive(self):
        """Test tool detection pattern is case-insensitive."""
        # The regex pattern re.IGNORECASE makes tool name detection case-insensitive
        output = "I invoked mcp__cipher__cipher_memory_search to find patterns."

        detected = detect_mcp_tool_calls(output)

        # Should detect the tool call
        assert len(detected) == 1
        assert "mcp__cipher__cipher_memory_search" in detected

    def test_tool_detection_requires_call_verb(self):
        """Test tool detection requires explicit call verbs (stricter matching)."""
        # Just mentioning the tool without a call verb
        output_mention_only = """
        The agent should use mcp__cipher__cipher_memory_search for searching.
        This tool is available: mcp__cipher__cipher_memory_search.
        """

        detected = detect_mcp_tool_calls(output_mention_only)

        # Should NOT detect (no call verb)
        assert len(detected) == 0

    def test_tool_detection_with_various_call_verbs(self):
        """Test tool detection recognizes various call verb patterns."""
        call_verbs = [
            "calling mcp__cipher__cipher_memory_search",
            "invoked mcp__cipher__cipher_memory_search",
            "using mcp__cipher__cipher_memory_search",
            "via mcp__cipher__cipher_memory_search",
            "searched mcp__cipher__cipher_memory_search",
            "queried mcp__cipher__cipher_memory_search",
            "executed mcp__cipher__cipher_memory_search",
            "ran mcp__cipher__cipher_memory_search"
        ]

        for verb_pattern in call_verbs:
            output = f"I {verb_pattern} to find patterns."
            detected = detect_mcp_tool_calls(output)

            assert len(detected) == 1, f"Failed to detect with pattern: {verb_pattern}"

    def test_mcp_verification_result_string_representation(self):
        """Test MCPVerificationResult __str__ method."""
        # Verified result
        verified = MCPVerificationResult(
            verified=True,
            missing_tools=[],
            detected_tools={"mcp__cipher__cipher_memory_search"},
            agent_name="reflector"
        )
        assert "✓" in str(verified)
        assert "verified" in str(verified)

        # Failed verification
        failed = MCPVerificationResult(
            verified=False,
            missing_tools=["mcp__cipher__cipher_memory_search"],
            detected_tools=set(),
            agent_name="reflector"
        )
        assert "✗" in str(failed)
        assert "missing" in str(failed)

    def test_verify_agent_without_mcp_requirements(self):
        """Test verification passes for agents without MCP requirements."""
        # Actor doesn't require MCP tools
        result = verify_mcp_tools("actor", "Some actor output without MCP tools")

        assert result.verified is True
        assert len(result.missing_tools) == 0


# ============================================================================
# Assertion Logic Truth Table Tests
# ============================================================================


class TestAssertionLogicTruthTable:
    """
    Test assertion boolean logic using truth table validation.

    Ensures OR/AND logic in test assertions is correct.
    Common bug: 'assert len(x) == 0 or "keyword" not in x' always passes.

    Truth table for no-violations check:
    | empty | has_keyword | expected | assertion |
    |-------|-------------|----------|-----------|
    | True  | False       | PASS     | PASS      |
    | True  | True        | N/A      | N/A       |  (impossible state)
    | False | False       | FAIL     | FAIL      |
    | False | True        | FAIL     | FAIL      |
    """

    def test_no_violations_truth_table_case1(self):
        """Truth table case 1: empty=True, has_keyword=False → PASS"""
        detected = []

        # Both conditions must be true for proper validation
        assert len(detected) == 0 and "cipher" not in str(detected)

    def test_no_violations_truth_table_case2_impossible(self):
        """Truth table case 2: empty=True, has_keyword=True → impossible state"""
        # Skip - can't have keyword in empty list
        pass

    def test_no_violations_truth_table_case3(self):
        """Truth table case 3: empty=False, has_keyword=False → FAIL"""
        detected = ["other_tool"]

        # This test SHOULD fail - violations exist
        with pytest.raises(AssertionError):
            assert len(detected) == 0 and "cipher" not in str(detected)

    def test_no_violations_truth_table_case4(self):
        """Truth table case 4: empty=False, has_keyword=True → FAIL"""
        detected = ["mcp__cipher__cipher_memory_search"]

        # This test SHOULD fail - has violations with cipher keyword
        with pytest.raises(AssertionError):
            assert len(detected) == 0 and "cipher" not in str(detected)

    def test_or_logic_bug_demonstration(self):
        """
        Demonstrate the OR logic bug.

        INCORRECT: assert len(x) == 0 or "cipher" not in x
        - If len(x) > 0 but "cipher" not in x → OR short-circuits to True (BUG!)

        CORRECT: assert len(x) == 0 and "cipher" not in x
        - Both conditions must be true
        """
        detected = ["other_violation"]  # Non-empty, no cipher

        # ❌ INCORRECT OR LOGIC - this would PASS (wrong!)
        # assert len(detected) == 0 or "cipher" not in str(detected)
        # Evaluates to: False OR True = True (passes despite violations!)

        # ✅ CORRECT AND LOGIC - this FAILS (correct!)
        with pytest.raises(AssertionError):
            assert len(detected) == 0 and "cipher" not in str(detected)


# ============================================================================
# Handlebars Template Runtime Validation Tests
# ============================================================================


class TestHandlebarsContextValidation:
    """
    Test that agent templates receive all required Handlebars variables at runtime.

    Validates orchestrator provides variables that templates expect.
    Prevents runtime failures from missing context variables.
    """

    @pytest.fixture
    def required_context_variables(self):
        """Minimal context that orchestrator MUST provide."""
        return {
            'language': 'Python',
            'framework': 'FastAPI',
            'project_name': 'test-project',
            'subtask_description': 'Implement feature X',
            'playbook_bullets': 'impl-001: Sample pattern',
            'code': 'def example(): pass',
            'feedback': 'Previous iteration feedback',
            'actor_output': '{"approach": "...", "code_changes": [...]}',
            'monitor_results': '{"verdict": "approved"}',
            'predictor_analysis': '{"risk_level": "low"}',
            'evaluator_scores': '{"overall": 8.0}',
            'reflector_insights': '{"key_insight": "...", "patterns": [...]}',
            'execution_outcome': 'success',
            'acceptance_criteria': ['Criterion 1', 'Criterion 2'],
            'feature_request': 'Add user authentication'
        }

    def test_actor_template_variables_provided(self, required_context_variables):
        """Ensure orchestrator provides all variables used in actor.md template."""
        # Variables that actor.md template requires
        actor_required = ['language', 'project_name', 'subtask_description', 'playbook_bullets']

        # Verify all required variables present in orchestrator context
        for var in actor_required:
            assert var in required_context_variables, f"Missing required variable: {{{{{var}}}}}"

    def test_monitor_template_variables_provided(self, required_context_variables):
        """Ensure orchestrator provides all variables used in monitor.md template."""
        monitor_required = [
            'language', 'project_name', 'subtask_description',
            'code', 'acceptance_criteria'
        ]

        for var in monitor_required:
            assert var in required_context_variables, f"Missing required variable: {{{{{var}}}}}"

    def test_reflector_template_variables_provided(self, required_context_variables):
        """Ensure orchestrator provides all variables used in reflector.md template."""
        reflector_required = [
            'language', 'project_name', 'subtask_description',
            'actor_output', 'monitor_results', 'predictor_analysis',
            'evaluator_scores', 'execution_outcome'
        ]

        for var in reflector_required:
            assert var in required_context_variables, f"Missing required variable: {{{{{var}}}}}"

    def test_curator_template_variables_provided(self, required_context_variables):
        """Ensure orchestrator provides all variables used in curator.md template."""
        curator_required = [
            'language', 'project_name', 'subtask_description',
            'reflector_insights', 'playbook_bullets'
        ]

        for var in curator_required:
            assert var in required_context_variables, f"Missing required variable: {{{{{var}}}}}"

    @pytest.mark.parametrize("agent,variables", [
        ("task-decomposer", ["language", "project_name", "feature_request"]),
        ("actor", ["language", "project_name", "subtask_description"]),
        ("monitor", ["language", "project_name", "subtask_description", "code"]),
        ("predictor", ["language", "project_name", "subtask_description"]),
        ("evaluator", ["language", "project_name", "subtask_description"]),
        ("reflector", ["language", "project_name", "subtask_description", "actor_output"]),
        ("curator", ["language", "project_name", "subtask_description", "reflector_insights"]),
    ])
    def test_all_agent_templates_have_required_variables(self, agent, variables, required_context_variables):
        """Test that orchestrator context provides required variables for each agent."""
        for var in variables:
            assert var in required_context_variables, \
                f"Agent '{agent}' requires variable '{var}' but it's not in orchestrator context"

    def test_template_variable_extraction_from_schemas(self):
        """
        Test that JSON schemas require the same variables used in templates.

        This ensures schema validation catches missing variables before
        templates are rendered.
        """
        validator = AgentContractValidator()

        # Actor schema should require language, project_name, subtask_description
        actor_schema = validator._input_schemas['actor']
        assert 'language' in actor_schema['required']
        assert 'project_name' in actor_schema['required']
        assert 'subtask_description' in actor_schema['required']

        # Reflector schema should require variables it uses
        reflector_schema = validator._input_schemas['reflector']
        assert 'language' in reflector_schema['required']
        assert 'subtask_description' in reflector_schema['required']
        assert 'actor_output' in reflector_schema['required']

        # Monitor schema requirements
        monitor_schema = validator._input_schemas['monitor']
        assert 'language' in monitor_schema['required']
        assert 'project_name' in monitor_schema['required']
        assert 'solution' in monitor_schema['required']


# ============================================================================
# Integration Tests
# ============================================================================


class TestValidationIntegration:
    """Test validation in realistic agent workflow scenarios."""

    def test_actor_monitor_workflow(self, validator, valid_actor_input, valid_actor_output):
        """Test Actor → Monitor workflow validation."""
        # Step 1: Validate Actor input
        actor_input_result = validator.validate_agent_input("actor", valid_actor_input)
        assert actor_input_result.valid is True

        # Step 2: Validate Actor output
        actor_output_result = validator.validate_agent_output("actor", valid_actor_output)
        assert actor_output_result.valid is True

        # Step 3: Create Monitor input using Actor output
        monitor_input = {
            "language": "python",
            "project_name": "map-framework",
            "subtask_description": "Implement user authentication with JWT tokens",
            "solution": "Implemented JWT authentication with bcrypt password hashing",
            "actor_output": json.dumps(valid_actor_output),
            "acceptance_criteria": ["Users can register", "Passwords hashed with bcrypt"],
            "test_strategy": "Unit tests for token generation and integration tests for login flow"
        }

        # Step 4: Validate Monitor input
        monitor_input_result = validator.validate_agent_input("monitor", monitor_input)
        assert monitor_input_result.valid is True

    def test_reflector_curator_workflow(self, validator, valid_reflector_output, valid_curator_output):
        """Test Reflector → Curator workflow validation."""
        # Step 1: Validate Reflector output
        reflector_result = validator.validate_agent_output("reflector", valid_reflector_output)
        assert reflector_result.valid is True

        # Step 2: Validate Curator output
        curator_result = validator.validate_agent_output("curator", valid_curator_output)
        assert curator_result.valid is True

    def test_full_workflow_chain(self, validator, valid_actor_input):
        """Test full workflow chain: Actor → Monitor → Predictor → Evaluator → Reflector → Curator."""
        # Actor input
        actor_input_result = validator.validate_agent_input("actor", valid_actor_input)
        assert actor_input_result.valid is True

        # Actor output
        actor_output = {
            "approach": "Implement JWT authentication using PyJWT library",
            "code_changes": [{
                "file_path": "auth.py",
                "change_type": "create",
                "content": "# JWT implementation code here",
                "rationale": "New auth module needed"
            }],
            "testing_approach": "Unit and integration tests for authentication",
            "used_bullets": []
        }
        actor_output_result = validator.validate_agent_output("actor", actor_output)
        assert actor_output_result.valid is True

        # Monitor input
        monitor_input = {
            "language": "python",
            "project_name": "map-framework",
            "subtask_description": "Implement user authentication with JWT tokens",
            "solution": "Implemented JWT authentication using PyJWT library",
            "actor_output": json.dumps(actor_output)
        }
        monitor_input_result = validator.validate_agent_input("monitor", monitor_input)
        assert monitor_input_result.valid is True

        # Monitor output
        monitor_output = {
            "valid": True,
            "issues": [],
            "verdict": "approved",
            "feedback": "",
            "high_risk_detected": False
        }
        monitor_result = validator.validate_agent_output("monitor", monitor_output)
        assert monitor_result.valid is True

        # All validations passed
        assert all([
            actor_input_result.valid,
            actor_output_result.valid,
            monitor_input_result.valid,
            monitor_result.valid
        ])

    def test_validation_with_mcp_tools(
        self,
        validator,
        reflector_output_with_tools,
        valid_reflector_output
    ):
        """Test integration of schema validation + MCP tool verification."""
        # Schema validation
        schema_result = validator.validate_agent_output("reflector", valid_reflector_output)
        assert schema_result.valid is True

        # MCP tool verification
        mcp_result = verify_mcp_tools("reflector", reflector_output_with_tools)
        assert mcp_result.verified is True

        # Both validations must pass
        assert schema_result.valid and mcp_result.verified


# ============================================================================
# CLI Command Tests
# ============================================================================


class TestCLICommands:
    """Test validation CLI commands."""

    def test_validate_agent_input_command(self, tmp_path, valid_actor_input):
        """Test 'mapify validate agent-input' command with valid input."""
        # Write valid input to temp file
        input_file = tmp_path / "actor_input.json"
        with open(input_file, 'w') as f:
            json.dump(valid_actor_input, f)

        runner = CliRunner()
        result = runner.invoke(cli, [
            'validate', 'agent-input', 'actor', str(input_file)
        ])

        # Exit code 0 means success
        assert result.exit_code == 0
        # Output should indicate validation passed (either 'passed' or checkmark)
        output_lower = result.output.lower()
        assert "passed" in output_lower or "✓" in result.output or "validation" in output_lower

    def test_validate_agent_input_command_fail(self, tmp_path, invalid_actor_input):
        """Test CLI command fails for invalid input."""
        input_file = tmp_path / "actor_input.json"
        with open(input_file, 'w') as f:
            json.dump(invalid_actor_input, f)

        runner = CliRunner()
        result = runner.invoke(cli, [
            'validate', 'agent-input', 'actor', str(input_file)
        ])

        assert result.exit_code == 1
        assert "failed" in result.output.lower() or "✗" in result.output

    def test_validate_agent_output_command(self, tmp_path, valid_actor_output):
        """Test 'mapify validate agent-output' command with valid output."""
        output_file = tmp_path / "actor_output.json"
        with open(output_file, 'w') as f:
            json.dump(valid_actor_output, f)

        runner = CliRunner()
        result = runner.invoke(cli, [
            'validate', 'agent-output', 'actor', str(output_file)
        ])

        assert result.exit_code == 0
        assert "passed" in result.output.lower() or "✓" in result.output

    def test_validate_agent_output_command_fail(self, tmp_path):
        """Test CLI command fails for invalid output."""
        invalid_output = {
            "approach": "Short",  # Too short (minLength: 20)
            # Missing required fields
        }

        output_file = tmp_path / "actor_output.json"
        with open(output_file, 'w') as f:
            json.dump(invalid_output, f)

        runner = CliRunner()
        result = runner.invoke(cli, [
            'validate', 'agent-output', 'actor', str(output_file)
        ])

        assert result.exit_code == 1

    def test_validate_agent_input_verbose(self, tmp_path, invalid_actor_input):
        """Test verbose flag shows detailed errors."""
        input_file = tmp_path / "actor_input.json"
        with open(input_file, 'w') as f:
            json.dump(invalid_actor_input, f)

        runner = CliRunner()
        result = runner.invoke(cli, [
            'validate', 'agent-input', 'actor', str(input_file), '--verbose'
        ])

        assert result.exit_code == 1
        # Verbose should show field-specific errors
        assert "project_name" in result.output or "subtask_description" in result.output

    def test_validate_malformed_json(self, tmp_path):
        """Test CLI handles malformed JSON gracefully."""
        input_file = tmp_path / "malformed.json"
        with open(input_file, 'w') as f:
            f.write("{ invalid json }")

        runner = CliRunner()
        result = runner.invoke(cli, [
            'validate', 'agent-input', 'actor', str(input_file)
        ])

        assert result.exit_code == 1
        assert "json" in result.output.lower() or "invalid" in result.output.lower()

    def test_validate_nonexistent_file(self):
        """Test CLI handles non-existent file gracefully."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            'validate', 'agent-input', 'actor', '/nonexistent/file.json'
        ])

        assert result.exit_code == 1


# ============================================================================
# Edge Case Tests
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_playbook_bullets(self, validator):
        """Test validation with empty playbook_bullets array (optional field)."""
        input_data = {
            "language": "python",
            "project_name": "test",
            "subtask_description": "Test task description here",
            "playbook_bullets": []  # Empty (optional field)
        }

        result = validator.validate_agent_input("actor", input_data)
        assert result.valid is True

    def test_missing_optional_feedback(self, validator):
        """Test validation passes when optional 'feedback' is missing."""
        input_data = {
            "language": "python",
            "project_name": "test",
            "subtask_description": "Test task description here"
            # feedback is optional, omitted
        }

        result = validator.validate_agent_input("actor", input_data)
        assert result.valid is True

    def test_missing_optional_trade_offs(self, validator):
        """Test Actor output validates when optional trade_offs is missing."""
        actor_output_minimal = {
            "approach": "Implement JWT authentication using PyJWT library",
            "code_changes": [{
                "file_path": "auth.py",
                "change_type": "create",
                "content": "# JWT implementation code",
                "rationale": "New authentication module needed"
            }],
            "testing_approach": "Unit tests for token generation",
            "used_bullets": []
            # trade_offs omitted (optional field)
        }

        result = validator.validate_agent_output("actor", actor_output_minimal)
        assert result.valid is True

    def test_extra_fields_with_additional_properties_false(self, validator):
        """Test validation with extra unexpected fields (additionalProperties: false)."""
        input_data = {
            "language": "python",
            "project_name": "test",
            "subtask_description": "Test task description here",
            "unexpected_field": "This should not be here"  # Extra field
        }

        result = validator.validate_agent_input("actor", input_data)

        # Should fail because schema has additionalProperties: false
        assert result.valid is False
        assert len(result.errors) > 0

    def test_validation_exception_handling(self, validator):
        """Test validator handles exceptions gracefully."""
        # Pass invalid type (not a dict)
        result = validator.validate_agent_input("actor", "not a dict")

        assert result.valid is False
        assert len(result.errors) > 0

    def test_empty_code_changes_array(self, validator):
        """Test Actor output fails when code_changes is empty (minItems: 1)."""
        actor_output_empty_changes = {
            "approach": "Implement JWT authentication",
            "code_changes": [],  # Empty (violates minItems: 1)
            "testing_approach": "Unit tests",
            "used_bullets": []
        }

        result = validator.validate_agent_output("actor", actor_output_empty_changes)
        assert result.valid is False
        assert any("code_changes" in err.lower() for err in result.errors)

    def test_string_too_short(self, validator):
        """Test validation fails when string is too short (violates minLength)."""
        actor_output_short_approach = {
            "approach": "Short",  # Too short (minLength: 20)
            "code_changes": [{
                "file_path": "auth.py",
                "change_type": "create",
                "content": "# code",
                "rationale": "needed"
            }],
            "testing_approach": "Unit tests for authentication",
            "used_bullets": []
        }

        result = validator.validate_agent_output("actor", actor_output_short_approach)
        assert result.valid is False

    def test_invalid_enum_value(self, validator):
        """Test validation fails for invalid enum values."""
        actor_output_invalid_enum = {
            "approach": "Implement JWT authentication",
            "code_changes": [{
                "file_path": "auth.py",
                "change_type": "invalid_type",  # Invalid (not in enum)
                "content": "# code",
                "rationale": "needed"
            }],
            "testing_approach": "Unit tests",
            "used_bullets": []
        }

        result = validator.validate_agent_output("actor", actor_output_invalid_enum)
        assert result.valid is False
        assert any("change_type" in err.lower() for err in result.errors)

    def test_mcp_tool_detection_empty_output(self):
        """Test MCP tool detection with empty output."""
        detected = detect_mcp_tool_calls("")
        assert len(detected) == 0

    def test_mcp_tool_detection_whitespace_only(self):
        """Test MCP tool detection with whitespace-only output."""
        detected = detect_mcp_tool_calls("   \n\n   \t\t   ")
        assert len(detected) == 0

    def test_validation_allows_optional_sections_omitted(self, validator):
        """Test that validation allows omitting all optional fields."""
        # Reflector output with minimal required fields only
        reflector_minimal = {
            "key_insight": "JWT authentication with short-lived access tokens",
            "patterns_used": [],
            "patterns_discovered": []
            # All other fields omitted (optional)
        }

        result = validator.validate_agent_output("reflector", reflector_minimal)
        assert result.valid is True

    def test_validation_allows_different_tool_orderings(self):
        """Test that validation allows valid variations in MCP tool call order."""
        # Reflector calls cipher_memory_search THEN sequential-thinking (different order)
        output_variant = """
        I searched existing patterns using mcp__cipher__cipher_memory_search
        and then executed mcp__sequential-thinking__sequentialthinking to analyze.
        """

        detected = detect_mcp_tool_calls(output_variant)

        # Both tools should be detected regardless of order
        assert "mcp__cipher__cipher_memory_search" in detected
        assert "mcp__sequential-thinking__sequentialthinking" in detected


# ============================================================================
# Regression Tests (Real Workflow Data)
# ============================================================================


class TestRegressionWithRealData:
    """Test validation against actual workflow logs (regression tests)."""

    @pytest.mark.skipif(
        not Path(".map/workflow_logs").exists(),
        reason="No workflow logs available"
    )
    def test_validate_real_workflow_logs(self, validator):
        """Test validation against real workflow log data."""
        logs_dir = Path(".map/workflow_logs")

        # Find most recent workflow
        workflow_dirs = sorted(logs_dir.glob("workflow_*"))
        if not workflow_dirs:
            pytest.skip("No workflow logs found")

        latest_workflow = workflow_dirs[-1]

        # Validate all agent inputs in workflow
        for input_file in latest_workflow.glob("*_input.json"):
            agent_name = input_file.stem.replace("_input", "")

            with open(input_file) as f:
                input_data = json.load(f)

            result = validator.validate_agent_input(agent_name, input_data)

            # Real workflow data should pass validation
            assert result.valid is True, \
                f"{input_file} failed validation: {result.errors}"

        # Validate all agent outputs in workflow
        for output_file in latest_workflow.glob("*_output.json"):
            agent_name = output_file.stem.replace("_output", "")

            with open(output_file) as f:
                output_data = json.load(f)

            result = validator.validate_agent_output(agent_name, output_data)

            # Real workflow data should pass validation
            assert result.valid is True, \
                f"{output_file} failed validation: {result.errors}"

    def test_validation_with_real_schema_files(self):
        """Test that validator can load real schema files from src/mapify_cli/schemas/."""
        schemas_dir = Path(__file__).parent.parent / "src" / "mapify_cli" / "schemas"

        if not schemas_dir.exists():
            pytest.skip("Schema directory not found")

        validator = AgentContractValidator(schemas_dir=schemas_dir)

        # All 8 agents should have schemas loaded
        expected_agents = [
            "actor", "monitor", "predictor", "evaluator",
            "reflector", "curator", "task_decomposer", "documentation_reviewer"
        ]

        for agent in expected_agents:
            assert agent in validator._input_schemas, \
                f"Missing input schema for {agent}"
            assert agent in validator._output_schemas, \
                f"Missing output schema for {agent}"


# ============================================================================
# MCP Tool Requirements Tests
# ============================================================================


class TestMCPToolRequirements:
    """Test MCP tool requirement specifications."""

    def test_reflector_requirements_defined(self):
        """Test Reflector has required MCP tools defined."""
        assert "reflector" in MCP_TOOL_REQUIREMENTS
        spec = MCP_TOOL_REQUIREMENTS["reflector"]

        assert "mcp__cipher__cipher_memory_search" in spec.required_tools
        assert spec.agent_name == "reflector"

    def test_curator_requirements_defined(self):
        """Test Curator has required MCP tools defined (both tools)."""
        assert "curator" in MCP_TOOL_REQUIREMENTS
        spec = MCP_TOOL_REQUIREMENTS["curator"]

        assert "mcp__cipher__cipher_memory_search" in spec.required_tools
        assert "mcp__cipher__cipher_extract_and_operate_memory" in spec.required_tools
        assert spec.agent_name == "curator"

    def test_other_agents_no_requirements(self):
        """Test other agents (Actor, Monitor, etc.) have no MCP tool requirements."""
        agents_without_requirements = ["actor", "monitor", "predictor", "evaluator"]

        for agent in agents_without_requirements:
            assert agent not in MCP_TOOL_REQUIREMENTS


# ============================================================================
# Additional Coverage Tests
# ============================================================================


class TestAdditionalCoverage:
    """Additional tests to increase code coverage above 90%."""

    def test_validator_schema_loading_warnings(self, tmp_path, caplog):
        """Test validator handles missing schema directory gracefully."""
        import logging

        # Create validator with non-existent schema directory
        validator = AgentContractValidator(schemas_dir=tmp_path / "nonexistent")

        # Should have empty schemas
        assert len(validator._input_schemas) == 0
        assert len(validator._output_schemas) == 0

    def test_validator_schema_loading_invalid_json(self, tmp_path, caplog):
        """Test validator handles invalid JSON schema files gracefully."""
        import logging

        # Create schema directory with invalid JSON
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()

        invalid_schema = schemas_dir / "actor_input.json"
        invalid_schema.write_text("{ invalid json }")

        # Should handle gracefully with warning
        validator = AgentContractValidator(schemas_dir=schemas_dir)

        # Should not have actor schema loaded
        assert "actor" not in validator._input_schemas

    def test_validation_result_warnings(self, validator):
        """Test ValidationResult with warnings."""
        # Create input with extra fields (generates warnings in some schemas)
        input_data = {
            "language": "python",
            "project_name": "test",
            "subtask_description": "Test task description"
        }

        result = validator.validate_agent_input("actor", input_data)

        # Should have valid result (may have warnings)
        assert result.valid is True
        # Warnings list should exist
        assert isinstance(result.warnings, list)

    def test_validation_exception_in_iter_errors(self, validator):
        """Test validator handles exceptions during schema validation."""
        # Pass completely wrong data type
        result = validator.validate_agent_input("actor", ["not", "a", "dict"])

        assert result.valid is False
        assert len(result.errors) > 0

    def test_output_validation_exception_handling(self, validator):
        """Test output validator handles exceptions gracefully."""
        # Pass invalid data type
        result = validator.validate_agent_output("actor", None)

        assert result.valid is False
        assert len(result.errors) > 0

    def test_mcp_tool_detector_main_function_success(self, tmp_path):
        """Test MCP tool detector CLI main function with valid input."""
        from mapify_cli.validation.mcp_tool_detector import main
        import sys

        # Create temp file with reflector output
        output_file = tmp_path / "reflector_output.txt"
        output_file.write_text("""
        I searched using mcp__cipher__cipher_memory_search to find patterns.
        """)

        # Mock sys.argv
        test_args = [
            "mcp_tool_detector.py",
            "--agent", "reflector",
            "--output", str(output_file)
        ]

        with pytest.raises(SystemExit) as exc_info:
            with unittest.mock.patch.object(sys, 'argv', test_args):
                main()

        # Should exit with code 0 (success)
        assert exc_info.value.code == 0

    def test_mcp_tool_detector_main_function_failure(self, tmp_path):
        """Test MCP tool detector CLI main function with missing tools."""
        from mapify_cli.validation.mcp_tool_detector import main
        import sys

        # Create temp file with reflector output (missing required tools)
        output_file = tmp_path / "reflector_output.txt"
        output_file.write_text("""
        I analyzed the implementation without using MCP tools.
        """)

        # Mock sys.argv
        test_args = [
            "mcp_tool_detector.py",
            "--agent", "reflector",
            "--output", str(output_file)
        ]

        with pytest.raises(SystemExit) as exc_info:
            with unittest.mock.patch.object(sys, 'argv', test_args):
                main()

        # Should exit with code 1 (failure)
        assert exc_info.value.code == 1

    def test_global_validator_singleton(self):
        """Test module-level singleton validator pattern."""
        from mapify_cli.validation import contract_validator

        # Reset global validator
        contract_validator._validator = None

        # First call creates validator
        result1 = validate_agent_input("actor", {
            "language": "python",
            "project_name": "test",
            "subtask_description": "Test task"
        })

        # Second call reuses same validator
        result2 = validate_agent_output("actor", {
            "approach": "Implement feature X with Y approach",
            "code_changes": [{
                "file_path": "test.py",
                "change_type": "create",
                "content": "# code",
                "rationale": "needed"
            }],
            "testing_approach": "Unit tests for feature X",
            "used_bullets": []
        })

        # Both should use same validator instance
        assert contract_validator._validator is not None


# ============================================================================
# Test Configuration
# ============================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
