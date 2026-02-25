# Why Crucis

## The problem

Code generation agents can produce impressive first drafts, but they can't iterate reliably on their own. Without structured feedback, they:

- **Hardcode known inputs** — the function returns `3` when it sees `(1, 2)` rather than actually adding
- **Miss edge cases** — works for positive integers, crashes on zero or negatives
- **Satisfy tests without real logic** — a lookup table that maps known inputs to expected outputs
- **Stall without direction** — when code fails, the agent needs specific, actionable feedback to make progress

The core issue isn't just false-passing code — it's that agents need structured feedback loops to work autonomously. Every human checkpoint ("did the tests catch cheating?", "does this generalize?", "does this meet style requirements?") is a place where an agent stalls or drifts without intervention.

## The solution: an autonomy scaffold

Crucis is an autonomy scaffold for code-generating agents. It provides structured automated feedback — tests, adversarial review, constraints, holdout verification — so agents can iterate longer without human intervention. Each verification layer maps to a human checkpoint that Crucis automates.

Test-driven generation is the forcing function: tests are generated and hardened *before* any implementation exists. The implementation agent only sees the tests — never the objective — so it must write general code to pass them.

Four automated interventions replace human checkpoints:

| Automated intervention | Replaces this human checkpoint | When it runs |
|---|---|---|
| **Constraint gates** | "Does this code meet our style and complexity standards?" | Every generation attempt |
| **Adversarial review** | "Are these tests actually robust, or could someone cheat?" | After test generation |
| **Cheating probe** | "Can a fake implementation pass these tests?" | After adversarial review |
| **Holdout evals** | "Does this implementation generalize beyond the examples I showed?" | After implementation |

## Feature-to-outcome map

| Feature | What you get |
|---|---|
| Adversarial hardening cycles | Tests that resist hardcoding and input-memorization cheats |
| Holdout evals | Final safety net — implementation must generalize beyond known examples |
| 34 static constraint checks | Enforced complexity limits, security rules, and code quality standards |
| Checkpoint/resume | Stop mid-run and pick up where you left off |
| `--reset` / `--reset-task` | Iterate on specific tasks without restarting everything |
| Auto-holdout | Holdout evals are automatically split from your examples — no manual setup needed |
| Flat constraints | List constraints naturally; the system classifies them as required or advisory automatically |
| Background optimizer | (Experimental) Prompt strategies improve automatically across runs |
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
