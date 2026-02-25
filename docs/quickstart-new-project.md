# Quickstart: New Project

Build a verified function from scratch using Crucis, an autonomy scaffold for code-generating agents that provides structured automated feedback.

**Who this is for:** You want to create a new function or module and want Crucis to generate robust tests and verified implementation.

**What you'll get:** A workspace with objective, generated test suite, adversarial report, and implementation code.

**Prerequisites:** Python 3.10+, `claude` or `codex` on PATH, API key set. Run `crucis doctor` to verify.

---

## 1. Create a workspace

```bash
mkdir my-project && cd my-project
crucis init --name add --no-agent
```

**Expected output:**
```
  Created: /path/to/my-project/objective.yaml
  Created: /path/to/my-project/src/solution.py
Tip: run `git init` — codex requires a trusted git repository.

Workspace ready at /path/to/my-project
Next steps:
  crucis run                    # run the full pipeline
  crucis run --plan             # generate a structured plan first
  crucis run --task <name>      # process a single task
  crucis run --dry-run          # preview generation prompts
```

`crucis init` creates only the essential files. Use `--with-profiles` to also create `constraints/profiles.yaml`, or `--with-settings` for `.crucis/settings.yaml`. Built-in defaults are used when these files don't exist.

!!! tip "Using Codex?"
    Run `git init && git add -A && git commit -m "init"` before proceeding. Codex requires a trusted git repository.

## 2. Edit the objective

Open `objective.yaml` and replace the placeholder with a real function description:

```yaml title="objective.yaml"
name: add
description: Add two integers and return the sum.
signature: "add(a: int, b: int) -> int"
behaviors:
  - "Returns the arithmetic sum of two integers"
  - "Handles negative numbers correctly"
tests_constraint_profile: recommended
implementation_constraint_profile: recommended
target_files:
  - "src/solution.py"
examples:
  - input: "(1, 2)"
    output: "3"
  - input: "(0, 0)"
    output: "0"
  - input: "(-1, 1)"
    output: "0"
  - input: "(100, 23)"
    output: "123"
tasks:
  - name: add
    description: Return the sum of two integers.
    signature: "add(a: int, b: int) -> int"
    examples:
      - input: "(1, 2)"
        output: "3"
      - input: "(0, 0)"
        output: "0"
      - input: "(-1, 1)"
        output: "0"
      - input: "(100, 23)"
        output: "123"
```

**Key fields:**

- `examples` — visible examples shown to the generation agent. The last ~20% are automatically held out as hidden evals (auto-holdout), so you don't need a separate `holdout:` section.
- `behaviors` — optional natural-language descriptions of expected behavior, used to guide test generation
- `target_files` — where the implementation will be written

## 3. Verify your environment

```bash
crucis doctor --workspace .
```

All checks should show `[OK]` or `[WARN]`. Fix any `[FAIL]` items before continuing.

## 4. Preview prompts (optional)

```bash
crucis run --dry-run
```

Shows the exact prompts that would be sent to agents without making API calls. Useful for verifying your objective before spending tokens.

## 5. Run the pipeline

```bash
crucis run
```

Crucis will:

1. Generate a pytest test suite from your objective
2. Validate it against constraint profiles
3. Run adversarial review (a critic agent attacks the tests)
4. Execute a cheating probe (tries to fake a passing implementation)
5. Implement code and verify against all tests
6. Save progress to `.checkpoint.json`

**Expected output (abbreviated):**
```
Workspace: /path/to/my-project

Review cycle 1/2 for add
┌── Generated Test Suite ──┐
│ import pytest              │
│ ...                        │
└────────────────────────────┘

Adversarial Report
  Attack vectors: ...
  Generalization gaps: ...

All tests passed.
Evaluation passed — 1/1 tasks complete.
```

## 6. Check progress

```bash
crucis status
```

Shows a table with task status, optimizer info, and next-step hints.

## What just happened?

1. **Test generation** — Crucis generated tests, had a critic attack them, ran a cheating probe, and hardened the tests through an adversarial loop. See [How It Works](workflow.md).
2. **Implementation** — The implementation agent wrote code guided only by the hardened tests. Auto-holdout evals (the last ~20% of your examples, automatically reserved) verified the implementation generalizes.
3. **Checkpoint** — All progress is persisted. You can resume, reset, or inspect at any time.

## Iterating

If tests or implementation need work:

```bash
# Reset everything and start fresh
crucis run --reset

# Reset only a specific task
crucis run --reset-task add

# Inspect what was generated
crucis status --task add
```

## Next step

- [Existing Codebase Quickstart](quickstart-existing-codebase.md) — apply Crucis to your current project
- [Use Cases](use-cases.md) — see what else Crucis can do
- [CLI Reference](cli-reference.md) — full command documentation
- [MCP Server](mcp-server.md) — use Crucis from inside Claude Code, OpenCode, or Codex
