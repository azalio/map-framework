#!/usr/bin/env python3
"""
MAP Agent Template Linter

Validates consistency and quality of MAP agent templates.

Usage:
    python scripts/lint-agent-templates.py [--fix]

Options:
    --fix    Automatically fix issues where possible
"""

import re
import sys
import yaml
from pathlib import Path
from typing import Dict, Tuple
from collections import defaultdict


# Color codes for terminal output
class Colors:
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    BOLD = "\033[1m"
    END = "\033[0m"


class TemplateLinter:
    def __init__(self, template_dir: Path, fix_mode: bool = False):
        self.template_dir = template_dir
        self.fix_mode = fix_mode
        self.issues = []
        self.stats = defaultdict(int)

    def error(self, file: str, line: int, message: str):
        """Record an error"""
        self.issues.append(("ERROR", file, line, message))
        self.stats["errors"] += 1

    def warning(self, file: str, line: int, message: str):
        """Record a warning"""
        self.issues.append(("WARNING", file, line, message))
        self.stats["warnings"] += 1

    def info(self, file: str, line: int, message: str):
        """Record an info message"""
        self.issues.append(("INFO", file, line, message))
        self.stats["info"] += 1

    def parse_yaml_frontmatter(self, content: str) -> Tuple[Dict, int]:
        """Extract YAML frontmatter and return it with end line number"""
        if not content.startswith("---"):
            return {}, 0

        # Find the closing ---
        end_match = re.search(r"\n---\n", content[3:])
        if not end_match:
            return {}, 0

        yaml_content = content[3 : end_match.start() + 3]
        try:
            frontmatter = yaml.safe_load(yaml_content)
            return frontmatter, len(yaml_content.split("\n"))
        except yaml.YAMLError:
            return {}, 0

    def lint_yaml_frontmatter(self, file_path: Path, content: str):
        """Validate YAML frontmatter"""
        frontmatter, end_line = self.parse_yaml_frontmatter(content)

        if not frontmatter:
            self.error(file_path.name, 1, "Missing or invalid YAML frontmatter")
            return

        # Required fields
        required_fields = [
            "name",
            "description",
            "tools",
            "model",
            "version",
            "last_updated",
            "changelog",
        ]
        for field in required_fields:
            if field not in frontmatter:
                self.error(file_path.name, end_line, f"Missing required field: {field}")

        # Validate version format (semver)
        if "version" in frontmatter:
            version = frontmatter["version"]
            if not re.match(r"^\d+\.\d+\.\d+$", str(version)):
                self.error(
                    file_path.name,
                    end_line,
                    f"Invalid version format: {version} (expected semver: X.Y.Z)",
                )

        # Validate last_updated format (YYYY-MM-DD)
        if "last_updated" in frontmatter:
            date = str(frontmatter["last_updated"])
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
                self.error(
                    file_path.name,
                    end_line,
                    f"Invalid date format: {date} (expected YYYY-MM-DD)",
                )

    def lint_required_sections(self, file_path: Path, content: str):
        """Check for required sections"""
        lines = content.split("\n")

        # All agents should have these sections
        required_sections = ["mcp_integration", "context", "examples", "constraints"]

        found_sections = []
        for line in lines:
            # Check for XML-style tags
            for section in required_sections:
                if f"<{section}>" in line.lower():
                    found_sections.append(section)

        missing = set(required_sections) - set(found_sections)
        if missing:
            self.warning(
                file_path.name, 0, f"Missing recommended sections: {', '.join(missing)}"
            )

    def lint_template_variables(self, file_path: Path, content: str):
        """Validate Handlebars template variables"""
        lines = content.split("\n")

        # Find all template variables
        variable_pattern = r"\{\{([^}]+)\}\}"

        for i, line in enumerate(lines, 1):
            matches = re.finditer(variable_pattern, line)
            for match in matches:
                var_content = match.group(1)

                # Check for malformed variables
                if "{{" in var_content or "}}" in var_content:
                    self.error(
                        file_path.name,
                        i,
                        f"Malformed template variable: {{{{{var_content}}}}}",
                    )

                # Extract variable name (handle conditionals like #if, #unless)
                var_name = var_content.strip()
                if var_name.startswith("#if ") or var_name.startswith("#unless "):
                    var_name = var_name.split()[1]
                elif var_name.startswith("/"):
                    continue  # Closing tag

                # Info: track variable usage
                self.stats[f"var_{var_name}"] = self.stats.get(f"var_{var_name}", 0) + 1

    def lint_xml_tags(self, file_path: Path, content: str):
        """Validate XML-style semantic tags are properly closed"""
        lines = content.split("\n")
        tag_stack = []

        # Updated pattern to handle attributes: <tag attr="value"> or <tag>
        tag_pattern = r"<(/?)(\w+(?:_\w+)*)(?:\s+[^>]*)?>"

        # Tags that are allowed to be inline/unclosed (annotations, not structure)
        inline_tags = {"example", "rationale", "critical", "note", "system-reminder"}

        for i, line in enumerate(lines, 1):
            matches = re.finditer(tag_pattern, line)
            for match in matches:
                is_closing = match.group(1) == "/"
                tag_name = match.group(2)

                # Skip inline annotation tags
                if tag_name.lower() in inline_tags:
                    continue

                if is_closing:
                    if not tag_stack:
                        # Only error if this is a structural tag
                        if tag_name.lower() not in inline_tags:
                            self.warning(
                                file_path.name,
                                i,
                                f"Closing tag </{tag_name}> without opening tag",
                            )
                    elif tag_stack[-1][0] != tag_name:
                        # Check if the tag we're looking for is anywhere in the stack
                        tag_in_stack = any(t[0] == tag_name for t in tag_stack)
                        if tag_in_stack:
                            # Pop until we find the matching tag
                            while tag_stack and tag_stack[-1][0] != tag_name:
                                unclosed = tag_stack.pop()
                                self.info(
                                    file_path.name,
                                    unclosed[1],
                                    f"Tag <{unclosed[0]}> was not explicitly closed before </{tag_name}>",
                                )
                            if tag_stack:
                                tag_stack.pop()
                        else:
                            self.warning(
                                file_path.name,
                                i,
                                f"Mismatched closing tag </{tag_name}> (expected </{tag_stack[-1][0]}>)",
                            )
                    else:
                        tag_stack.pop()
                else:
                    tag_stack.append((tag_name, i))

        # Check for unclosed structural tags only
        structural_tags = [t for t in tag_stack if t[0].lower() not in inline_tags]
        for tag_name, line_num in structural_tags:
            self.warning(file_path.name, line_num, f"Unclosed tag <{tag_name}>")

    def lint_mcp_tool_descriptions(self, file_path: Path, content: str):
        """Check MCP tool descriptions for consistency"""
        # MCP tools whose descriptions should be consistent when present.
        # (deepwiki/context7 were removed; sequential-thinking needs no keyword check.)
        mcp_tools: dict[str, list[str]] = {}

        for tool, keywords in mcp_tools.items():
            if tool in content:
                # Check if description contains expected keywords
                tool_section = content[content.find(tool) : content.find(tool) + 500]
                missing_keywords = [
                    kw for kw in keywords if kw.lower() not in tool_section.lower()
                ]

                if len(missing_keywords) > len(keywords) // 2:
                    self.info(
                        file_path.name,
                        0,
                        f"MCP tool '{tool}' description may be incomplete (missing: {', '.join(missing_keywords)})",
                    )

    def lint_code_examples(self, file_path: Path, content: str):
        """Validate code example format"""
        lines = content.split("\n")
        in_code_block = False
        code_block_start = 0

        for i, line in enumerate(lines, 1):
            if line.strip().startswith("```"):
                if not in_code_block:
                    in_code_block = True
                    code_block_start = i
                else:
                    in_code_block = False

                    # Check if code block is too short for examples section
                    block_length = i - code_block_start
                    if (
                        block_length < 5
                        and "example"
                        in content[
                            max(0, code_block_start - 200) : code_block_start
                        ].lower()
                    ):
                        self.warning(
                            file_path.name,
                            code_block_start,
                            f"Code example may be too short ({block_length} lines)",
                        )

    def lint_section_naming_consistency(self):
        """Check that similar sections have consistent naming across templates"""
        section_names = defaultdict(list)

        for file_path in self.template_dir.glob("*.md"):
            if file_path.name in ["CHANGELOG.md", "README.md", "MCP-PATTERNS.md"]:
                continue

            content = file_path.read_text()

            # Extract section headers (both markdown and XML)
            markdown_headers = re.findall(r"^#+\s+(.+)$", content, re.MULTILINE)
            xml_tags = re.findall(r"<(\w+(?:_\w+)*)>", content)

            for header in markdown_headers:
                section_names[header.lower()].append(
                    (file_path.name, "markdown", header)
                )

            for tag in set(xml_tags):
                section_names[tag.lower()].append((file_path.name, "xml", tag))

        # Check for variations of similar section names
        mcp_variants = [
            name for name in section_names if "mcp" in name and "integration" in name
        ]
        if len(set(mcp_variants)) > 1:
            self.warning(
                "*", 0, f"Inconsistent MCP section naming: {set(mcp_variants)}"
            )

    def lint_file(self, file_path: Path):
        """Lint a single template file"""
        print(f"Linting {file_path.name}...")

        content = file_path.read_text()

        # Run all lint checks
        self.lint_yaml_frontmatter(file_path, content)
        self.lint_required_sections(file_path, content)
        self.lint_template_variables(file_path, content)
        self.lint_xml_tags(file_path, content)
        self.lint_mcp_tool_descriptions(file_path, content)
        self.lint_code_examples(file_path, content)

    def lint_all(self):
        """Lint all template files"""
        print(f"{Colors.BOLD}MAP Agent Template Linter{Colors.END}\n")
        print(f"Linting templates in: {self.template_dir}\n")

        # Lint individual files
        template_files = sorted(self.template_dir.glob("*.md"))
        template_files = [
            f
            for f in template_files
            if f.name not in ["CHANGELOG.md", "README.md", "MCP-PATTERNS.md"]
        ]

        for file_path in template_files:
            self.lint_file(file_path)

        # Lint cross-file consistency
        self.lint_section_naming_consistency()

        # Print results
        self.print_results()

    def print_results(self):
        """Print linting results"""
        print(f"\n{Colors.BOLD}{'='*60}{Colors.END}")
        print(f"{Colors.BOLD}Linting Results{Colors.END}\n")

        # Group issues by severity
        errors = [i for i in self.issues if i[0] == "ERROR"]
        warnings = [i for i in self.issues if i[0] == "WARNING"]
        info = [i for i in self.issues if i[0] == "INFO"]

        # Print errors
        if errors:
            print(f"{Colors.RED}{Colors.BOLD}Errors ({len(errors)}):{Colors.END}")
            for _, file, line, message in errors:
                line_str = f":{line}" if line > 0 else ""
                print(f"  {Colors.RED}✗{Colors.END} {file}{line_str} - {message}")
            print()

        # Print warnings
        if warnings:
            print(
                f"{Colors.YELLOW}{Colors.BOLD}Warnings ({len(warnings)}):{Colors.END}"
            )
            for _, file, line, message in warnings:
                line_str = f":{line}" if line > 0 else ""
                print(f"  {Colors.YELLOW}⚠{Colors.END} {file}{line_str} - {message}")
            print()

        # Print info (only if verbose or no other issues)
        if info and not (errors or warnings):
            print(f"{Colors.BLUE}{Colors.BOLD}Info ({len(info)}):{Colors.END}")
            for _, file, line, message in info[:5]:  # Limit info messages
                line_str = f":{line}" if line > 0 else ""
                print(f"  {Colors.BLUE}ℹ{Colors.END} {file}{line_str} - {message}")
            if len(info) > 5:
                print(f"  ... and {len(info) - 5} more")
            print()

        # Print summary
        print(f"{Colors.BOLD}Summary:{Colors.END}")
        print(f"  Templates checked: {self.stats.get('files', 9)}")
        print(f"  {Colors.RED}Errors: {self.stats['errors']}{Colors.END}")
        print(f"  {Colors.YELLOW}Warnings: {self.stats['warnings']}{Colors.END}")
        print(f"  {Colors.BLUE}Info: {self.stats['info']}{Colors.END}")

        # Print variable usage statistics
        var_stats = {k: v for k, v in self.stats.items() if k.startswith("var_")}
        if var_stats:
            print(f"\n{Colors.BOLD}Template Variable Usage:{Colors.END}")
            for var, count in sorted(
                var_stats.items(), key=lambda x: x[1], reverse=True
            )[:10]:
                var_name = var.replace("var_", "")
                print(f"  {var_name}: {count}")

        # Exit code
        print()
        if self.stats["errors"] > 0:
            print(
                f"{Colors.RED}✗ Linting failed with {self.stats['errors']} error(s){Colors.END}"
            )
            return 1
        elif self.stats["warnings"] > 0:
            print(
                f"{Colors.YELLOW}⚠ Linting passed with {self.stats['warnings']} warning(s){Colors.END}"
            )
            return 0
        else:
            print(f"{Colors.GREEN}✓ All templates passed linting!{Colors.END}")
            return 0


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Lint MAP agent templates")
    parser.add_argument(
        "--fix", action="store_true", help="Automatically fix issues where possible"
    )
    parser.add_argument(
        "--dir", type=str, default=".claude/agents", help="Template directory"
    )
    args = parser.parse_args()

    template_dir = Path(args.dir)
    if not template_dir.exists():
        print(f"Error: Template directory not found: {template_dir}")
        sys.exit(1)

    linter = TemplateLinter(template_dir, fix_mode=args.fix)
    exit_code = linter.lint_all()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
