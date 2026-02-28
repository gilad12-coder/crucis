# Quickstart: New Project

Build a verified function from scratch using Crucis, an autonomy scaffold for code-generating agents that provides structured automated feedback.

## 1. Create a workspace

```bash
mkdir my-project && cd my-project
crucis init --name add --no-agent
```

## 2. Edit the objective

```yaml
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

## 3. Verify your environment

```bash
crucis doctor --workspace .
```

## 5. Run the pipeline

```bash
crucis run
```

## 6. Check progress

```bash
crucis status
```

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
