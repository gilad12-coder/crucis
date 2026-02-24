# Use Cases

Crucis works best for functions and modules with well-defined input/output contracts. Here are common scenarios.

---

## Utility library

Build a set of pure functions (string manipulation, date math, data transformations) with adversarial verification that each function generalizes beyond the examples.

```bash
crucis init --name string_utils --no-agent
# Edit objective.yaml with multiple tasks (one per function)
crucis run
```

See [New Project Quickstart](quickstart-new-project.md).

---

## Algorithm implementation

Implement algorithms (sorting, graph traversal, interval scheduling) where correctness is critical and edge cases are easy to miss.

```bash
crucis init --name interval_system --no-agent
# Define tasks: merge_intervals, insert_interval, find_free_slots
crucis run
```

Multi-task objectives let you verify each function independently. See the interval system example in the [How It Works](workflow.md) page.

---

## Existing codebase refactor

Add a new module or refactor behavior in an existing project. Use `context_files` to feed your project's patterns into prompts and `existing_tests` as a regression gate.

```bash
crucis init --existing-codebase --name config_loader
# Set target_files, context_files, existing_tests in objective.yaml
crucis run
```

See [Existing Codebase Quickstart](quickstart-existing-codebase.md).

---

## Data pipeline validation

Define a data transformation pipeline with input/output contracts. Holdout evals verify the pipeline handles unseen data shapes.

```bash
crucis init --name etl_pipeline --no-agent
# Define tasks for each transformation step
crucis run
```

---

## Multi-task API

Generate and verify multiple related endpoint handlers in one objective. Each task maps to one handler function, all sharing the same target file.

```yaml
tasks:
  - name: create_user
    description: Create a new user and return the user dict.
    target_files: ["src/handlers.py"]
    examples:
      - input: "({'name': 'alice'},)"
        output: "{'id': 1, 'name': 'alice'}"
  - name: get_user
    description: Retrieve a user by ID.
    target_files: ["src/handlers.py"]
    examples:
      - input: "(1,)"
        output: "{'id': 1, 'name': 'alice'}"
```

```bash
crucis run --task create_user
crucis run --task get_user
```

## Next step

- [CLI Reference](cli-reference.md) — all commands and options
- [Objective Format Reference](objective-reference.md) — how to structure your objective file
