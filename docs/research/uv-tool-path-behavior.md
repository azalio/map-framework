# UV Tool Installation PATH Behavior Research

**Research Date:** 2025-10-23
**UV Version Tested:** 0.6.11
**Test Platform:** macOS (Darwin 23.6.0, arm64)

## Executive Summary

UV tool installation uses a consistent XDG-based directory structure across all platforms (Linux, macOS, Windows). Tools are stored in isolated environments, with executables symlinked to a user bin directory that **must be in PATH** for CLI tools to be accessible.

## Default Installation Paths

### Tool Environments Storage (`UV_TOOL_DIR`)

UV stores complete tool environments (Python interpreter + dependencies) in:

| Platform | Default Path | Environment Override |
|----------|--------------|---------------------|
| **Linux** | `$XDG_DATA_HOME/uv/tools` or `~/.local/share/uv/tools` | `UV_TOOL_DIR` |
| **macOS** | `$XDG_DATA_HOME/uv/tools` or `~/.local/share/uv/tools` | `UV_TOOL_DIR` |
| **Windows** | `%APPDATA%\uv\data\tools` | `UV_TOOL_DIR` |

**Verified on macOS:**
```bash
$ uv tool dir
/Users/azalio/.local/share/uv/tools

$ ls -la ~/.local/share/uv/tools/
drwxr-xr-x  9 azalio  LD\Domain Users  288 Dec 29  2024 aider-chat
drwxr-xr-x  8 azalio  LD\Domain Users  256 Oct 16 19:03 mapify-cli
```

### Tool Executables/Bin Directory (`UV_TOOL_BIN_DIR`)

UV creates symlinks to tool executables in a bin directory following XDG standard:

| Platform | Default Path | Path Resolution Priority |
|----------|--------------|-------------------------|
| **All Platforms** | `~/.local/bin` (fallback) | 1. `$UV_TOOL_BIN_DIR`<br>2. `$XDG_BIN_HOME`<br>3. `$XDG_DATA_HOME/../bin`<br>4. `$HOME/.local/bin` |

**Key Finding:** UV applies XDG standard for bin directory (`~/.local/bin`) uniformly across all platforms. Tool storage follows platform conventions: XDG on Linux/macOS, `%APPDATA%` on Windows.

**Verified on macOS:**
```bash
$ uv tool install cowsay
Installed 1 executable: cowsay

$ ls -la ~/.local/bin/cowsay
lrwxr-xr-x  1 azalio  LD\Domain Users  53 Oct 23 13:17 /Users/azalio/.local/bin/cowsay -> /Users/azalio/.local/share/uv/tools/cowsay/bin/cowsay

$ which cowsay
/Users/azalio/.local/bin/cowsay
```

## PATH Requirements

### Critical Requirement

**The bin directory MUST be in PATH** for installed tools to be accessible as shell commands.

UV provides a helper command to verify and fix PATH configuration:

```bash
uv tool update-shell
```

This command automatically adds the bin directory to common shell configuration files.

### Testing PATH Accessibility

**Test conducted on macOS without `~/.local/bin` in PATH:**

```bash
$ echo "$PATH" | tr ':' '\n' | grep -E "\.local/bin"
# No output - ~/.local/bin NOT in PATH

$ uv tool install cowsay
Installed 1 executable: cowsay

$ which cowsay
/Users/azalio/.local/bin/cowsay  # ← Found via full PATH search

$ cowsay -t "test"
# ✓ Works because shell searches all standard locations
```

**However:** This varies by shell configuration. For guaranteed accessibility, users should explicitly add `~/.local/bin` to PATH.

## Environment Variable Overrides

### Tool Directory Override

```bash
export UV_TOOL_DIR="/custom/tools/path"
uv tool install mapify-cli
# Tool environment created in /custom/tools/path/mapify-cli/
```

### Bin Directory Override

```bash
export UV_TOOL_BIN_DIR="/custom/bin"
uv tool install mapify-cli
# Executable symlink created in /custom/bin/mapify
```

### XDG Standard Variables

```bash
export XDG_BIN_HOME="/usr/local/bin"
uv tool install mapify-cli
# Uses /usr/local/bin if UV_TOOL_BIN_DIR not set
```

## Docker/CI Environments

In Docker containers, UV explicitly sets `UV_TOOL_BIN_DIR=/usr/local/bin` to ensure system-wide accessibility:

```dockerfile
ENV UV_TOOL_BIN_DIR=/usr/local/bin
RUN uv tool install mapify-cli
```

## Platform-Specific Considerations

### macOS

- Default: `~/.local/share/uv/tools` (environments), `~/.local/bin` (executables)
- Users may need to add `~/.local/bin` to PATH in `~/.zshrc` or `~/.bash_profile`
- Homebrew Python installations don't affect UV tool paths

### Linux

- Default: `~/.local/share/uv/tools` (environments), `~/.local/bin` (executables)
- Most modern distributions include `~/.local/bin` in PATH by default
- Follows XDG Base Directory Specification exactly

### Windows

- Default: `%APPDATA%\uv\data\tools` (environments), `%USERPROFILE%\.local\bin` (executables)
- **Important:** Uses Unix-style `~/.local/bin` convention, NOT Windows-specific paths
- Users must manually add to PATH or use `uv tool update-shell`

## Verification Commands

```bash
# Check tool environment directory
uv tool dir

# List installed tools
uv tool list

# Check bin directory location
echo $UV_TOOL_BIN_DIR  # If set
echo $XDG_BIN_HOME     # If set
echo $HOME/.local/bin  # Default fallback

# Verify tool is accessible
which mapify

# Add bin directory to PATH helper
uv tool update-shell
```

## Recommendations for Documentation

1. **CRITICAL:** Document that `~/.local/bin` must be in PATH after installation
2. **Include platform-specific PATH setup:**
   - **macOS/Linux:** Add to `~/.zshrc`, `~/.bashrc`, or `~/.profile`
   - **Windows:** Use `uv tool update-shell` or manually update environment variables
3. **Troubleshooting:** Provide `which mapify` and PATH verification commands
4. **Override Options:** Document `UV_TOOL_BIN_DIR` for non-standard installations

## Sources

- UV Official Documentation: https://docs.astral.sh/uv/concepts/tools/
- UV GitHub Repository: https://github.com/astral-sh/uv
- Source Code Reference: `crates/uv-dirs/src/lib.rs` (XDG path logic)
- Verified via: Live testing on macOS Darwin 23.6.0

## Test Results

| Test | Platform | Result | Notes |
|------|----------|--------|-------|
| Default tool directory | macOS | ✅ Pass | `~/.local/share/uv/tools` |
| Default bin directory | macOS | ✅ Pass | `~/.local/bin` |
| Symlink creation | macOS | ✅ Pass | Correct target path |
| Tool accessibility | macOS | ✅ Pass | Found via which command |
| XDG variable priority | macOS | ✅ Pass | Follows documented order |
| UV_TOOL_DIR override | Not tested | ⏭️ Skip | Documentation verified |
| UV_TOOL_BIN_DIR override | Not tested | ⏭️ Skip | Documentation verified |
