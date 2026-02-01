#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "=== Ableton MCP Dev Refresh ==="

# Force quit Ableton
echo "Closing Ableton Live..."
if pgrep -f "Ableton Live" > /dev/null 2>&1; then
    pkill -9 -f "Ableton Live" 2>/dev/null || true
    while pgrep -f "Ableton Live" > /dev/null 2>&1; do sleep 0.5; done
    echo "Ableton closed."
else
    echo "Ableton not running."
fi

# Wait for port to be released
while lsof -i :9877 > /dev/null 2>&1; do sleep 0.5; done
echo "Port 9877 released."

# ALWAYS delete crash recovery files before launching to prevent dialog
# Must use find because glob with spaces (Live 11.3.43) doesn't work with rm directly
find ~/Library/Preferences/Ableton -maxdepth 2 -name "Crash" -type d -exec rm -rf {} + 2>/dev/null || true
find ~/Library/Preferences/Ableton -maxdepth 2 -name "CrashRecoveryInfo.cfg" -delete 2>/dev/null || true
find ~/Library/Preferences/Ableton -maxdepth 2 -name "CrashDetection.cfg" -delete 2>/dev/null || true
find ~/Library/Preferences/Ableton -maxdepth 2 -name "Undo" -type d -exec rm -rf {} + 2>/dev/null || true
echo "Cleaned crash recovery files."

# Re-symlink Remote Script (points to repo source, not uv cache)
echo "Installing Remote Script symlink..."
uv run python -c "from MCP_Server.server import main; import sys; sys.argv = ['', '--install']; main()" 2>&1 | grep -E "(Symlinked|Already configured|ERROR)"

# Open the test fixture project (or just launch Ableton if no fixture)
FIXTURE_PATH="$PROJECT_DIR/tests/fixtures/test_session Project/test_session.als"
if [ -f "$FIXTURE_PATH" ]; then
    echo "Opening test fixture: $FIXTURE_PATH"
    open "$FIXTURE_PATH"
else
    # Fallback: just launch Ableton
    ABLETON_APP=$(ls /Applications | grep -i "Ableton Live" | head -1 | sed 's/\.app$//')
    if [ -z "$ABLETON_APP" ]; then
        echo "ERROR: Could not find Ableton Live in /Applications"
        exit 1
    fi
    echo "Launching: $ABLETON_APP"
    open -a "$ABLETON_APP"
fi
echo "Waiting for Remote Script (max 90s)..."
for i in {1..90}; do
    if lsof -i :9877 > /dev/null 2>&1; then
        echo "Remote Script ready on port 9877."
        break
    fi
    sleep 1
done

if ! lsof -i :9877 > /dev/null 2>&1; then
    echo "ERROR: Remote Script did not start on port 9877"
    exit 1
fi

echo ""
echo "=== Ableton Ready ==="
echo ""

# Option 1: Launch MCP Inspector (interactive)
if [ "$1" = "--inspector" ]; then
    echo "Launching MCP Inspector..."
    echo "Open: http://localhost:6274"
    uv run mcp dev MCP_Server/server.py
    exit 0
fi

# Option 2: Run automated tests
if [ "$1" = "--test" ]; then
    echo "Running automated tests..."
    uv run python scripts/test_mcp_tools.py
    exit 0
fi

# Default: just print instructions
echo "Next steps:"
echo "  1. Launch MCP Inspector:"
echo "     uv run mcp dev MCP_Server/server.py"
echo "     Then open: http://localhost:6274"
echo ""
echo "  2. Or run automated tests:"
echo "     uv run python scripts/test_mcp_tools.py"
echo ""
echo "  3. Or rerun with flags:"
echo "     ./scripts/dev-refresh.sh --inspector"
echo "     ./scripts/dev-refresh.sh --test"
