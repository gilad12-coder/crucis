# Objective Format

Crucis reads YAML objective files with strict keys.

## Top-Level Keys

| Key | Required | Description |
|---|---|---|
| `name` | yes | Objective name |
| `description` | yes | Objective behavior |
| `signature` | no | Callable signature |
| `train_evals` | no | Visible evals used in prompts |
| `holdout_evals` | no | Hidden evals used only in final verification |
| `tests_constraint_profile` | no | Constraint profile for generated tests (default: `default`) |
| `implementation_constraint_profile` | no | Constraint profile for implementation code (default: `default`) |
| `target_files` | no | Files the evaluator should write |
| `context_files` | no | Existing files injected into generation and evaluation prompts |
| `existing_tests` | no | Test files run as a regression gate during evaluation |
| `tasks` | no | Multi-task objective entries |
| `verification_granularity` | no | `task` (default) or `objective` |

## Task Keys

| Key | Required | Description |
|---|---|---|
| `name` | yes | Task name |
| `description` | no | Task description |
| `signature` | no | Task signature |
| `train_evals` | no | Task-specific train evals |
| `holdout_evals` | no | Task-specific hidden evals |
| `tests_constraint_profile` | no | Task-specific test constraint profile override |
| `implementation_constraint_profile` | no | Task-specific implementation constraint profile override |
| `target_files` | no | Task-specific target files (fallback to top-level `target_files`) |
| `context_files` | no | Task-specific context files (merged with top-level) |
| `existing_tests` | no | Task-specific regression test files (merged with top-level) |

## Eval Schema

Both `train_evals` and `holdout_evals` use:

```yaml
- input: "(1, 2)"
  output: "3"
```

`holdout_evals` are strict:

- must include `input` and `output`
- values must be strings
- expressions must parse as Python `eval` expressions
- `raw` is not allowed

## Verification Granularity

Crucis supports two verification unit modes:

- `task` (default): evaluate verifier units per task and aggregate overall outcome.
- `objective`: evaluate one verifier unit for the full objective suite.

Example:

```yaml
verification_granularity: task
```

## Strict Cutover

Legacy keys are rejected at runtime:

- `examples`
- `public_evals`
- `hidden_evals`
- `functions`

Migrate legacy files before running:

```bash
crucis migrate --objective-in spec.yaml --objective-out objective.yaml
```
