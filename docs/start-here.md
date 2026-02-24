# Start Here

Crucis is a verification-first coding loop. It generates tests, attacks them adversarially, and only then lets an implementation agent write code. The result: generated code that actually works beyond the examples you gave it.

## Is Crucis for me?

| Situation | Path |
|---|---|
| Starting a new function or module from scratch | [New Project Quickstart](quickstart-new-project.md) |
| Adding verified behavior to an existing codebase | [Existing Codebase Quickstart](quickstart-existing-codebase.md) |
| Want to understand the approach first | [Why Crucis](why-crucis.md) |

## Prerequisites

Before you start, you need:

1. **Python 3.10+** (3.12+ recommended)
2. **An agent CLI** on your PATH — either `claude` or `codex`
3. **An API key** — `ANTHROPIC_API_KEY` for Claude, or `OPENAI_API_KEY` / `codex login` for Codex

## Verify your environment

```bash
crucis doctor --workspace .
```

This checks Python version, agent binaries, API keys, Docker availability, and runtime settings. Fix any `[FAIL]` items before proceeding.

## Install

=== "uv (recommended)"

    ```bash
    uv pip install crucis
    ```

=== "pip"

    ```bash
    pip install crucis
    ```

=== "Source tree (no install)"

    ```bash
    ./crucis-dev doctor --workspace .
    ```

## Next step

Pick a quickstart:

- [New Project Quickstart](quickstart-new-project.md) — build a function from scratch with full verification
- [Existing Codebase Quickstart](quickstart-existing-codebase.md) — add verified behavior to your current project

!!! tip "Using an AI agent?"
    If you work inside Claude Code, OpenCode, or Codex, you can use Crucis as an [MCP server](mcp-server.md) instead of the CLI. The MCP server exposes every CLI command as a tool your agent can call directly.
