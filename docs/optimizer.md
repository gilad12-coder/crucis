# Background Optimizer

> **Experimental.** The optimizer is disabled by default. To enable it, set `optimizer: enabled: true` in `.crucis/settings.yaml`. See [Enabling the optimizer](#enabling-the-optimizer) below.

Crucis includes a background policy optimizer powered by [GEPA](https://github.com/gilad12-coder/gepa) that improves prompt steering over time. After each `fit` or `evaluate` run, Crucis queues an optimization job that scores candidate policies against a baseline using black-box evaluation.

## How It Works

1. After `crucis run` completes, an optimization job is queued.
2. A detached worker process picks up the job.
3. The worker builds examples from the objective and checkpoint.
4. GEPA generates candidate policies (prompt directives for generation, adversary, and evaluation agents).
5. Each candidate is scored by running the evaluation step in an isolated workspace.
6. If the candidate beats the baseline by `min_score_delta`, it's marked ready for promotion.

## Policy Structure

An optimizer policy steers Crucis prompts at three stages:

```yaml
# .crucis/optimizer/active_policy.yaml
repository_skill: "Context about the repository and coding patterns..."
generation_directives: "When generating train suites, focus on..."
adversary_directives: "When reviewing tests adversarially, look for..."
evaluation_directives: "When implementing code, prefer..."
```

Each field is injected into the corresponding prompt builder. Fields are capped at 20,000 characters.

## Directory Layout

```
.crucis/
  settings.yaml              # Optimizer settings (see below)
  optimizer/
    active_policy.yaml       # Current active policy
    status.json              # Optimizer state and metrics
    worker.lock              # Prevents concurrent workers
    queue/
      <job_id>.json          # Pending optimization jobs
    runs/
      <run_id>/
        candidate_policy.yaml  # Candidate from this run
        result.json            # Outcome metrics
        report.md              # Human-readable summary
```

## Job Lifecycle

```d2
direction: down

start: fit/evaluate completes

queue: Queue job

worker: Spawn detached worker

lock: Acquire worker.lock

examples: Build examples {
  tooltip: From objective + checkpoint
}

split: Split train/validation

gepa: Run GEPA optimize_anything()

score: Score baseline vs candidate

gate: "candidate >= baseline + min_score_delta?" {
  shape: diamond
}

ready: candidate_ready = true
skip: Skip (no improvement)

promote: Promote or wait {
  tooltip: "Manual: crucis promote | Auto: immediate"
}

start -> queue -> worker -> lock -> examples -> split -> gepa -> score -> gate
gate -> ready: yes
gate -> skip: no
ready -> promote
```

## Scoring

Each example is scored by running the evaluation step in a temporary isolated workspace:

```
final_score = pass_weight * correctness + speed_weight * speed
```

- **correctness**: 1.0 if all tests pass, 0.0 otherwise
- **speed**: `max(0.0, 1.0 - duration_sec / timeout_sec)`
- Default weights: `pass_weight=0.9`, `speed_weight=0.1`

Promotion requires:
- `candidate_mean_score >= baseline_mean_score + min_score_delta`
- `candidate_mean_correctness >= baseline_mean_correctness` (no regression)

## Promotion

### Manual mode (default)

After the optimizer marks a candidate as ready:

```bash
# Check status
crucis status

# Promote the winning candidate
crucis promote --run-id <run_id>
```

The `status` command (alias: `summary`) shows optimizer status including whether a candidate is ready and its run ID.

### Auto mode

Set `promotion_mode: auto` in `.crucis/settings.yaml`. Winning candidates are promoted immediately without user intervention.

## Automation-Friendly Commands

Crucis exposes machine-readable outputs for optimizer workflows:

```bash
# One-shot foreground worker drain
crucis optimizer-worker --workspace . --json

# Continuous worker loop
crucis optimizer-worker --workspace . --loop

# Scriptable optimizer + checkpoint status
crucis status --json
```

## Settings

All optimizer settings live in `.crucis/settings.yaml` under the `optimizer` key:

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | `false` | Enable/disable background optimization |
| `max_metric_calls` | `24` | Max scoring evaluations per run |
| `reflection_lm` | `openai/gpt-5.2` | LLM used for GEPA reflection |
| `train_split_ratio` | `0.7` | Train/validation split for examples |
| `max_examples_per_run` | `24` | Max examples per optimization run |
| `evaluator_timeout_sec` | `180` | Timeout for each evaluation attempt |
| `pass_weight` | `0.9` | Weight for correctness in scoring |
| `speed_weight` | `0.1` | Weight for speed in scoring |
| `min_score_delta` | `0.01` | Minimum improvement to promote |
| `promotion_mode` | `manual` | `manual` or `auto` |
| `queue_max_jobs` | `64` | Max jobs in queue |
| `capture_stdio` | `true` | Capture agent stdout/stderr |

Example `.crucis/settings.yaml`:

```yaml
schema_version: 1
optimizer:
  enabled: true
  promotion_mode: manual
  pass_weight: 0.9
  speed_weight: 0.1
  min_score_delta: 0.01
  evaluator_timeout_sec: 180
```

## Enabling the Optimizer

The optimizer is experimental and disabled by default. To enable it, add the `optimizer` block to `.crucis/settings.yaml`:

```yaml
schema_version: 1
optimizer:
  enabled: true
```

You can also scaffold the settings file with `crucis init --with-settings` and then add the optimizer block manually.

## Disabling the Optimizer

Set `enabled: false` in `.crucis/settings.yaml`, or set the environment variable to skip optimization entirely:

```bash
CRUCIS_DISABLE_BACKGROUND_OPTIMIZER=1 crucis run
```

## Policy Override

For testing, you can override the active policy with an environment variable:

```bash
export CRUCIS_POLICY_OVERRIDE_JSON='{"repository_skill":"...","generation_directives":"...","adversary_directives":"...","evaluation_directives":"..."}'
```

This takes precedence over `active_policy.yaml`.
