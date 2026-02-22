# Crucis

**Objective-driven coding with adversarial verification.**

Tests are generated and adversarially attacked before any implementation is written. A cheating probe tries to pass tests by faking results. Only when tests survive does the implementation agent work — and hidden holdout evals provide a final safety net.

## Install

```bash
pip install crucis
```

Requires Python 3.12+ and at least one agent CLI (`claude` or `codex`) on your PATH.

## Usage

```yaml
# objective.yaml
name: add
description: Add two integers and return the sum.
signature: "add(a: int, b: int) -> int"
train_evals:
  - input: "(1, 2)"
    output: "3"
holdout_evals:
  - input: "(100, 23)"
    output: "123"
target_files:
  - "src/add.py"
```

```bash
crucis fit objective.yaml -y --evaluate
```

Useful operational commands:

```bash
# Environment and workspace diagnostics
crucis doctor --workspace . --objective objective.yaml --profiles constraints/profiles.yaml

# Machine-readable checkpoint status for scripts/automation
crucis checkpoint --checkpoint .checkpoint.json --json

# Foreground optimizer worker (one-shot by default)
crucis optimizer-worker --workspace . --json
```

Crucis now writes structured JSONL run logs under `.crucis/logs/` for fit, evaluate, and optimizer worker runs.

## Documentation

[Full docs](https://gilad12-coder.github.io/crucis/) — tutorial, architecture, constraints, optimizer, troubleshooting.

## License

MIT
