# Project Instructions

Control Ableton Live via model context protocol.
Goal: easiest one-liner install and setup of any ableton mcp on the market.

## Python Environment

Always use `uv` instead of `python` or `python3` directly:

# Important Files

- ./PRD.md -> overall project goal
- ./UPGRADES.md -> short term upgrades were working
- ./ARCHITECTURE.md -> Current arch overview. WARNING: possibly outdated. use a guidepost, not hard truth
- ./progress.txt -> Append-only log. Use early and often to document your work. Write things your future self will want to know.

## Architecture

- `MCP_Server/server.py` - FastMCP server that exposes tools to Claude
- `AbletonMCP_Remote_Script/__init__.py` - Control Surface script that runs inside Ableton Live
- Communication: TCP socket on port 9877 with length-prefixed JSON protocol

## Remote Script Constraints

The Remote Script runs in Ableton's embedded Python (2.7 compatible syntax in older versions):

- Use `format()` instead of f-strings
- State-modifying operations must be scheduled on the main thread via `schedule_message()`
- Read-only operations can run directly in the socket handler thread

## Testing

### Unit Tests

```bash
uv run pytest tests/test_command_dispatch.py -v
```

Tests command dispatch in the Remote Script. Mocks Ableton API at boundary.

### End-to-End Tests (requires Ableton)

```bash
# Full cycle: restart Ableton with fixture, run tests
./scripts/dev-refresh.sh --test

# Or separately:
./scripts/dev-refresh.sh      # Reset Ableton with test fixture
uv run python scripts/test_mcp_tools.py  # Run MCP tool tests
```

### Test Fixture

Located at `tests/fixtures/test_session Project/test_session.als`:

- Track 0 "Test-Synth": MIDI track with Drift synth
- Track 2 "Test-EQ": Audio track with EQ Eight
- Tempo: 128 BPM

### MCP Inspector (interactive debugging)

```bash
./scripts/dev-refresh.sh --inspector
# Opens http://localhost:6274
```

## Gotchas

- **E2E tests expect JSON**: Don't use `format_result` in `@ableton_command` for tools tested in `test_mcp_tools.py` - tests call `json.loads()` on responses.
