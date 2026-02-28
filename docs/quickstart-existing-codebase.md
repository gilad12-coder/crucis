# Quickstart: Existing Codebase

Add verified behavior to a project that already has source code. Crucis is an autonomy scaffold for code-generating agents — it detects existing Python files and scaffolds accordingly.

## 1. Initialize in your project

```bash
crucis init --existing-codebase --no-agent --name my_feature
```

## 2. Configure the objective

```yaml
name: my_feature
description: >-
  Parse configuration from YAML files and return validated settings.
signature: "load_config(path: str) -> dict"
behaviors:
  - "Parses YAML config files into validated dictionaries"
  - "Returns empty dict for missing files instead of raising"
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
      - input: "('missing.yaml',)"
        output: "{}"
```

## 3. Configure the agent (optional)

```yaml
agents:
  generation_agent: codex    # or "claude"
  generation_model: null     # null = agent default
```

## 4. Run the pipeline

```bash
crucis run --no-sandbox
```

## Iterating on tasks

```bash
# Reset a specific task and re-run
crucis run --reset-task my_feature

# Reset everything
crucis run --reset

# Inspect generated tests
crucis status --task my_feature
```
