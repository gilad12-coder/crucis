# Crucis

**Verification-first coding — tests are generated and adversarially attacked before any implementation is written.**

Four layers protect against false-passing code: AST-based constraints reject weak tests, an adversarial critic finds gaps, a cheating probe exploits them, and hidden holdout evals verify the final result. Only when tests survive all four does the implementation agent write code.

## Quick start — new project

```bash
uv pip install crucis
crucis init --name add --no-agent
crucis run
```

## Quick start — existing codebase

```bash
uv pip install crucis
crucis init --existing-codebase --no-agent
# Edit objective.yaml: set target_files, context_files, existing_tests
crucis run
```

## Install

```bash
uv pip install crucis        # recommended
pip install crucis            # also works
```

Requires Python 3.10+ (3.12+ recommended) and at least one agent CLI (`claude` or `codex`) on your PATH.

Source-tree development (without editable install):

```bash
./crucis-dev doctor --workspace .
./crucis-dev run
```

## Documentation

[Full docs](https://gilad12-coder.github.io/crucis/) — quickstarts, reference, configuration, troubleshooting.

- [Start Here](https://gilad12-coder.github.io/crucis/start-here/) — prerequisites and orientation
- [New Project Quickstart](https://gilad12-coder.github.io/crucis/quickstart-new-project/) — build a verified function from scratch
- [Existing Codebase Quickstart](https://gilad12-coder.github.io/crucis/quickstart-existing-codebase/) — add verification to your current project
- [CLI Reference](https://gilad12-coder.github.io/crucis/cli-reference/) — all commands and options

## License

MIT
