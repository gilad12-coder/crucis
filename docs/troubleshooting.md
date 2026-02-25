# Troubleshooting

## Getting Started

### Workspace not initialized

```
Error: No objective file found
```

If you're starting fresh, initialize a workspace first:

```bash
crucis init --name my_function
```

By default, an AI agent interviews you about your project. Use `--no-agent` for static templates. In non-interactive shells, Crucis falls back to static templates unless `--require-agent` is set. `init` requires Python 3.10+ (3.12+ recommended). By default, `crucis init` creates only `objective.yaml` and `src/solution.py` (for new projects). Use `--with-profiles` to also create `constraints/profiles.yaml`, or `--with-settings` for `.crucis/settings.yaml`. Built-in defaults are used when these optional files don't exist, and `settings.yaml` is auto-created on first `crucis run` if needed. Existing codebases are auto-detected from existing Python files (or forced via `--existing-codebase`), and in that mode only `objective.yaml` is created with `target_files` left empty for you to fill.

### `python -m crucis` fails with module not found

```
No module named crucis
```

This happens when running from source without installing Crucis into the active environment. Use one of:

```bash
# from repo root
./crucis-dev <command>

# from any directory
/absolute/path/to/crucis/crucis-dev <command>
```

Or install Crucis (`uv pip install -e .` or `pip install -e .` for development) and use `crucis <command>`.

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

## Agent Output

All agent calls stream stderr to the terminal in real time so you can see progress as it happens. Stdout is captured for response parsing. This applies to every phase: generation, adversarial review, planning, validation, and evaluation.

## Agent Errors

### Agent binary not found

```
Error: claude binary not found on PATH
```

Crucis runs agents as CLI subprocesses. Ensure the agent binary is installed and on your `PATH`:

```bash
# Check availability
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

### JSON parse failure in adversarial report

The adversary agent should return JSON with keys `attack_vectors`, `generalization_gaps`, and `suggested_probe_tests`. If the response is malformed, Crucis uses `json_repair` to attempt recovery. If repair fails, the adversarial review is skipped for that cycle and retried.

## Docker / Sandbox Issues

### Docker not available

```
Sandbox: Docker unavailable, falling back to host pytest
```

When running `crucis run`, Crucis checks for Docker availability via `docker info`. If Docker is not installed or the daemon is not running, Crucis falls back to running pytest directly on the host.

To use the Docker sandbox:
1. Install Docker
2. Start the Docker daemon
3. Run without the `--no-sandbox` flag

To explicitly skip Docker:
```bash
crucis run --no-sandbox
```

### Host pytest missing

When Docker is unavailable (or `--no-sandbox` is used), Crucis runs host verification via `python -m pytest`. If pytest is missing, Crucis now fails fast with a preflight error.

Fix by installing pytest into the active environment:

```bash
uv pip install pytest   # or: pip install pytest
```

### Docker timeout

The default Docker pytest timeout is 120 seconds. If tests take longer, the container is killed and the attempt is marked as failed. This is usually a sign that the generated implementation has an infinite loop or excessive computation.

## Constraint Violations

### Understanding violation output

When generated tests violate constraints, Crucis shows which constraints failed:

```
Required constraint violations:
  - max_cyclomatic_complexity: measured 18, limit 15
  - max_lines_per_function: measured 95, limit 80
```

Required constraints are hard gates -- the train suite is rejected and regenerated. Advisory constraints are soft gates -- violations are reported but don't block approval.

### Adjusting constraint profiles

If constraints are too strict for your use case, create or modify `constraints/profiles.yaml`. Constraints use a flat list format -- they are auto-classified as "required" (blocking) or "advisory" (non-blocking):

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

### Implementation constraints apply to entire target files

When using `implementation_constraint_profile: recommended` with an existing codebase, constraints are checked against the **entire** target file — not just the new code Crucis generates. Pre-existing functions that exceed complexity or line-count limits will cause every implementation attempt to fail.

For existing codebases, use a relaxed profile for implementation constraints:

```yaml
tests_constraint_profile: recommended
implementation_constraint_profile: default
```

The `crucis init --existing-codebase` scaffold sets this automatically.

## Checkpoint Issues

### Checkpoint file not found

```
Error: Checkpoint file not found: .checkpoint.json
```

The checkpoint is created automatically during `crucis run`. If the checkpoint is missing, run the pipeline first. You can specify a custom path:

```bash
crucis run --checkpoint path/to/checkpoint.json
```

### Resuming after interruption

Crucis saves the checkpoint after each task completes. If you interrupt a fit run, simply re-run the same command -- it resumes from the last completed task:

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


### Codex requires trusted git directory

```
Error: codex requires a trusted git directory
```

Codex requires a git repository. If you just ran `crucis init`, initialize git first:

```bash
git init && git add -A && git commit -m "init"
```

Crucis prints a hint about this after `crucis init` when no `.git` directory exists.

### Model not supported

```
Error: model "gpt-xxx" is not supported by agent "claude"
```

The configured model doesn't match the configured agent. Check `.crucis/settings.yaml`:

```yaml
agents:
  generation_agent: claude
  generation_model: claude-opus-4-6   # must be a Claude model
```

Run `crucis doctor` to detect agent/model mismatches. Model defaults per agent:

- `claude` → `claude-opus-4-6`
- `codex` → uses codex built-in default (set model to `null`)

## Optimizer Issues

### Optimizer not running

Check optimizer status:
```bash
crucis status
```

If the optimizer shows `idle` and never runs:
- Verify `.crucis/settings.yaml` has `optimizer.enabled: true`
- Check the environment: `CRUCIS_DISABLE_BACKGROUND_OPTIMIZER` should not be set
- Check the queue: `ls .crucis/optimizer/queue/`
- Check for stale lock: `cat .crucis/optimizer/worker.lock`

To run the worker explicitly in foreground mode:

```bash
crucis optimizer-worker --workspace . --json
```

A stale lock (from a crashed worker) is automatically recovered if the PID is no longer alive.

### Candidate not promoting

If a candidate is ready but not promoted in manual mode:
```bash
crucis promote --run-id <run_id>
```

The run ID is shown in `crucis status` output (alias: `crucis summary`). To enable auto-promotion, set `promotion_mode: auto` in `.crucis/settings.yaml`.
