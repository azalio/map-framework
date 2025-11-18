"""
MCP tool verification for Reflector and Curator agents.

Ensures that Reflector and Curator call required Cipher MCP tools
(cipher_memory_search, cipher_extract_and_operate_memory) during execution.
"""

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Set

logger = logging.getLogger(__name__)


@dataclass
class MCPToolSpec:
    """Specification of required MCP tools for an agent."""

    agent_name: str
    required_tools: List[str]
    optional_tools: List[str]


# MCP tool requirements for agents
MCP_TOOL_REQUIREMENTS: Dict[str, MCPToolSpec] = {
    "reflector": MCPToolSpec(
        agent_name="reflector",
        required_tools=[
            "mcp__cipher__cipher_memory_search"
        ],
        optional_tools=[
            "mcp__sequential-thinking__sequentialthinking"
        ]
    ),
    "curator": MCPToolSpec(
        agent_name="curator",
        required_tools=[
            "mcp__cipher__cipher_memory_search",  # For deduplication
            "mcp__cipher__cipher_extract_and_operate_memory"  # For syncing high-quality bullets
        ],
        optional_tools=[]
    )
}


@dataclass
class MCPVerificationResult:
    """Result of MCP tool verification."""

    verified: bool
    missing_tools: List[str]
    detected_tools: Set[str]
    agent_name: str

    def __str__(self) -> str:
        if self.verified:
            return f"✓ {self.agent_name} MCP tools verified: {', '.join(self.detected_tools)}"
        else:
            missing = ', '.join(self.missing_tools)
            return f"✗ {self.agent_name} missing required MCP tools: {missing}"


def detect_mcp_tool_calls(agent_output: str) -> Set[str]:
    """
    Detect MCP tool calls in agent output.

    Looks for patterns like:
    - mcp__cipher__cipher_memory_search
    - mcp__sequential-thinking__sequentialthinking

    Distinguishes actual tool calls from mentions in explanations by checking
    for tool call context (e.g., preceding "calling", "invoked", "using").

    Args:
        agent_output: The agent's complete output text

    Returns:
        Set of detected MCP tool names
    """
    detected_tools = set()

    # Pattern for MCP tool names
    mcp_pattern = r'mcp__[a-z0-9_-]+__[a-z0-9_]+'

    # Find all MCP tool mentions
    matches = re.finditer(mcp_pattern, agent_output, re.IGNORECASE)

    for match in matches:
        tool_name = match.group(0)

        # Get surrounding context (50 chars before and after)
        start = max(0, match.start() - 50)
        end = min(len(agent_output), match.end() + 50)
        context = agent_output[start:end].lower()

        # Check if this looks like an actual tool call (not just a mention)
        # Tool calls often have keywords like: "calling", "invoked", "using", "via"
        call_indicators = [
            "calling",
            "invoked",
            "using",
            "via",
            "searched",
            "queried",
            "executed",
            "ran"
        ]

        # Require explicit call verb BEFORE tool name (stricter matching)
        # This prevents false positives from documentation mentions
        tool_called = False
        for indicator in call_indicators:
            # Match "invoked mcp__cipher__...", "using mcp__cipher__...", etc.
            if f"{indicator} {tool_name}" in context or f"{indicator} `{tool_name}`" in context:
                tool_called = True
                break

        if tool_called:
            detected_tools.add(tool_name)
            logger.debug(f"Detected MCP tool call: {tool_name}")

    return detected_tools


def verify_mcp_tools(agent_name: str, agent_output: str) -> MCPVerificationResult:
    """
    Verify that agent called all required MCP tools.

    Args:
        agent_name: Name of the agent (must be in MCP_TOOL_REQUIREMENTS)
        agent_output: Complete agent output text

    Returns:
        MCPVerificationResult with verification status
    """
    if agent_name not in MCP_TOOL_REQUIREMENTS:
        logger.warning(f"No MCP tool requirements defined for agent: {agent_name}")
        return MCPVerificationResult(
            verified=True,
            missing_tools=[],
            detected_tools=set(),
            agent_name=agent_name
        )

    spec = MCP_TOOL_REQUIREMENTS[agent_name]
    detected_tools = detect_mcp_tool_calls(agent_output)

    # Check which required tools are missing
    required_set = set(spec.required_tools)
    missing_tools = list(required_set - detected_tools)

    verified = len(missing_tools) == 0

    if verified:
        logger.info(
            f"✓ {agent_name} MCP tool verification passed: "
            f"{', '.join(detected_tools)}"
        )
    else:
        logger.error(
            f"✗ {agent_name} missing required MCP tools: {', '.join(missing_tools)}"
        )

    return MCPVerificationResult(
        verified=verified,
        missing_tools=missing_tools,
        detected_tools=detected_tools,
        agent_name=agent_name
    )


def main():
    """CLI entrypoint for MCP tool verification."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Verify MCP tool usage in agent output"
    )
    parser.add_argument(
        "--agent",
        required=True,
        help="Agent name (reflector, curator)"
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to agent output file"
    )
    args = parser.parse_args()

    with open(args.output) as f:
        output_text = f.read()

    result = verify_mcp_tools(args.agent, output_text)

    if result.verified:
        print(f"✓ {args.agent} MCP tool verification passed")
        sys.exit(0)
    else:
        print(
            f"✗ {args.agent} missing required MCP tools: "
            f"{', '.join(result.missing_tools)}"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
