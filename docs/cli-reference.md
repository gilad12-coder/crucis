# CLI Reference

All Crucis commands with their options.

---

## `crucis init`

Scaffold a new workspace with starter files.

```bash
crucis init [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--name` | `my_project` | Project name for the objective template |
| `--workspace` | `.` | Directory to scaffold |
| `--agent` | config default | Agent for onboarding interview (`claude` or `codex`) |
| `--no-agent` | off | Skip AI interview; use static templates |
| `--require-agent` | off | Fail if agent onboarding cannot run |
| `--existing-codebase` | off | Force existing-codebase mode (skip `src/solution.py`) |
| `--json` | off | Print machine-readable JSON |

Creates: `objective.yaml`, `constraints/profiles.yaml`, `.crucis/settings.yaml`. Creates `src/solution.py` only for new-project scaffolds.

---

## `crucis run`

Run the full pipeline: generate test suites, harden, and implement.

```bash
crucis run [objective.yaml] [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--objective` | — | Alternative to positional argument |
| `--profiles` | `constraints/profiles.yaml` | Constraint profile file |
| `--checkpoint` | `.checkpoint.json` | Checkpoint file path |
| `--workspace` | objective parent | Workspace directory |
| `--task` | — | Process only named task(s); repeatable |
| `--reset` | off | Clear entire checkpoint before starting |
| `--reset-task` | — | Clear named task(s) from checkpoint; repeatable |
| `--no-sandbox` | off | Run host pytest instead of Docker sandbox |
| `-y, --yes` | off | Skip confirmation prompts (e.g. `--reset`) |
| `--dry-run` | off | Display generation prompts without calling agents |
| `--demo` | off | Simulate workflow with canned data (no API calls) |
| `--plan` | off | Generate a structured `plan.md` instead of running |
| `--force-plan` | off | Regenerate `plan.md` even if it exists (use with `--plan`) |
| `--timeout SECONDS` | `300` | Override agent subprocess timeout |

Auto-finds `objective.yaml` in the current directory if not specified. By default, approves everything and runs the full pipeline (generate tests, harden, implement).

`--reset` and `--reset-task` are mutually exclusive. When `--reset-task` is used without `--task`, the reset tasks are automatically scoped.

`--reset` prompts for confirmation in interactive terminals. Pass `-y` to skip the prompt.

---

## `crucis status`

Show progress and optimizer status. (Alias: `crucis summary`)

```bash
crucis status [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--checkpoint` | `.checkpoint.json` | Checkpoint file path |
| `--task` | — | Show detail for a specific task |
| `--json` | off | Print machine-readable JSON |
| `--workspace` | — | Workspace root for resolving paths |

---

## `crucis validate`

Validate an objective file. By default runs both structural checks and an LLM semantic review that verifies each eval's expected output matches the described behavior. Use `--static` to skip the LLM review.

```bash
crucis validate <objective.yaml> [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--profiles` | — | Optional profiles file to validate against |
| `--workspace` | — | Workspace directory for resolving relative paths |
| `--static` | off | Run only structural checks (skip LLM semantic review) |
| `--json` | off | Print machine-readable JSON |

The semantic review catches issues like incorrect expected values in train or holdout evals, ambiguous descriptions, and contradictions between the description and the eval cases. Agent output streams to the terminal in real time.

---

## `crucis doctor`

Run environment and workspace diagnostics.

```bash
crucis doctor [OPTIONS]
```

Checks: Python version, pytest, agent binaries, API keys, agent/model coherence, Claude Code nesting, runtime settings, Docker availability.

Doctor loads workspace agent settings from `.crucis/settings.yaml` before running diagnostics, so it correctly checks the agents you've configured.

| Option | Default | Description |
|---|---|---|
| `--workspace` | `.` | Workspace root |
| `--objective` | — | Optional objective file to validate |
| `--profiles` | — | Optional profiles file to validate |
| `--checkpoint` | — | Optional checkpoint file to validate |
| `--require-docker` | off | Treat missing Docker as a hard failure |
| `-v, --verbose` | off | Show all checks including passing ones |
| `--json` | off | Print machine-readable diagnostics JSON |

---

## `crucis promote`

Promote an optimizer candidate policy to active.

```bash
crucis promote --run-id <run_id> [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--run-id` | *(required)* | Run ID of candidate to promote |
| `--workspace` | `.` | Workspace root |
| `--force` | off | Promote even when metadata is missing |
| `--json` | off | Print machine-readable JSON |

---

## `crucis optimizer-worker`

Run background optimizer worker in foreground. This command is hidden from `crucis --help` but remains available for direct use and automation scripts.

```bash
crucis optimizer-worker [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--workspace` | `.` | Workspace root |
| `--loop` | off | Run continuously instead of one-shot |
| `--json` | off | Print machine-readable JSON |

---

## Global options

| Option | Description |
|---|---|
| `-V, --version` | Show version and exit |
| `--verbose` | Show all diagnostic details |
| `--quiet` | Suppress informational output |
| `--color` | Force colored output even when not a TTY |
| `--no-color` | Disable colored output |

`--verbose` and `--quiet` are mutually exclusive. `--color` and `--no-color` are mutually exclusive.

Crucis also respects the `NO_COLOR` environment variable (see [no-color.org](https://no-color.org/)). `--color` overrides `NO_COLOR` when both are set.

---

## Output conventions

- **Data output** (JSON from `--json` flags) goes to **stdout**.
- **UI output** (Rich-formatted messages, tables, spinners, prompts) goes to **stderr**.

This means you can pipe JSON output to other tools without UI noise:

```bash
crucis status --json | jq '.task_progress'
crucis validate objective.yaml --json > result.json
```

Error messages include actionable hints where possible:

```
Error: No objective file specified and no objective.yaml in current directory.
Hint: Check the path or run 'crucis init' to create one.
```

---

## MCP server alternative

Every CLI command above is also available as an MCP tool via `crucis-mcp`. If you use Claude Code, OpenCode, or Codex, you can add Crucis as an MCP server and call these commands directly from your agent. See [MCP Server](mcp-server.md) for setup and the full tool reference.
