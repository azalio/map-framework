"""Delivery layer for MAP Framework.

Handles generation and installation of MAP files into target projects.
"""

from mapify_cli.delivery.agent_generator import (
    create_task_decomposer_content,
    create_actor_content,
    create_monitor_content,
    create_predictor_content,
    create_evaluator_content,
    create_reflector_content,
    create_documentation_reviewer_content,
)
from mapify_cli.delivery.file_copier import (
    create_agent_files,
    create_reference_files,
    create_command_files,
    create_skill_files,
    create_hook_files,
    create_config_files,
    create_commands_dir,
    create_map_tools,
    create_rules_dir,
)
from mapify_cli.delivery.providers import BaseProvider as BaseProvider
from mapify_cli.delivery.providers import CodexProvider as CodexProvider
from mapify_cli.delivery.managed_file_copier import (
    CopyResult,
    DriftReport,
    copy_managed_file,
    detect_drift,
    inject_metadata,
    extract_metadata,
    compute_hash,
)
from mapify_cli.delivery.domain_skill import create_domain_skill

__all__ = [
    "BaseProvider",
    "CodexProvider",
    "create_task_decomposer_content",
    "create_actor_content",
    "create_monitor_content",
    "create_predictor_content",
    "create_evaluator_content",
    "create_reflector_content",
    "create_documentation_reviewer_content",
    "create_agent_files",
    "create_reference_files",
    "create_command_files",
    "create_skill_files",
    "create_hook_files",
    "create_config_files",
    "create_commands_dir",
    "create_map_tools",
    "create_rules_dir",
    "CopyResult",
    "DriftReport",
    "copy_managed_file",
    "detect_drift",
    "inject_metadata",
    "extract_metadata",
    "compute_hash",
    "create_domain_skill",
]
