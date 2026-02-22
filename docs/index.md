# Crucis Documentation

Objective-driven coding with adversarial verification and background policy optimization.

## Why Crucis?

Code generation agents can write code, but how do you know the code is correct? Running a few examples isn't enough -- generated implementations often hardcode known inputs, miss edge cases, or satisfy tests without implementing real logic.

Crucis solves this by treating code generation as a **verification-first training loop**: tests are generated and adversarially attacked before any implementation is written. A cheating probe actively tries to pass the tests by faking results. Only when tests survive adversarial probing does the implementation agent get to work -- and even then, hidden holdout evals provide a final safety net.

## Key Features

- **Adversarial test hardening** -- a critic agent attacks generated tests, finding gaps and cheating strategies. Tests improve through an arms race. [Learn more](workflow.md)
- **Hidden holdout verification** -- holdout evals are never shown to any agent. They verify that implementations actually work, not just pass known tests. [Learn more](spec-format.md)
- **Background policy optimization** -- a GEPA optimizer learns better prompt strategies over time, improving generation quality across runs. [Learn more](optimizer.md)
- **34 static constraint checks** -- AST-based analysis enforces complexity limits, security rules, and code quality standards. [Learn more](constraints.md)

## Quick Start

### Install

```bash
pip install crucis
# or
uv sync
```

Requires Python 3.12+ and at least one agent CLI (`claude` or `codex`) on your PATH.

Check your version:

```bash
crucis --version
```

### Initialize a Workspace

```bash
mkdir my-project && cd my-project
crucis init --name add
```

An AI agent interviews you about your project, then generates tailored workspace files. Use `--no-agent` for static templates (CI/automation). Either way, you get `objective.yaml`, `constraints/profiles.yaml`, `.crucis/settings.yaml`, and `src/solution.py`. Edit the generated `objective.yaml` to describe your function:

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
target_files:
  - "src/add.py"
```

### Run

```bash
# Interactive fit + evaluate
crucis fit objective.yaml -y --evaluate

# Or step by step
crucis plan objective.yaml       # generate a structured plan
crucis fit objective.yaml        # generate and harden tests
crucis evaluate objective.yaml   # implement and verify
crucis checkpoint                # check progress
```

### Verify Environment

```bash
crucis doctor
```

Checks Python version, agent binaries, API keys, Docker availability, and runtime settings.

See the [Tutorial](tutorial.md) for a full walkthrough including multi-task objectives.
