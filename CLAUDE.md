# Repository Guidelines

## What This Is

A Model Context Protocol (MCP) server that connects TrainingPeaks to AI assistants. Uses cookie-based authentication (not the official gated API) to exchange for short-lived OAuth tokens. Communicates via stdio transport only.

## Commands

```bash
# Install (dev + browser extras)
python -m venv .venv && .venv/bin/pip install -e ".[dev,browser]"

# Run tests
.venv/bin/python -m pytest tests/ -v

# Run a single test
.venv/bin/python -m pytest tests/test_tools/test_workouts.py::test_name -v

# Lint and type check
.venv/bin/python -m ruff check src/ tests/
.venv/bin/python -m mypy src/

# Run server locally
.venv/bin/tp-mcp serve

# Authenticate
.venv/bin/tp-mcp auth --from-browser chrome
```

## Architecture

**Layered design:** CLI → Server → Tools → Client → TrainingPeaks API

- **`src/tp_mcp/server.py`** — MCP server entry point. Defines all `Tool` schemas (name, description, inputSchema) in a `TOOLS` list and dispatches calls via `call_tool()`. Each tool function is imported from `tp_mcp.tools`.
- **`src/tp_mcp/tools/`** — One module per domain (workouts, fitness, peaks, metrics, analyze, profile, auth_status, refresh_auth). Each exports async functions that use `TPClient` and return plain dicts.
- **`src/tp_mcp/client/http.py`** — `TPClient` async HTTP client. Handles cookie→OAuth token exchange, token caching with auto-refresh, request throttling (150ms), retry on 401, and athlete ID caching at class level. All API calls go through `_request()`.
- **`src/tp_mcp/client/models.py`** — Pydantic models for API data.
- **`src/tp_mcp/auth/`** — Cookie storage (keyring with encrypted file fallback), browser cookie extraction (hardcoded to `.trainingpeaks.com`), and auth validation.
- **`src/tp_mcp/cli.py`** — CLI entry point (`tp-mcp` command) for `serve`, `auth`, `auth-status`, `auth-clear`, `config`.
- **`tests/`** — Mirrored subfolders: `test_auth/`, `test_client/`, `test_tools/`.
- **`docs/`** — Planning notes. **`har/`** — Captured traffic examples (never commit secrets).

**Adding a new tool:**
1. Create or extend a module in `src/tp_mcp/tools/`
2. Export the function from `src/tp_mcp/tools/__init__.py`
3. Add a `Tool()` schema entry to the `TOOLS` list in `server.py`
4. Add the dispatch case in `call_tool()` in `server.py`
5. Add tests in `tests/test_tools/`

## Conventions

- Python 3.10+; 4-space indentation; type hints on public functions
- `ruff` for linting (line-length 120, import sorting via `I` rules)
- Naming: `snake_case` (modules/functions), `PascalCase` (classes), `UPPER_SNAKE_CASE` (constants)
- Tool functions use `tp_*` naming prefix
- `pytest` + `pytest-asyncio` with `asyncio_mode = auto`
- Tests mirror source structure: `src/tp_mcp/tools/workouts.py` → `tests/test_tools/test_workouts.py`
- Test names describe behavior: `test_update_workout_invalid_id`
- Mock external API calls; no real TrainingPeaks network access in tests
- Conventional Commits: `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`
- Keep commits scoped to one concern; include tests for behavior changes
- Cookie/token values must never appear in logs, tool results, error messages, or commits
- Prefer sanitized fixtures for API payload examples
