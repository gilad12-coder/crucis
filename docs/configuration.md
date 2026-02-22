# Configuration

Crucis uses environment-backed runtime settings (`crucis/config.py`) and workspace-local settings (`.crucis/settings.yaml`).

## Key Runtime Fields

Environment variables (or `config.py` defaults):

| Variable | Default | Description |
|----------|---------|-------------|
| `GENERATION_AGENT` | `claude` | Agent for test generation |
| `GENERATION_MODEL` | `claude-opus-4-6` | Model for test generation |
| `CRITIC_AGENT` | `claude` | Agent for adversarial review |
| `CRITIC_MODEL` | `claude-opus-4-6` | Model for adversarial review |
| `IMPLEMENTATION_AGENT` | `codex` | Agent for code implementation |
| `IMPLEMENTATION_MODEL` | `gpt-5.3-codex` | Model for code implementation |
| `MAX_ITERATIONS` | `10` | Max retry attempts for generation/evaluation |
| `MAX_BUDGET_USD` | `5.0` | Per-agent-call cost budget cap |
| `OPTIMIZER_EVAL_TIMEOUT_SEC` | `180` | Evaluator timeout in seconds |
| `ANTHROPIC_API_KEY` | — | Anthropic API key (required for `claude` agent) |
| `OPENAI_API_KEY` | — | OpenAI API key (required for `codex` agent) |

## Workspace Settings

Crucis maintains a workspace-local settings file at `.crucis/settings.yaml`, created by `crucis init` or automatically on first run.

### Optimizer Settings

```yaml
schema_version: 1
optimizer:
  enabled: true
  max_metric_calls: 24
  reflection_lm: openai/gpt-5.1
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

## Constraint Profiles

Constraint profiles are loaded from `constraints/profiles.yaml` (or a custom file via `--profiles`).
Each profile defines `primary` and `secondary` gates plus optional guidance that shape train-suite generation.

## CLI Commands

### `crucis init`

```bash
crucis init [OPTIONS]
```

Scaffold a new Crucis workspace. By default, an AI agent conducts an interactive interview about your project and generates tailored files. Use `--no-agent` to skip the interview and use static templates.

| Option | Default | Description |
|---|---|---|
| `--name` | `my_project` | Project name; built-in templates exist for `factorial` |
| `--workspace` | `.` | Directory to scaffold |
| `--agent` | config default | Which agent conducts the onboarding (`claude` or `codex`) |
| `--no-agent` | off | Skip AI interview; use static templates (for CI/automation) |

Creates: `objective.yaml`, `constraints/profiles.yaml`, `.crucis/settings.yaml`, `src/solution.py`.

### `crucis plan`

```bash
crucis plan objective.yaml [OPTIONS]
```

Generate a structured generation plan for the objective.

| Option | Default | Description |
|---|---|---|
| `objective_path` | *(required)* | Path to objective YAML |
| `--profiles` | `constraints/profiles.yaml` | Constraint profile file |
| `--workspace` | objective parent | Workspace directory |
| `--force` | off | Regenerate plan even if `plan.md` exists |

Creates: `plan.md` in the workspace root.

### `crucis fit`

```bash
crucis fit objective.yaml [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `objective_path` | *(positional)* | Path to objective YAML file |
| `--objective` | — | Alternative to positional argument |
| `--profiles` | `constraints/profiles.yaml` | Constraint profile file |
| `--checkpoint` | `.checkpoint.json` | Checkpoint file path |
| `-y, --auto` | off | Auto-approve tests + adversarial review |
| `--auto-tests` | off | Auto-approve generated train suites |
| `--auto-adversary` | off | Auto-accept adversarial report |
| `--evaluate` | off | Run evaluation after fit |
| `--workspace` | objective parent | Workspace directory |
| `--dry-run` | off | Display generation prompts without calling agents |
| `--task` | — | Process only named task(s); repeatable |

### `crucis evaluate`

```bash
crucis evaluate objective.yaml [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `objective_path` | *(positional)* | Path to objective YAML file |
| `--objective` | — | Alternative to positional argument |
| `--profiles` | `constraints/profiles.yaml` | Constraint profile file |
| `--checkpoint` | `.checkpoint.json` | Checkpoint file path |
| `--no-sandbox` | off | Run host pytest instead of Docker sandbox |
| `--workspace` | objective parent | Workspace directory |

### `crucis checkpoint`

```bash
crucis checkpoint [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--checkpoint` | `.checkpoint.json` | Checkpoint file path |
| `--task` | — | Show test source and adversarial report for specific task |
| `--json` | off | Print machine-readable checkpoint payload |

### `crucis doctor`

```bash
crucis doctor [OPTIONS]
```

Runs diagnostics for environment prerequisites and optional workspace artifacts.

Checks performed:

- Python version (requires 3.12+)
- pytest availability
- Agent binaries on PATH (`claude`, `codex`)
- API keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`)
- Agent/model coherence (warns on mismatches like claude agent with gpt model)
- Claude Code nesting detection
- Runtime settings validation
- Docker sandbox availability

| Option | Default | Description |
|---|---|---|
| `--workspace` | `.` | Workspace root |
| `--objective` | unset | Optional objective file to validate |
| `--profiles` | unset | Optional profiles file to validate |
| `--checkpoint` | unset | Optional checkpoint file to validate |
| `--require-docker` | off | Treat missing Docker as a hard failure |
| `--json` | off | Print machine-readable diagnostics payload |

### `crucis promote`

```bash
crucis promote --run-id <run_id> [--workspace .]
```

Promotes a background optimizer candidate policy from `.crucis/optimizer/runs/<run_id>/candidate_policy.yaml` into active policy.

| Option | Default | Description |
|---|---|---|
| `--run-id` | *(required)* | Run ID of candidate to promote |
| `--workspace` | `.` | Workspace root |
| `--force` | off | Promote even when metadata is missing |

### `crucis optimizer-worker`

```bash
crucis optimizer-worker [OPTIONS]
```

Runs optimizer worker in foreground mode for scripts/automation.

| Option | Default | Description |
|---|---|---|
| `--workspace` | `.` | Workspace root |
| `--loop` | off | Run continuously instead of one-shot queue drain |
| `--json` | off | Print machine-readable worker result payload |

### `crucis migrate`

```bash
crucis migrate --objective-in old.yaml --objective-out objective.yaml
crucis migrate --checkpoint-in .session.json --checkpoint-out .checkpoint.json
```

Use migration before running strict parser/runtime on legacy files.

## Run Logs

Long-running phases (`fit`, `evaluate`, and `optimizer-worker`) append structured JSONL events under:

```
.crucis/logs/
```
