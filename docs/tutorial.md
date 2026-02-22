# Tutorial

This guide walks through two examples: a simple single-task objective and a multi-task interval system.

## Quick Start: Single Task

### 1. Initialize a Workspace

```bash
mkdir my-project && cd my-project
crucis init --name add
```

This scaffolds starter files:

- `objective.yaml` — objective template with your function name
- `constraints/profiles.yaml` — default constraint profiles
- `.crucis/settings.yaml` — runtime settings (agents, optimizer)
- `src/solution.py` — placeholder for implementation

If you use `--name factorial`, Crucis generates a complete factorial objective with real train evals. For other names, it creates a generic template with the name injected into function signatures and descriptions.

### 2. Edit the Objective

Edit the generated `objective.yaml` to describe your function:

```yaml title="objective.yaml"
name: add
description: Add two integers and return the sum.
signature: "add(a: int, b: int) -> int"
train_evals:
  - input: "(1, 2)"
    output: "3"
holdout_evals:
  - input: "(100, 23)"
    output: "123"
tests_constraint_profile: default
implementation_constraint_profile: default
verification_granularity: task
target_files:
  - "src/add.py"
```

### 3. Generate a Plan (Optional)

```bash
crucis plan objective.yaml
```

Creates `plan.md` — a structured generation plan that guides the test generation agent. This step is optional but improves first-attempt quality for complex objectives.

### 4. Preview Prompts (Optional)

```bash
crucis fit objective.yaml --dry-run
```

Shows the exact prompts that would be sent to agents, without making any API calls. Useful for verifying your objective and constraints before spending tokens.

### 5. Run Fit

```bash
# Interactive fit (review tests and adversarial reports manually)
crucis fit objective.yaml

# Fully automatic fit + evaluate
crucis fit objective.yaml -y --evaluate
```

During interactive fit, Crucis will:

1. **Generate a pytest train suite** from your objective and display it with syntax highlighting.
2. **Ask for approval** -- you can:
    - `a` -- accept the tests
    - `e` -- edit in your `$EDITOR`
    - `r` -- reject and regenerate
3. **Run adversarial review** -- the critic agent attacks the test suite, looking for generalization gaps and cheating opportunities.
4. **Execute a cheating probe** -- Crucis generates a deliberate cheat implementation and runs it against the tests. If the probe passes, the tests are too weak and the cycle repeats.
5. **Save checkpoint** -- progress is persisted after each task.

### 6. Evaluate

```bash
crucis evaluate objective.yaml
```

Crucis builds a curriculum from the checkpoint, sends it to the implementation agent, and verifies the result against both train suites and hidden holdout evals.

### 7. Check Progress

```bash
crucis checkpoint
```

Shows a table with task status and optimizer info.

## Multi-Task Example: Interval System

Real objectives often have multiple tasks. Here's the `examples/intervals/spec.yaml`:

