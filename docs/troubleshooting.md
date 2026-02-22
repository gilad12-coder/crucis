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

This creates `objective.yaml`, `constraints/profiles.yaml`, `.crucis/settings.yaml`, and `src/solution.py`. Edit `objective.yaml` to describe your function, then run `crucis fit objective.yaml`.

### API key not set

```
[WARN] api_key_claude: ANTHROPIC_API_KEY is not set (required by claude agent)
```

Run `crucis doctor` to check API key status. Set the required key for your configured agent:

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # for claude agent
export OPENAI_API_KEY=sk-...          # for codex agent
```

Alternatively, configure a different agent in `.crucis/settings.yaml`:

```yaml
agents:
  generation_agent: codex
```

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

To reduce timeouts:
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

When running `crucis evaluate`, Crucis checks for Docker availability via `docker info`. If Docker is not installed or the daemon is not running, Crucis falls back to running pytest directly on the host.

To use the Docker sandbox:
1. Install Docker
2. Start the Docker daemon
3. Run without the `--no-sandbox` flag

To explicitly skip Docker:
```bash
crucis evaluate --objective objective.yaml --no-sandbox
```

### Host pytest missing

When Docker is unavailable (or `--no-sandbox` is used), Crucis runs host verification via `python -m pytest`. If pytest is missing, Crucis now fails fast with a preflight error.

Fix by installing pytest into the active environment:

```bash
pip install pytest
```

### Docker timeout

The default Docker pytest timeout is 120 seconds. If tests take longer, the container is killed and the attempt is marked as failed. This is usually a sign that the generated implementation has an infinite loop or excessive computation.

## Constraint Violations

### Understanding violation output

When generated tests violate constraints, Crucis shows which constraints failed:

```
Primary constraint violations:
  - max_cyclomatic_complexity: measured 18, limit 15
  - max_lines_per_function: measured 95, limit 80
```

Primary constraints are hard gates -- the train suite is rejected and regenerated. Secondary constraints are soft gates -- violations are reported but don't block approval.

### Adjusting constraint profiles

If constraints are too strict for your use case, modify `constraints/profiles.yaml`:

```yaml
profiles:
  my_profile:
    primary:
      max_cyclomatic_complexity: 20
      max_lines_per_function: 100
    secondary:
      require_docstrings: true
```

Then reference in your objective:
```yaml
tests_constraint_profile: my_profile
```

## Checkpoint Issues

### Checkpoint file not found

```
Error: Checkpoint file not found: .checkpoint.json
```

The checkpoint is created automatically during `crucis fit`. If you're running `crucis evaluate` without a prior fit, ensure the checkpoint exists. You can specify a custom path:

```bash
crucis evaluate --objective objective.yaml --checkpoint path/to/checkpoint.json
```

### Resuming after interruption

Crucis saves the checkpoint after each task completes. If you interrupt a fit run, simply re-run the same command -- it resumes from the last completed task:

```bash
crucis fit objective.yaml  # interrupted after task 2 of 4
crucis fit objective.yaml  # resumes at task 3
```

### Resetting checkpoint state

To start fresh, delete the checkpoint file:

```bash
rm .checkpoint.json
crucis fit objective.yaml
```

## Migration Issues

### Legacy key rejection

```
Error: Legacy key 'examples' found. Use 'train_evals' instead.
```

If your objective uses old schema keys, run the migration tool:

```bash
crucis migrate --objective-in spec.yaml --objective-out objective.yaml
```

Legacy key mappings:

| Old Key | New Key |
|---------|---------|
| `examples` | `train_evals` |
| `public_evals` | `train_evals` |
| `hidden_evals` | `holdout_evals` |
| `functions` | `tasks` |

### Legacy checkpoint migration

```bash
crucis migrate --checkpoint-in .session.json --checkpoint-out .checkpoint.json
```

Status mappings:

| Old Status | New Status |
|------------|------------|
| `tests_generated` | `train_suite_generated` |
| `tests_approved` | `train_suite_approved` |
| `critiqued` | `adversarially_reviewed` |
| `done` | `complete` |

## Optimizer Issues

### Optimizer not running

Check optimizer status:
```bash
crucis checkpoint
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

The run ID is shown in `crucis checkpoint` output. To enable auto-promotion, set `promotion_mode: auto` in `.crucis/settings.yaml`.
