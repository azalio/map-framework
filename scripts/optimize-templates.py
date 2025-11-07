#!/usr/bin/env python3
"""
MAP Template Optimizer

Identifies and optionally fixes redundancy in MAP agent templates.

Usage:
    python scripts/optimize-templates.py --analyze
    python scripts/optimize-templates.py --optimize --dry-run
    python scripts/optimize-templates.py --optimize
"""

import re
import sys
from pathlib import Path
from collections import defaultdict
from difflib import SequenceMatcher


class TemplateOptimizer:
    def __init__(self, template_dir: Path):
        self.template_dir = template_dir
        self.stats = defaultdict(int)
        self.optimizations = []

    def find_redundant_text(self, content: str, min_length=100):
        """Find text blocks that appear multiple times"""
        lines = content.split("\n")
        chunks = []

        # Create sliding window of 5-line chunks
        for i in range(len(lines) - 5):
            chunk = "\n".join(lines[i : i + 5])
            if len(chunk) >= min_length:
                chunks.append((i, chunk))

        # Find duplicates
        duplicates = defaultdict(list)
        for i, chunk in chunks:
            for j, other_chunk in chunks[i + 10 :]:  # Skip nearby chunks
                similarity = SequenceMatcher(None, chunk, other_chunk).ratio()
                if similarity > 0.85:
                    duplicates[chunk].append((i, j))

        return duplicates

    def analyze_example_lengths(self, content: str):
        """Analyze code example blocks and their lengths"""
        lines = content.split("\n")
        in_code_block = False
        block_start = 0
        code_blocks = []

        for i, line in enumerate(lines):
            if line.strip().startswith("```"):
                if not in_code_block:
                    in_code_block = True
                    block_start = i
                else:
                    in_code_block = False
                    block_length = i - block_start
                    if block_length > 50:
                        code_blocks.append((block_start, i, block_length))

        return code_blocks

    def find_redundant_sections(self, content: str):
        """Find sections with similar content"""
        # Extract all major sections
        sections = []
        current_section = None
        current_lines = []

        for line in content.split("\n"):
            if line.startswith("##"):
                if current_section:
                    sections.append((current_section, "\n".join(current_lines)))
                current_section = line
                current_lines = []
            else:
                current_lines.append(line)

        if current_section:
            sections.append((current_section, "\n".join(current_lines)))

        # Find similar sections
        similar = []
        for i, (title1, content1) in enumerate(sections):
            for title2, content2 in sections[i + 1 :]:
                if len(content1) > 200 and len(content2) > 200:
                    similarity = SequenceMatcher(None, content1, content2).ratio()
                    if similarity > 0.7:
                        similar.append(
                            (title1, title2, similarity, len(content1) + len(content2))
                        )

        return similar

    def count_critical_tags(self, content: str):
        """Count critical reminder sections"""
        critical_blocks = re.findall(r"<critical>(.+?)</critical>", content, re.DOTALL)
        return len(critical_blocks), sum(len(b) for b in critical_blocks)

    def suggest_consolidations(self, file_path: Path):
        """Suggest specific consolidations for a file"""
        content = file_path.read_text()
        suggestions = []

        # 1. Check for redundant text
        duplicates = self.find_redundant_text(content)
        if duplicates:
            suggestions.append(
                f"Found {len(duplicates)} redundant text blocks (5+ lines repeated)"
            )

        # 2. Check example lengths
        code_blocks = self.analyze_example_lengths(content)
        long_blocks = [b for b in code_blocks if b[2] > 80]
        if long_blocks:
            suggestions.append(
                f"Found {len(long_blocks)} code examples >80 lines (could be shortened)"
            )

        # 3. Check for similar sections
        similar_sections = self.find_redundant_sections(content)
        if similar_sections:
            suggestions.append(
                f"Found {len(similar_sections)} similar sections (>70% match)"
            )

        # 4. Check critical tags
        critical_count, critical_chars = self.count_critical_tags(content)
        if critical_count > 3:
            suggestions.append(
                f"Found {critical_count} <critical> blocks ({critical_chars} chars total, could consolidate)"
            )

        return suggestions

    def estimate_savings(self, file_path: Path):
        """Estimate potential line savings"""
        content = file_path.read_text()
        total_lines = len(content.split("\n"))

        # Conservative estimates
        savings = 0

        # Long code blocks could be reduced by 30%
        code_blocks = self.analyze_example_lengths(content)
        long_blocks = [b for b in code_blocks if b[2] > 80]
        for start, end, length in long_blocks:
            savings += int(length * 0.3)

        # Similar sections could be merged (save 40%)
        similar = self.find_redundant_sections(content)
        for _, _, _, total_chars in similar:
            lines_saved = int((total_chars / 80) * 0.4)  # Assume 80 chars per line
            savings += lines_saved

        # Critical blocks could be consolidated
        critical_count, _ = self.count_critical_tags(content)
        if critical_count > 3:
            savings += (
                critical_count - 2
            ) * 10  # Save ~10 lines per extra critical block

        return min(savings, int(total_lines * 0.15))  # Cap at 15%

    def analyze_all(self):
        """Analyze all templates and suggest optimizations"""
        print("\n=== MAP Template Optimization Analysis ===\n")

        template_files = sorted(
            [
                f
                for f in self.template_dir.glob("*.md")
                if f.name not in ["CHANGELOG.md", "README.md", "MCP-PATTERNS.md"]
            ]
        )

        total_lines = 0
        total_savings = 0

        for file_path in template_files:
            content = file_path.read_text()
            lines = len(content.split("\n"))
            total_lines += lines

            suggestions = self.suggest_consolidations(file_path)
            savings = self.estimate_savings(file_path)
            total_savings += savings

            print(f"📄 {file_path.name} ({lines} lines)")

            if suggestions:
                for suggestion in suggestions:
                    print(f"   • {suggestion}")
                print(
                    f"   💰 Potential savings: ~{savings} lines ({savings/lines*100:.1f}%)"
                )
            else:
                print("   ✓ Already optimized")
            print()

        print(f"{'='*60}")
        print("📊 SUMMARY")
        print(f"{'='*60}")
        print(f"Total lines:          {total_lines}")
        print(
            f"Potential savings:    ~{total_savings} lines ({total_savings/total_lines*100:.1f}%)"
        )
        print(
            f"Target (10-15%):      {int(total_lines * 0.10)}-{int(total_lines * 0.15)} lines"
        )
        print(
            f"Status:               {'✓ Target achievable' if total_savings >= total_lines * 0.10 else '⚠ Below target'}"
        )
        print()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Optimize MAP agent templates")
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Analyze templates and suggest optimizations",
    )
    parser.add_argument("--optimize", action="store_true", help="Apply optimizations")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without modifying files",
    )
    parser.add_argument(
        "--dir", type=str, default=".claude/agents", help="Template directory"
    )
    args = parser.parse_args()

    template_dir = Path(args.dir)
    if not template_dir.exists():
        print(f"Error: Template directory not found: {template_dir}")
        sys.exit(1)

    optimizer = TemplateOptimizer(template_dir)

    if args.analyze:
        optimizer.analyze_all()
    elif args.optimize:
        print("Optimization mode not yet implemented.")
        print("Please use --analyze to see suggested optimizations.")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
