# Objective Format Reference

Crucis reads YAML objective files with strict keys. Legacy keys are rejected at parse time.

## Top-level keys

| Key | Required | Type | Default | Description |
|---|---|---|---|---|
| `name` | yes | `str` | — | Objective name (used as task name for single-task objectives) |
| `description` | yes | `str` | — | What the function/module should do |
| `signature` | no | `str` | — | Callable signature hint (e.g. `add(a: int, b: int) -> int`) |
| `train_evals` | no | `list` | `[]` | Visible evaluation cases shown to generation and critic agents |
| `holdout_evals` | no | `list` | `[]` | Hidden evaluation cases used only in final verification |
| `tests_constraint_profile` | no | `str` | `default` | Profile name from `constraints/profiles.yaml` for generated tests (constraints auto-classified as required or advisory) |
| `implementation_constraint_profile` | no | `str` | `default` | Profile name for implementation code (constraints auto-classified as required or advisory) |
| `behaviors` | no | `list[str]` | `[]` | Expected behavioral properties (e.g. `"idempotent"`, `"thread-safe"`) |
| `target_files` | no | `list[str]` | `[]` | Files the implementation agent should write |
| `context_files` | no | `list[str]` | `[]` | Existing files injected into generation and evaluation prompts |
| `existing_tests` | no | `list[str]` | `[]` | Test files run as a regression gate during evaluation |
| `tasks` | no | `list` | `[]` | Multi-task entries (see below) |
| `verification_granularity` | no | `str` | `task` | `task` or `objective` |

## Task keys

Each entry in `tasks` supports:

| Key | Required | Type | Default | Description |
|---|---|---|---|---|
| `name` | yes | `str` | — | Task name (must be a valid Python identifier) |
| `description` | no | `str` | `""` | Task description (falls back to top-level) |
| `signature` | no | `str` | — | Task signature (falls back to top-level) |
| `behaviors` | no | `list[str]` | `[]` | Task-specific behavioral properties |
| `train_evals` | no | `list` | falls back | Task-specific train evals |
| `holdout_evals` | no | `list` | falls back | Task-specific holdout evals |
| `tests_constraint_profile` | no | `str` | falls back | Task-specific test constraint profile |
| `implementation_constraint_profile` | no | `str` | falls back | Task-specific implementation constraint profile |
| `target_files` | no | `list[str]` | falls back | Task-specific target files |
| `context_files` | no | `list[str]` | `[]` | Task-specific context files (merged with top-level) |
| `existing_tests` | no | `list[str]` | `[]` | Task-specific regression tests (merged with top-level) |

**Inheritance:** Task-level fields override top-level fields when set. `context_files` and `existing_tests` are merged (both levels are included).

## Eval schema

Both `train_evals` and `holdout_evals` use the same format:

```yaml
train_evals:
  - input: "(1, 2)"
    output: "3"
```

- `input` — Python expression representing call arguments as a tuple (e.g. `"(1, 2)"` means `func(1, 2)`)
- `output` — Python expression representing the expected return value

**Auto-holdout:** If you only provide `examples` (or `train_evals`) without a `holdout_evals` key, Crucis automatically splits the last ~20% as holdout evals. To provide explicit holdout evals, add a `holdout:` key. To opt out of auto-holdout, set `holdout: []`.

**Holdout evals** have stricter requirements:

- Both `input` and `output` are required
- Values must be strings
- Expressions must parse as valid Python `eval` expressions
- The `raw` key is not allowed

## Verification granularity

Controls how Crucis evaluates implementation correctness:

- **`task`** (default) — each task's tests run independently; all must pass
- **`objective`** — all tests run as a single batch

```yaml
verification_granularity: task
```

Use `task` for multi-task objectives to get per-task failure feedback. Use `objective` when tasks are tightly coupled.

## Minimal example

```yaml
name: add
description: Add two integers.
signature: "add(a: int, b: int) -> int"
target_files:
  - "src/solution.py"
train_evals:
  - input: "(1, 2)"
    output: "3"
holdout_evals:
  - input: "(100, 23)"
    output: "123"
```

## Multi-task example

```yaml
name: math_utils
description: Basic math utilities.
target_files:
  - "src/math_utils.py"
tests_constraint_profile: recommended
implementation_constraint_profile: recommended
verification_granularity: task

tasks:
  - name: add
    description: Return the sum of two integers.
    signature: "add(a: int, b: int) -> int"
    train_evals:
      - input: "(1, 2)"
        output: "3"
  - name: multiply
    description: Return the product of two integers.
    signature: "multiply(a: int, b: int) -> int"
    train_evals:
      - input: "(3, 4)"
        output: "12"
```
