# Troubleshooting

Common issues and how to resolve them. Run `crucis doctor` first — it catches most problems automatically.

## :material-play-outline: Getting Started

### Workspace not initialized

```
Error: No objective file found
```

If you're starting fresh, initialize a workspace first:

```bash
crucis init --name my_function
```

### API key not set

```
[WARN] api_key_claude: ANTHROPIC_API_KEY is not set (required by claude agent)
```

Run `crucis doctor` to check API key status. Set the required key for your configured agent:

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # for claude agent
export OPENAI_API_KEY=sk-...          # for codex agent
```

For Codex, `codex login` also satisfies authentication checks even when `OPENAI_API_KEY` is unset.

Alternatively, configure a different agent in `.crucis/settings.yaml`:

```yaml
agents:
  generation_agent: codex
```

## :material-cpu-64-bit: Agent Errors

### Agent binary not found

```
Error: claude binary not found on PATH
```

Crucis runs agents as CLI subprocesses. Ensure the agent binary is installed and on your PATH:

```bash
which claude
which codex
```

If the binary is missing, install the relevant CLI tool. The agent returns `exit_code=-1` when the binary is not found, and Crucis retries with the next iteration.

Run diagnostics to verify binaries and environment quickly:

```bash
crucis doctor --workspace . --json
```

### Agent timeout

```
Error: Agent timed out after 300s
```

The default agent timeout is 300 seconds. If your objective is complex or the model is slow, the agent may time out. Crucis treats this as a failed attempt and retries.

To increase the timeout, pass `--timeout` to the run command:

```bash
crucis run --timeout 600   # 10 minutes
```

Other options to reduce timeouts:

- Simplify the objective (fewer train evals, simpler constraints)
- Use a faster model via config
- Reduce `max_budget_usd` to limit agent thinking time

## :material-package-variant: Docker / Sandbox Issues

### Docker not available

```
Sandbox: Docker unavailable, falling back to host pytest
```

When running `crucis run`, Crucis checks for Docker availability via `docker info`. If Docker is not installed or the daemon is not running, Crucis falls back to running pytest directly on the host.

To use the Docker sandbox:

1. Install Docker
2. Start the Docker daemon
3. Run without the `--no-sandbox` flag

To explicitly skip Docker: `crucis run --no-sandbox`

### Host pytest missing

When Docker is unavailable (or `--no-sandbox` is used), Crucis runs host verification via `python -m pytest`. If pytest is missing, Crucis now fails fast with a preflight error.

Fix by installing pytest into the active environment:

```bash
uv pip install pytest   # or: pip install pytest
```

## :material-shield-outline: Constraint Violations

### Understanding violation output

When generated tests violate constraints, Crucis shows which constraints failed:

```
Required constraint violations:
  - max_cyclomatic_complexity: measured 18, limit 15
  - max_lines_per_function: measured 95, limit 80
```

Required constraints are hard gates — the train suite is rejected and regenerated. Advisory constraints are soft gates — violations are reported but don't block approval.

### Adjusting constraint profiles

If constraints are too strict for your use case, create or modify `constraints/profiles.yaml`. Constraints use a flat list format — they are auto-classified as "required" (blocking) or "advisory" (non-blocking):

```yaml
profiles:
  my_profile:
    max_cyclomatic_complexity: 20
    max_lines_per_function: 100
    require_docstrings: true
```

Then reference in your objective:

```yaml
tests_constraint_profile: my_profile
```

If no `profiles.yaml` exists, built-in defaults are used.

## :material-content-save-outline: Checkpoint Issues

### Resuming after interruption

Crucis saves the checkpoint after each task completes. If you interrupt a fit run, simply re-run the same command — it resumes from the last completed task:

```bash
crucis run  # interrupted after task 2 of 4
crucis run  # resumes at task 3
```

### Resetting checkpoint state

Use the built-in reset flags instead of manually deleting files:

```bash
# Reset everything (prompts for confirmation)
crucis run --reset

# Skip the confirmation prompt
crucis run --reset -y

# Reset only specific tasks
crucis run --reset-task my_task
```

`--reset` and `--reset-task` are mutually exclusive. When `--reset-task` is used without `--task`, the reset tasks are automatically scoped for processing.
