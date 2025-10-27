#!/usr/bin/env python3
"""
DEPRECATED: This script is now a thin wrapper around the mapify CLI module.

For new usage, prefer:
  mapify validate graph <file>

This script remains for backward compatibility and development workflows.
It imports the validator implementation from mapify_cli.tools.validate_dependencies
to avoid code duplication.
"""

from mapify_cli.tools.validate_dependencies import main

if __name__ == "__main__":
    main()
