#!/bin/bash
# Easy Ableton MCP - Bootstrap script
# Ensures uv is installed, then runs the tool
#
# Usage:
#   ./ableton-mcp.sh --install     # Install Remote Script + configure Ableton
#   ./ableton-mcp.sh --uninstall   # Remove Remote Script + restore config
#   ./ableton-mcp.sh               # Run the MCP server

set -e

# Check for uv
if ! command -v uv &> /dev/null; then
    echo "uv is not installed. uv is required to manage Python dependencies."
    echo ""
    echo "uv is a fast Python package manager from Astral (creators of Ruff)."
    echo "Learn more: https://github.com/astral-sh/uv"
    echo ""
    read -p "Install uv now? [y/N] " -n 1 -r
    echo ""

    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted. Install uv manually:"
        echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi

    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh

    # Add to PATH for this session
    export PATH="$HOME/.local/bin:$PATH"

    if ! command -v uv &> /dev/null; then
        echo "ERROR: uv installation failed or not in PATH."
        echo "Restart your terminal and try again."
        exit 1
    fi

    echo "uv installed successfully."
    echo ""
fi

# Detect script location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "$SCRIPT_DIR/pyproject.toml" ]; then
    # Running from local repo
    uvx --from "$SCRIPT_DIR" easy-ableton-mcp "$@"
else
    # Running standalone - fetch from GitHub
    uvx --from git+https://github.com/androidStern/easy-ableton-mcp easy-ableton-mcp "$@"
fi
