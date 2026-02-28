# Start Here

Crucis is an autonomy scaffold for code-generating agents. It provides structured automated feedback — tests, adversarial review, constraints, holdout verification — so agents can iterate longer without human intervention. The result: generated code that actually works beyond the examples you gave it.

## Is Crucis right for your project?

| Situation | Path |
|---|---|
| Starting a new function or module from scratch | [New Project Quickstart](quickstart-new-project.md) |
| Adding verified behavior to an existing codebase | [Existing Codebase Quickstart](quickstart-existing-codebase.md) |
| Want to understand the approach first | [Why Crucis](why-crucis.md) |

If you work inside Claude Code, OpenCode, or Codex, you can use Crucis as an [MCP server](mcp-server.md) instead of the CLI. The MCP server exposes every CLI command as a tool your agent can call directly.

## Prerequisites

1. Python 3.10+ (3.12+ recommended)
2. An agent CLI on your PATH — either `claude` or `codex`
3. An API key — `ANTHROPIC_API_KEY` for Claude, or `OPENAI_API_KEY` / `codex login` for Codex

## Verify your environment

```bash
crucis doctor --workspace .
```

This checks Python version, agent binaries, API keys, Docker availability, and runtime settings. Fix any `[FAIL]` items before proceeding.

## Install

```bash
uv pip install crucis
```

Also available via pip:

```bash
pip install crucis
```

Or run directly from the source tree (no install):

```bash
./crucis-dev doctor --workspace .
```

## What crucis init creates

By default, `crucis init` creates only two files: `objective.yaml` and `src/solution.py`. Profiles and settings are optional — add them with `--with-profiles` or `--with-settings`. Settings are auto-created on first `crucis run` if they don't exist.

You don't need to manually split examples into train and holdout sets. Just list your examples under `examples:` and Crucis automatically holds out the last ~20% for verification. If you need manual control, you can still use an explicit `holdout:` field. Use `holdout: []` to opt out of holdout verification entirely.

## Next step

Pick a quickstart:

- [New Project Quickstart](quickstart-new-project.md) — build a function from scratch with full verification
- [Existing Codebase Quickstart](quickstart-existing-codebase.md) — add verified behavior to your current project
