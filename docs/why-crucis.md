# Why Crucis

## The problem

Code generation agents can write code that passes the examples you show them. But generated implementations routinely:

- **Hardcode known inputs** — the function returns `3` when it sees `(1, 2)` rather than actually adding
- **Miss edge cases** — works for positive integers, crashes on zero or negatives
- **Satisfy tests without real logic** — a lookup table that maps known inputs to expected outputs

Running a few manual tests doesn't catch this. You need adversarial pressure.

## The solution: verification-first

Crucis flips the usual generate-then-test workflow. Tests are generated and hardened *before* any implementation exists. The implementation agent only sees the tests — never the objective — so it must write general code to pass them.

Four verification layers work together:

| Layer | What it does | When it runs |
|---|---|---|
| **Constraint gates** | AST-based checks enforce complexity, security, and style rules on generated tests and implementation code | Every generation attempt |
| **Adversarial review** | A critic agent attacks the test suite, finding gaps and cheating strategies | After test generation |
| **Cheating probe** | A deliberate cheat implementation tries to pass tests by faking results | After adversarial review |
| **Holdout evals** | Hidden input/output pairs that no agent ever sees verify the final implementation | After implementation |

## Feature-to-outcome map

| Feature | What you get |
|---|---|
| Adversarial hardening cycles | Tests that resist hardcoding and input-memorization cheats |
| Holdout evals | Final safety net — implementation must generalize beyond known examples |
| 34 static constraint checks | Enforced complexity limits, security rules, and code quality standards |
| Checkpoint/resume | Stop mid-run and pick up where you left off |
| `--reset` / `--reset-task` | Iterate on specific tasks without restarting everything |
| Background optimizer | Prompt strategies improve automatically across runs |
| Multi-task objectives | Define several related functions in one file, each verified independently |

## When NOT to use Crucis

- **One-off scripts** where correctness doesn't matter much
- **UI/frontend code** where behavior is visual, not functional
- **Tasks without clear input/output contracts** (e.g., "make the app faster")
- **When you already have comprehensive tests** and just need implementation

Crucis works best for functions and modules with well-defined input/output behavior — algorithms, data transformations, business logic, API handlers.

## Next step

- [New Project Quickstart](quickstart-new-project.md) — try it in 5 minutes
- [Existing Codebase Quickstart](quickstart-existing-codebase.md) — apply it to your current project
