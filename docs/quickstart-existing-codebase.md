# Quickstart: Existing Codebase

Add verified behavior to a project that already has source code. Crucis detects existing Python files and scaffolds accordingly.

**Who this is for:** You have a Python project and want to add a new function or refactor existing behavior with verification.

**What you'll get:** A Crucis workspace integrated with your existing code, verified tests, and implementation.

**Prerequisites:** Python 3.10+, `claude` or `codex` on PATH, API key set. Run `crucis doctor` to verify.

---

## 1. Initialize in your project

From your project root:

```bash
crucis init --existing-codebase --no-agent --name my_feature
```

**Expected output:**
```
Existing codebase detected. Objective scaffold skips src/solution.py and leaves target_files for you to set.
  Created: /path/to/project/objective.yaml
  Created: /path/to/project/constraints/profiles.yaml
  Created: /path/to/project/.crucis/settings.yaml

Workspace ready at /path/to/project
```

Crucis auto-detects existing Python files. The `--existing-codebase` flag forces this mode explicitly.

## 2. Configure the objective

Edit `objective.yaml` to point at your actual project files:

```yaml title="objective.yaml"
name: my_feature
description: >-
  Parse configuration from YAML files and return validated settings.
signature: "load_config(path: str) -> dict"
tests_constraint_profile: recommended
implementation_constraint_profile: default
target_files:
  - "myproject/config.py"
context_files:
  - "myproject/models.py"
  - "myproject/defaults.py"
existing_tests:
  - "tests/test_models.py"
examples:
  - input: "('config.yaml',)"
    output: "{'debug': False, 'port': 8080}"
holdout:
  - input: "('missing.yaml',)"
    output: "{}"
tasks:
  - name: my_feature
    description: Load and validate config from a YAML file path.
    signature: "load_config(path: str) -> dict"
    target_files:
      - "myproject/config.py"
    context_files:
      - "myproject/models.py"
    examples:
      - input: "('config.yaml',)"
        output: "{'debug': False, 'port': 8080}"
    holdout:
      - input: "('missing.yaml',)"
        output: "{}"
```

**Key fields for existing codebases:**

- `target_files` — the file(s) the implementation agent will create or modify
- `context_files` — existing source files injected into prompts so agents understand your codebase
- `existing_tests` — test files that must continue passing (regression gate)

## 3. Configure the agent

Edit `.crucis/settings.yaml` if you need a different agent:

```yaml title=".crucis/settings.yaml"
agents:
  generation_agent: codex    # or "claude"
  generation_model: null     # null = agent default
```

Model defaults per agent:

- `claude` → `claude-opus-4-6`
- `codex` → uses codex built-in default (set model to `null`)

## 4. Run the pipeline

```bash
crucis run --no-sandbox
```

Crucis generates tests, hardens them adversarially, implements code into your `target_files`, and verifies against:

1. Generated test suite tests
2. Hidden holdout evals
3. Your existing tests (regression gate)

Context files are included in the generation prompt so the agent understands your project's patterns.

## Iterating on tasks

```bash
# Reset a specific task and re-run
crucis run --reset-task my_feature

# Reset everything
crucis run --reset

# Inspect generated tests
crucis status --task my_feature
```

## Validating your objective

```bash
crucis validate objective.yaml --workspace .
```

Checks that the objective parses correctly and referenced profiles exist. Use `--workspace` to resolve relative paths.

## Next step

- [CLI Reference](cli-reference.md) — full command documentation
- [Objective Format Reference](objective-reference.md) — all objective keys explained
- [How It Works](workflow.md) — understand the verification loop
- [MCP Server](mcp-server.md) — use Crucis from inside Claude Code, OpenCode, or Codex
