# Crucis

**Structured automated feedback for code-generating agents — so they can work longer and more reliably without human intervention.**

Crucis is an autonomy scaffold. It replaces the human checkpoints that slow down AI-assisted coding — "does this work?", "did you handle edge cases?", "are you cheating?", "is the code clean?" — with automated, structured interventions that run in real time.

Each intervention maps to a specific human oversight role:

| Human checkpoint | Crucis intervention |
|---|---|
| "Does the code actually work?" | Test-driven generation — agent iterates against a runnable test suite |
| "Does it generalize?" | Holdout evals — hidden test cases verify beyond training examples |
| "Are the tests too easy to cheat?" | Adversarial review + cheating probe |
| "Is the code well-written?" | AST-based constraint checking (34 static analysis rules) |
| "Did you handle the edge cases I care about?" | Behaviors — natural-language specs injected into prompts |

The core idea: **any test suite, even an imperfect one, gives an implementation agent a tighter feedback loop than no tests at all.** Crucis automates the entire test-driven loop so the model can self-correct against something objective.

## Quick start

```bash
uv pip install crucis
crucis init --name factorial --no-agent
# Edit objective.yaml: add examples, set description and signature
crucis run
```

That's it. Crucis generates tests, hardens them adversarially, writes an implementation, and verifies it against hidden holdout evals — all without human intervention.

## How it works

```
objective.yaml ──► Generate tests ──► Adversarial review ──► Cheating probe ──► Implementation ──► Holdout verification
                        │                    │                     │                  │                     │
                   "write pytest"     "find weaknesses"     "try to cheat"    "pass all tests"     "pass hidden evals"
```

1. **Fit phase**: An agent generates a pytest suite from your examples and constraints. A second agent attacks it, finding gaps. A cheating probe tries to exploit them. The cycle repeats until the tests are robust.
2. **Evaluate phase**: An implementation agent writes code to pass the hardened tests. Hidden holdout evals verify it generalizes.

## What you write

A single `objective.yaml`:

```yaml
name: factorial
description: Return n! for non-negative n. Raise ValueError for negative input.
signature: factorial(n: int) -> int
examples:
  - input: "(0,)"
    output: "1"
  - input: "(5,)"
    output: "120"
  - input: "(10,)"
    output: "3628800"
behaviors:
  - "Raises ValueError for negative input"
target_files:
  - src/solution.py
```

Holdout evals are auto-split from your examples — no manual train/holdout separation needed. Constraint profiles are optional and loaded from built-in defaults if you don't provide them.

## Install

```bash
uv pip install crucis        # recommended
pip install crucis            # also works
```

Requires Python 3.10+ (3.12+ recommended) and at least one agent CLI (`claude` or `codex`) on your PATH.

## Documentation

[Full docs](https://gilad12-coder.github.io/crucis/) — quickstarts, reference, configuration, troubleshooting.

- [Start Here](https://gilad12-coder.github.io/crucis/start-here/) — prerequisites and orientation
- [New Project Quickstart](https://gilad12-coder.github.io/crucis/quickstart-new-project/) — build a verified function from scratch
- [Existing Codebase Quickstart](https://gilad12-coder.github.io/crucis/quickstart-existing-codebase/) — add verification to your current project
- [CLI Reference](https://gilad12-coder.github.io/crucis/cli-reference/) — all commands and options
- [MCP Server](https://gilad12-coder.github.io/crucis/mcp-server/) — use Crucis as MCP tools from any AI agent

## License

MIT
