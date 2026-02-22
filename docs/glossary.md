# Glossary

Every command, concept, model, and configuration option in Crucis.

---

## CLI Commands

### `crucis init`

Scaffold a new Crucis workspace. By default, an AI agent interviews you about your project and generates tailored files.

```bash
crucis init [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--name` | `my_project` | Project name; built-in templates exist for `factorial` |
| `--workspace` | `.` | Directory to scaffold |
| `--agent` | config default | Which agent conducts the onboarding (`claude` or `codex`) |
| `--no-agent` | off | Skip AI interview; use static templates (for CI/automation) |

### `crucis plan`

Generate a structured generation plan.

```bash
crucis plan objective.yaml [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `objective_path` | *(required)* | Path to objective YAML |
| `--profiles` | `constraints/profiles.yaml` | Path to constraint profiles YAML |
| `--workspace` | objective parent | Workspace directory |
| `--force` | off | Regenerate plan even if `plan.md` exists |

### `crucis fit`

Generate and harden test suites for an objective.

```bash
crucis fit objective.yaml [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `objective_path` | *(positional)* | Path to the objective YAML file |
| `--objective` | — | Alternative to positional argument |
| `--profiles` | `constraints/profiles.yaml` | Path to constraint profiles YAML |
| `--checkpoint` | `.checkpoint.json` | Path to checkpoint JSON file |
| `-y, --auto` | off | Auto-accept tests and adversarial review |
| `--auto-tests` | off | Auto-approve generated train suites only |
| `--auto-adversary` | off | Auto-accept adversarial report only |
| `--evaluate` | off | Run evaluation automatically after fit completes |
| `--workspace` | objective parent | Workspace directory |
| `--dry-run` | off | Display generation prompts without calling agents |
| `--task` | — | Process only named task(s); repeatable |

### `crucis evaluate`

Run the implementation agent against an existing checkpoint.

```bash
crucis evaluate objective.yaml [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `objective_path` | *(positional)* | Path to objective YAML |
| `--objective` | — | Alternative to positional argument |
| `--profiles` | `constraints/profiles.yaml` | Path to constraint profiles YAML |
| `--checkpoint` | `.checkpoint.json` | Path to checkpoint JSON |
| `--no-sandbox` | off | Run pytest on host instead of Docker |
| `--workspace` | objective parent | Workspace directory |

### `crucis checkpoint`

Display checkpoint progress table and optimizer status.

```bash
crucis checkpoint [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--checkpoint` | `.checkpoint.json` | Path to checkpoint JSON file |
| `--task` | — | Show test source and adversarial report for specific task |
| `--json` | off | Print machine-readable checkpoint payload |

### `crucis doctor`

Run environment and workspace diagnostics.

```bash
crucis doctor [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--workspace` | `.` | Workspace root |
| `--objective` | unset | Optional objective file to validate |
| `--profiles` | unset | Optional profiles file to validate |
| `--checkpoint` | unset | Optional checkpoint file to validate |
| `--require-docker` | off | Treat missing Docker as hard failure |
| `--json` | off | Print machine-readable diagnostics payload |

### `crucis migrate`

Migrate legacy objective and checkpoint files to the current schema.

```bash
crucis migrate [options]
```

| Flag | Description |
|------|-------------|
| `--objective-in` | Input objective file path |
| `--objective-out` | Output objective file path |
| `--checkpoint-in` | Input checkpoint file path |
| `--checkpoint-out` | Output checkpoint file path |

### `crucis promote`

Promote a candidate optimizer policy to active.

```bash
crucis promote --run-id <run_id> [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--run-id` | *(required)* | Run ID of candidate to promote |
| `--workspace` | `.` | Workspace directory root |
| `--force` | off | Promote even when candidate-ready metadata is missing |

### `crucis optimizer-worker`

Run the background optimizer worker in foreground mode.

```bash
crucis optimizer-worker [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--workspace` | `.` | Workspace root |
| `--loop` | off | Run continuously instead of one-shot |
| `--json` | off | Print machine-readable worker result |

---

## Concepts

### Scaffold

The workspace initialization created by `crucis init`. By default, an AI agent conducts an interactive interview to generate tailored files based on your project type and requirements. With `--no-agent`, static templates are used instead. Either way, generates `objective.yaml`, `constraints/profiles.yaml`, `.crucis/settings.yaml`, and `src/solution.py`. Built-in templates (e.g., `factorial`) produce complete objectives with real train evals.

### Plan

A structured generation plan created by `crucis plan`. Written to `plan.md` in the workspace root. Guides the test generation agent with per-task file structure, test categories, and constraint compliance instructions. Optional but improves first-attempt quality.

### Objective

A YAML file defining what Crucis should build. Contains a name, description, train evals, holdout evals, constraints, and target files. Can be single-task or multi-task.

### Task

One unit of work within an objective. Each task has its own name, signature, evals, and constraint profile. Multi-task objectives list tasks under the `tasks` key.

### Train Evals

Visible input/output pairs used during test generation and adversarial review. Agents see these evals and use them to build pytest suites.

### Holdout Evals

Hidden input/output pairs never shown to any agent. Used only during final verification to ensure the implementation generalizes beyond known inputs. Failures are reported as counts only — no payloads are leaked.

### Train Suite

A generated pytest file containing tests for a task. Built by the generation agent from the objective, constraints, and train evals. Must pass syntax validation and constraint checks before approval.

### Constraint Profile

A named set of primary and secondary constraints defined in `constraints/profiles.yaml`. Referenced by name in the objective YAML via `tests_constraint_profile` (for test generation) and `implementation_constraint_profile` (for implementation code).

### Primary Constraints

Hard gates — if violated, the train suite is rejected and regenerated. Violations are fed back to the generation prompt.

### Secondary Constraints

Soft gates — violations are reported but don't block approval. Checked only after primary constraints pass.

### Adversarial Review

The critic agent analyzes a train suite for weaknesses. Returns a JSON report with attack vectors, generalization gaps, and suggested probe tests.

### Cheating Probe

A deliberately cheating implementation generated to test whether the train suite can be passed by hardcoding, fingerprinting inputs, or using lookup tables. If the probe passes, the tests have gaps.

### Checkpoint

A JSON file (`.checkpoint.json`) that persists progress across runs. Tracks each task's state, approved train suite source, and adversarial report. Allows resuming interrupted runs.

### Curriculum

A markdown file generated during evaluation containing the objective metadata, target files, test paths, and per-task details. This is the primary context sent to the implementation agent.

### Sandbox

Docker-isolated pytest execution. Tests run inside a container to prevent generated code from affecting the host. Falls back to host pytest if Docker is unavailable.

### Verification Granularity

Controls how tests are verified:

- **`task`** (default) — each task's tests run independently
- **`objective`** — all tasks' tests run together in a single pytest invocation

### Background Optimizer

A GEPA-powered system that improves prompt steering over time. After `fit` or `evaluate`, a background worker scores candidate policies and promotes winners.

### Policy

An optimizer policy that steers Crucis prompts. Contains four fields: `repository_skill`, `generation_directives`, `adversary_directives`, `evaluation_directives`. Each field is injected into the corresponding prompt builder.

### Promotion

The act of replacing the active optimizer policy with a winning candidate. Can be manual (`crucis promote`) or automatic (`promotion_mode: auto`).

---

## Task States

Each task progresses through a state machine:

| State | Description |
|-------|-------------|
| `pending` | Task not yet started |
| `train_suite_generated` | Tests generated by LLM, not yet reviewed |
| `train_suite_approved` | Tests approved by user or auto-approved |
| `adversarially_reviewed` | Adversary attacked, probe ran |
| `complete` | Ready for evaluation |

---

## Training Loop Phases

### Fit Phase

1. **Generate** — create pytest train suite from objective and constraints
2. **Validate** — check syntax (`ast.parse`) and constraints (static analysis)
3. **Review** — user approves, edits, or rejects the train suite
4. **Adversarial review** — critic agent attacks tests, cheating probe runs
5. **Save** — checkpoint updated after each task

### Evaluation Phase

1. **Write test files** — train suites written to `tests/test_<task>.py`
2. **Build curriculum** — markdown guide from checkpoint + objective
3. **Run implementation agent** — agent writes code to target files
4. **Verify public tests** — pytest against train suites
5. **Verify holdout evals** — ephemeral pytest against hidden evals
6. **Retry or complete** — on failure, error feedback sent back to agent

---

## Data Models

### ParsedObjective

| Field | Type | Description |
|-------|------|-------------|
| `name` | str | Objective name |
| `description` | str | Objective description |
| `signature` | str or null | Function signature |
| `train_evals` | list[TrainEval] | Visible eval cases |
| `holdout_evals` | list[HoldoutEval] | Hidden eval cases |
| `tests_constraint_profile` | str | Constraint profile for tests (default: `default`) |
| `implementation_constraint_profile` | str | Constraint profile for implementation (default: `default`) |
| `target_files` | list[str] | Files the implementation agent writes |
| `tasks` | list[TaskObjective] | Sub-tasks for multi-task objectives |
| `verification_granularity` | `task` or `objective` | Verification unit mode |

### TaskObjective

| Field | Type | Description |
|-------|------|-------------|
| `name` | str | Task identifier |
| `description` | str | Task description |
| `signature` | str or null | Function signature |
| `train_evals` | list[TrainEval] | Task-specific visible evals |
| `holdout_evals` | list[HoldoutEval] | Task-specific hidden evals |
| `tests_constraint_profile` | str or null | Override test constraint profile |
| `implementation_constraint_profile` | str or null | Override implementation constraint profile |
| `target_files` | list[str] | Task-specific target files |

### TrainEval / HoldoutEval

| Field | Type | Description |
|-------|------|-------------|
| `input` | str | Test input expression (Python eval) |
| `output` | str | Expected output expression (Python eval) |

### AdversarialReport

| Field | Type | Description |
|-------|------|-------------|
| `attack_vectors` | list[str] | Identified attack strategies |
| `generalization_gaps` | list[str] | Gaps in test coverage |
| `suggested_probe_tests` | list[str] | Recommended additional tests |
| `probe_code` | str or null | Cheating implementation source |
| `probe_succeeded` | bool | Whether the probe passed the tests |

### ConstraintResult

| Field | Type | Description |
|-------|------|-------------|
| `passed` | bool | Whether all constraints passed |
| `violations` | list[str] | Violation messages |
| `metrics` | dict | Extracted metrics (complexity, lines, etc.) |

### CLIResult

| Field | Type | Description |
|-------|------|-------------|
| `stdout` | str | Process standard output |
| `stderr` | str | Process standard error |
| `exit_code` | int | Exit code (0 = success, -1 = binary not found) |
| `parsed_json` | dict or null | Parsed JSON from stdout |

---

## Configuration

Environment-backed settings in `crucis/config.py`:

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `GENERATION_AGENT` | `claude` | Agent for test generation |
| `GENERATION_MODEL` | `claude-opus-4-6` | Model for test generation |
| `CRITIC_AGENT` | `claude` | Agent for adversarial review |
| `CRITIC_MODEL` | `claude-opus-4-6` | Model for adversarial review |
| `IMPLEMENTATION_AGENT` | `codex` | Agent for code implementation |
| `IMPLEMENTATION_MODEL` | `gpt-5.3-codex` | Model for code implementation |
| `MAX_ITERATIONS` | `10` | Max retry attempts |
| `MAX_BUDGET_USD` | `5.0` | Cost budget for API calls |
| `OPTIMIZER_EVAL_TIMEOUT_SEC` | `180` | Evaluation timeout in seconds |

---

## Optimizer Settings

All settings in `.crucis/settings.yaml` under the `optimizer` key:

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | `true` | Enable background optimization |
| `max_metric_calls` | `24` | Max scoring evaluations per run |
| `reflection_lm` | `openai/gpt-5.1` | LLM for GEPA reflection |
| `train_split_ratio` | `0.7` | Train/validation split |
| `max_examples_per_run` | `24` | Max examples per optimization run |
| `evaluator_timeout_sec` | `180` | Timeout per evaluation attempt |
| `pass_weight` | `0.9` | Weight for correctness in scoring |
| `speed_weight` | `0.1` | Weight for speed in scoring |
| `min_score_delta` | `0.01` | Minimum improvement to promote |
| `promotion_mode` | `manual` | `manual` or `auto` |
| `queue_max_jobs` | `64` | Max jobs in queue |
| `capture_stdio` | `true` | Capture agent stdout/stderr |

---

## All 34 Constraints

### Complexity and Size

| Constraint | Type | Description |
|------------|------|-------------|
| `max_cyclomatic_complexity` | int | Max McCabe complexity per function |
| `max_cognitive_complexity` | int | Max SonarSource cognitive complexity per function |
| `max_lines_per_function` | int | Max lines in any single function |
| `max_total_lines` | int | Max total lines in the file |
| `max_time_complexity` | str | Max estimated time complexity (`O(1)` through `O(2^n)`) |
| `max_parameters` | int | Max parameters per function (excluding self/cls) |
| `max_nested_depth` | int | Max nesting depth of control flow |
| `max_return_statements` | int | Max return statements per function |
| `max_local_variables` | int | Max local variables per function |

### Code Quality

| Constraint | Type | Description |
|------------|------|-------------|
| `require_docstrings` | bool | Require docstrings on all functions and classes |
| `require_type_annotations` | bool | Require type hints on all parameters and returns |
| `no_print_statements` | bool | Disallow `print()` calls |
| `no_star_imports` | bool | Disallow `from x import *` |
| `no_mutable_defaults` | bool | Disallow mutable default arguments |
| `no_mutable_call_in_defaults` | bool | Disallow mutable calls in default values |
| `no_global_state` | bool | Disallow module-level mutable state |
| `no_debugger_statements` | bool | Disallow pdb/debugger statements |
| `no_nested_imports` | bool | Disallow imports inside functions |
| `no_bare_except` | bool | Disallow bare `except:` clauses |
| `no_try_except_pass` | bool | Disallow `try/except` blocks with only `pass` |
| `no_return_in_finally` | bool | Disallow return in `finally` blocks |
| `no_unreachable_code` | bool | Disallow code after unconditional return |
| `no_duplicate_dict_keys` | bool | Disallow duplicate dictionary keys |
| `no_loop_variable_closure` | bool | Disallow closure over loop variables |
| `no_shadowing_builtins` | bool | Disallow shadowing built-in names |
| `no_magic_numbers` | bool | Disallow numeric literals other than -1, 0, 1, 2 inside functions |
| `max_string_literal_repeats` | int | Max repeated string literals in a file |
| `allowed_imports` | list[str] | Whitelist of allowed import modules |

### Security

| Constraint | Type | Description |
|------------|------|-------------|
| `no_eval` | bool | Disallow `eval()` |
| `no_exec` | bool | Disallow `exec()` |
| `no_unsafe_deserialization` | bool | Disallow unsafe `pickle`/`yaml` deserialization |
| `no_unsafe_yaml` | bool | Disallow `yaml.load()` without safe Loader |
| `no_shell_true` | bool | Disallow `shell=True` in subprocess calls |
| `no_hardcoded_secrets` | bool | Disallow hardcoded credentials |
| `no_requests_without_timeout` | bool | Require timeout on `requests` calls |
| `no_open_without_context_manager` | bool | Require context manager for file opens |

---

## Agents

| Role | Default Agent | Default Model | Purpose |
|------|---------------|---------------|---------|
| Generation | `claude` | `claude-opus-4-6` | Generate pytest train suites |
| Critic | `claude` | `claude-opus-4-6` | Adversarial review of tests |
| Implementation | `codex` | `gpt-5.3-codex` | Write code to pass tests |

---

## File Structure

| Path | Purpose |
|------|---------|
| `objective.yaml` | Objective definition |
| `plan.md` | Structured generation plan (from `crucis plan`) |
| `.checkpoint.json` | Task progress and train suite sources |
| `curriculum.md` | Generated evaluation guide |
| `constraints/profiles.yaml` | Constraint profile definitions |
| `tests/test_<task>.py` | Generated train suites |
| `src/<target>.py` | Implementation targets |
| `.crucis/settings.yaml` | Runtime settings |
| `.crucis/optimizer/active_policy.yaml` | Current active policy |
| `.crucis/optimizer/status.json` | Optimizer state |
| `.crucis/optimizer/worker.lock` | Prevents concurrent workers |
| `.crucis/optimizer/queue/<job_id>.json` | Pending optimization jobs |
| `.crucis/optimizer/runs/<run_id>/` | Per-run candidate, result, report |

---

## Legacy Mappings

### Objective Keys

| Old Key | New Key |
|---------|---------|
| `examples` | `train_evals` |
| `public_evals` | `train_evals` |
| `hidden_evals` | `holdout_evals` |
| `functions` | `tasks` |

### Checkpoint Statuses

| Old Status | New Status |
|------------|------------|
| `tests_generated` | `train_suite_generated` |
| `tests_approved` | `train_suite_approved` |
| `critiqued` | `adversarially_reviewed` |
| `done` | `complete` |

### CLI Flags

| Old Flag | New Flag |
|----------|----------|
| `--session` | `--checkpoint` |
| `--implement` | `--evaluate` |
| `--auto-critique` | `--auto-adversary` |
| `--no-docker` | `--no-sandbox` |
| `--spec` | `--objective` |

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude |
| `OPENAI_API_KEY` | OpenAI API key for GPT/Codex |
| `CRUCIS_DISABLE_BACKGROUND_OPTIMIZER` | Set to `1` to disable optimizer |
| `CRUCIS_POLICY_OVERRIDE_JSON` | JSON string to override active policy |
