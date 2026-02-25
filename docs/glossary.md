# Glossary

Term definitions for Crucis concepts.

---

## Concepts

### Scaffold

The workspace initialization created by `crucis init`. By default generates only `objective.yaml` and `src/solution.py` (for new-project scaffolds). Use `--with-profiles` to also create `constraints/profiles.yaml` and `--with-settings` to also create `.crucis/settings.yaml`. Existing codebases are auto-detected or forced via `--existing-codebase`.

### Plan

A structured generation plan created by `crucis run --plan`. Written to `plan.md` in the workspace root. Guides the test generation agent with per-task file structure, test categories, and constraint compliance instructions.

### Objective

A YAML file defining what Crucis should build. Contains a name, description, train evals, holdout evals, constraints, target files, and optional `behaviors`. Can be single-task or multi-task. See [Objective Format Reference](objective-reference.md).

### Task

One unit of work within an objective. Each task has its own name, signature, evals, constraint profile, and optional `behaviors`. Multi-task objectives list tasks under the `tasks` key.

### Behaviors

An optional `list[str]` on objectives and tasks describing expected behavioral properties (e.g. `"idempotent"`, `"thread-safe"`, `"deterministic"`). Used to guide test generation and adversarial review.

### Train Evals

Visible input/output pairs used during test generation and adversarial review. Agents see these evals and use them to build pytest suites.

### Holdout Evals

Hidden input/output pairs never shown to any agent. Used only during final verification to ensure the implementation generalizes beyond known inputs. Failures are reported as counts only -- no payloads are leaked.

### Auto-Holdout

When only `examples` (or `train_evals`) are provided without a `holdout_evals` key, Crucis automatically splits the last ~20% as holdout evals. To provide explicit holdout evals, add a `holdout:` key. To opt out of auto-holdout, set `holdout: []`.

### Train Suite

A generated pytest file containing tests for a task. Built by the generation agent from the objective, constraints, and train evals. Must pass syntax validation and constraint checks before approval.

### Constraint Profile

A named set of constraints defined in `constraints/profiles.yaml`. Constraints are listed flat and auto-classified into required (blocking) or advisory based on the field type. The old nested `primary:`/`secondary:` format still works. Referenced by name in the objective YAML via `tests_constraint_profile` and `implementation_constraint_profile`. See [Constraints Reference](constraints-reference.md).

### Required Constraints

Hard gates -- if violated, the train suite is rejected and regenerated. Violations are fed back to the generation prompt. Most constraints are required by default.

### Advisory Constraints

Soft gates -- violations are reported but don't block approval. Checked only after required constraints pass. Advisory fields: `require_docstrings`, `no_print_statements`, `no_debugger_statements`, `no_global_state`, `require_type_annotations`, `no_nested_imports`, `no_star_imports`, `max_local_variables`.

### Adversarial Review

The critic agent analyzes a train suite for weaknesses. Returns a JSON report with attack vectors, generalization gaps, and suggested probe tests.

### Cheating Probe

A deliberately cheating implementation generated to test whether the train suite can be passed by hardcoding, fingerprinting inputs, or using lookup tables. If the probe passes, the tests have gaps.

### Checkpoint

A JSON file (`.checkpoint.json`) that persists progress across runs. Tracks each task's state, approved train suite source, adversarial report, and `evaluation_passed` status. Allows resuming interrupted runs. Use `crucis run --reset` to clear the entire checkpoint or `--reset-task <name>` to clear specific tasks.

### Curriculum

A markdown file generated during evaluation containing the objective metadata, target files, test paths, and per-task details. This is the primary context sent to the implementation agent.

### Sandbox

Docker-isolated pytest execution. Tests run inside a container to prevent generated code from affecting the host. Falls back to host pytest if Docker is unavailable.

### Verification Granularity

Controls how tests are verified: `task` (default) runs each task's tests independently; `objective` runs all tasks' tests together in a single pytest invocation.

### Background Optimizer

An experimental GEPA-powered system that improves prompt steering over time. Disabled by default; enable with `optimizer: enabled: true` in `.crucis/settings.yaml`. After successful evaluation, a background worker scores candidate policies and promotes winners. See [Background Optimizer](optimizer.md).

### Policy

An optimizer policy that steers Crucis prompts. Contains four fields: `repository_skill`, `generation_directives`, `adversary_directives`, `evaluation_directives`. Each is injected into the corresponding prompt builder.

### Promotion

Replacing the active optimizer policy with a winning candidate. Can be manual (`crucis promote`) or automatic (`promotion_mode: auto`).

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
| `objective.yaml` | Objective definition (always created by `crucis init`) |
| `src/solution.py` | Implementation target (created by `crucis init` for new projects) |
| `plan.md` | Structured generation plan |
| `.checkpoint.json` | Task progress and train suite sources |
| `curriculum.md` | Generated evaluation guide |
| `constraints/profiles.yaml` | Constraint profile definitions (created with `--with-profiles`) |
| `tests/test_<task>.py` | Generated train suites |
| `src/<target>.py` | Implementation targets |
| `.crucis/settings.yaml` | Runtime settings (created with `--with-settings`) |
| `.crucis/optimizer/` | Optimizer state, policies, queue, and runs (when optimizer enabled) |
| `.crucis/logs/` | Structured JSONL run logs |