```yaml title="objective.yaml"
name: interval_system
description: >-
  Interval scheduling utilities operating on sorted, non-overlapping
  interval lists represented as list[tuple[int, int]].
tests_constraint_profile: recommended
implementation_constraint_profile: recommended
target_files:
  - "src/intervals.py"

tasks:
  - name: merge_intervals
    description: Merge overlapping or adjacent intervals.
    signature: "merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]"
    train_evals:
      - input: "[(1,3),(2,6),(8,10)]"
        output: "[(1,6),(8,10)]"
      - input: "[]"
        output: "[]"
      - input: "[(1,4),(4,5)]"
        output: "[(1,5)]"
    holdout_evals:
      - input: "[(1,10)]"
        output: "[(1,10)]"
      - input: "[(1,2),(3,4),(5,6)]"
        output: "[(1,2),(3,4),(5,6)]"
      - input: "[(1,5),(2,3)]"
        output: "[(1,5)]"

  - name: insert_interval
    description: Insert a new interval and merge overlaps.
    signature: "insert_interval(intervals: list[tuple[int, int]], new: tuple[int, int]) -> list[tuple[int, int]]"
    train_evals:
      - input: "([(1,3),(6,9)], (2,5))"
        output: "[(1,5),(6,9)]"
      - input: "([], (5,7))"
        output: "[(5,7)]"
      - input: "([(1,5)], (2,3))"
        output: "[(1,5)]"
    holdout_evals:
      - input: "([(1,2),(3,5),(6,7),(8,10),(12,16)], (4,8))"
        output: "[(1,2),(3,10),(12,16)]"
      - input: "([(1,5)], (0,6))"
        output: "[(0,6)]"
      - input: "([(1,5)], (6,8))"
        output: "[(1,8)]"

  - name: find_free_slots
    description: Find unoccupied time ranges within a boundary.
    signature: "find_free_slots(busy: list[tuple[int, int]], range_start: int, range_end: int) -> list[tuple[int, int]]"
    train_evals:
      - input: "([(1,3),(5,8)], 0, 10)"
        output: "[(0,1),(3,5),(8,10)]"
      - input: "([], 0, 5)"
        output: "[(0,5)]"
      - input: "([(0,10)], 0, 10)"
        output: "[]"
    holdout_evals:
      - input: "([(2,4)], 5, 3)"
        output: "[]"
      - input: "([(0,5),(10,15)], 3, 12)"
        output: "[(5,10)]"
      - input: "([(3,7)], 3, 7)"
        output: "[]"

  - name: interval_intersection
    description: Compute the intersection of two interval lists.
    signature: "interval_intersection(a: list[tuple[int, int]], b: list[tuple[int, int]]) -> list[tuple[int, int]]"
    train_evals:
      - input: "([(0,2),(5,10)], [(1,5),(8,12)])"
        output: "[(1,2),(5,5),(8,10)]"
      - input: "([(1,3)], [(4,6)])"
        output: "[]"
    holdout_evals:
      - input: "([], [(1,2)])"
        output: "[]"
      - input: "([(0,10)], [(1,2),(3,4)])"
        output: "[(1,2),(3,4)]"
      - input: "([(0,3),(5,9)], [(2,6)])"
        output: "[(2,3),(5,6)]"
```

### Running the Multi-Task Objective

```bash
crucis fit objective.yaml
```

To process only specific tasks, use `--task`:

```bash
crucis fit objective.yaml --task merge_intervals --task insert_interval
```

Crucis processes each task sequentially:

```
Task [1/4]: merge_intervals
  Generating train suite...
  Validating syntax... OK
  Checking constraints... OK
  [a/e/r] Accept, edit, or reject?
  Running adversarial review...
  Executing cheating probe...
  Probe failed (good) -- tests are robust.
  Saved to checkpoint.

Task [2/4]: insert_interval
  ...

Task [3/4]: find_free_slots
  ...

Task [4/4]: interval_intersection
  ...

Fit complete: 4/4 tasks done.
```

### The Adversarial Review

When Crucis runs the adversarial review, you'll see output like:

```
Attack Vectors:
  - Hardcode return values for the 3 known inputs
  - Use input length as a lookup key

Generalization Gaps:
  - No test for single-element input
  - No negative number test cases

Suggested Probe Tests:
  - Test with intervals containing zero-width ranges
```

In interactive mode, you choose:
- `i` -- **improve**: regenerate tests incorporating the adversarial findings
- `d` -- **done**: accept the current tests

### Resuming After Interruption

If you stop mid-fit (e.g., after task 2), re-running the same command resumes from task 3:

```bash
crucis fit objective.yaml  # interrupted after merge_intervals, insert_interval
crucis fit objective.yaml  # resumes at find_free_slots
```

The checkpoint tracks each task's state independently.

## Artifacts

After a complete fit + evaluate cycle, your workspace contains:

| File | Purpose |
|------|---------|
| `.checkpoint.json` | Task progress and train suite sources |
| `tests/test_merge_intervals.py` | Generated train suite for each task |
| `curriculum.md` | Evaluation guide sent to implementation agent |
| `src/intervals.py` | Generated implementation |
| `.crucis/settings.yaml` | Runtime settings |
| `.crucis/optimizer/` | Background optimization state |

## Migration from Legacy Schema

If you have old `spec.yaml` or `.session.json` files:

```bash
crucis migrate --objective-in spec.yaml --objective-out objective.yaml
crucis migrate --checkpoint-in .session.json --checkpoint-out .checkpoint.json
```

See [Troubleshooting](troubleshooting.md) for details on legacy key mappings.

## Promoting Optimizer Candidates

After background optimization completes with a winning candidate:

```bash
crucis checkpoint          # check if candidate_ready is true
crucis promote --run-id <run_id>
```

See [Background Optimizer](optimizer.md) for the full promotion workflow.
