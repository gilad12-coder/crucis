# Configuration

Crucis uses environment-backed runtime settings (`crucis/config.py`) and workspace-local settings (`.crucis/settings.yaml`).

Most projects only need `objective.yaml`. Profiles and settings are optional — Crucis uses sensible defaults.

## Key Runtime Fields

Environment variables (or `config.py` defaults):

| Variable | Default | Description |
|---|---|---|
| `GENERATION_AGENT` | `claude` | Agent for test generation |
| `GENERATION_MODEL` | `claude-opus-4-6` | Model for test generation |
| `CRITIC_AGENT` | `claude` | Agent for adversarial review |
| `CRITIC_MODEL` | `claude-opus-4-6` | Model for adversarial review |
| `IMPLEMENTATION_AGENT` | `codex` | Agent for code implementation |
| `IMPLEMENTATION_MODEL` | `gpt-5.3-codex` | Model for code implementation |
| `MAX_ITERATIONS` | `10` | Max retry attempts for generation/evaluation |
| `MAX_BUDGET_USD` | `5.0` | Per-agent-call cost budget cap |
| `OPTIMIZER_EVAL_TIMEOUT_SEC` | `180` | Evaluator timeout in seconds |
| `ANTHROPIC_API_KEY` | — | Anthropic API key (required for claude agent) |
| `OPENAI_API_KEY` | — | OpenAI API key (optional when Codex CLI login session is active) |

## Workspace Settings

Crucis maintains a workspace-local settings file at `.crucis/settings.yaml`, created by `crucis init` or automatically on first run.

### Optimizer Settings

The optimizer is disabled by default. To enable it, add `optimizer: enabled: true` to `.crucis/settings.yaml`:

```yaml
schema_version: 1
optimizer:
  enabled: true
  max_metric_calls: 24
  reflection_lm: openai/gpt-5.2
  train_split_ratio: 0.7
  max_examples_per_run: 24
  evaluator_timeout_sec: 180
  pass_weight: 0.9
  speed_weight: 0.1
  min_score_delta: 0.01
  promotion_mode: manual
  queue_max_jobs: 64
  capture_stdio: true
```

When the optimizer is disabled (the default), `crucis init` does not include the `optimizer` block in `settings.yaml`. The minimal default `settings.yaml` is:

```yaml
schema_version: 1
```

`max_metric_calls` is intentionally user-controlled here so budget can be tuned per workspace without changing CLI commands.

### Agent Settings

Agent settings in `.crucis/settings.yaml` override environment variables when set:

```yaml
agents:
  generation_agent: null   # "claude" or "codex" (null = env var or default)
  generation_model: null   # e.g. "claude-opus-4-6", "o4-mini"
  critic_agent: null
  critic_model: null
  implementation_agent: null
  implementation_model: null
  max_iterations: null     # max generation/evaluation retries (null = 10)
  max_budget_usd: null     # per-agent call budget cap (null = 5.00)
```

## Model Defaults

Each agent has a default model when `generation_model` / `critic_model` / `implementation_model` is set to `null`:

| Agent | Default Model |
|---|---|
| `claude` | `claude-opus-4-6` |
| `codex` | codex built-in default (leave model as `null`) |

Run `crucis doctor` to detect agent/model mismatches (e.g. a Claude agent configured with a GPT model).

## Constraint Profiles

Constraint profiles are loaded from `constraints/profiles.yaml` (or a custom file via `--profiles`). Each profile lists constraints flat — they are auto-classified into required (blocking) or advisory based on the field type. The old nested `primary:`/`secondary:` format still works for backward compatibility. See [Constraints Reference](constraints-reference.md) for all 44 available constraints and the list of advisory fields.

## Color and Output

Crucis routes all UI output (Rich-formatted messages, tables, spinners) to **stderr** and data output (JSON from `--json` flags) to **stdout**. This lets you pipe JSON output cleanly:

```bash
crucis status --json | jq '.task_progress'
```

Color is enabled by default when stderr is a TTY. Override with:

- `--color` / `--no-color` flags (see [CLI Reference](cli-reference.md#global-options))
- `NO_COLOR` environment variable (see [no-color.org](https://no-color.org/))

`--color` takes precedence over `NO_COLOR` when both are set.

## MCP Server

When running Crucis as an [MCP server](mcp-server.md), these additional environment variables apply:

| Variable | Default | Description |
|---|---|---|
| `CRUCIS_MCP_AUTHORIZED` | — | Set to `1` to authorize MCP access to the workspace |
| `CRUCIS_WORKSPACE` | cwd | Override workspace root for the MCP server |

Alternatively, create a `.crucis/mcp_enabled` marker file in the workspace to authorize MCP access without environment variables.

## Run Logs

Long-running phases (`fit`, `evaluate`, and `optimizer-worker`) append structured JSONL events under `.crucis/logs/`.

See [CLI Reference](cli-reference.md) for all commands and options.
