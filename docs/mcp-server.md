# MCP Server

Crucis ships an [MCP](https://modelcontextprotocol.io/) (Model Context Protocol) server that exposes the entire TDD pipeline as tools, resources, and prompts. AI agents running inside Claude Code, OpenCode, Codex, or any MCP-compatible host can use Crucis natively without shelling out to the CLI.

---

## Quick start

### 1. Authorize the workspace

Before the MCP server will operate on a workspace, the workspace must explicitly opt in. Choose one method:

=== "Marker file (recommended)"

    ```bash
    mkdir -p .crucis && touch .crucis/mcp_enabled
    ```

=== "Environment variable"

    ```bash
    export CRUCIS_MCP_AUTHORIZED=1
    ```

### 2. Configure your MCP host

Add the Crucis server to your host's MCP configuration.

=== "Claude Code"

    ```json
    {
      "mcpServers": {
        "crucis": {
          "command": "crucis-mcp",
          "env": {
            "CRUCIS_WORKSPACE": "/path/to/your/project",
            "CRUCIS_MCP_AUTHORIZED": "1"
          }
        }
      }
    }
    ```

=== "Generic STDIO"

    ```bash
    crucis-mcp
    # or
    python -m crucis.mcp
    ```

The server communicates over **STDIO** using JSON-RPC, the standard MCP transport.

### 3. Use the tools

Once connected, your agent can call any of the 19 tools. Every response includes `next_steps` telling the agent what to do next:

```
crucis_validate → crucis_doctor → crucis_run → crucis_summary
```

---

## Two modes of operation

### Pipeline mode

Crucis spawns its own subprocess agents (Claude, Codex) to handle generation, adversarial review, and implementation. You call a single tool like `crucis_run` and get results when done.

Best for: automated workflows, CI-style runs, hands-off execution.

### Step-by-step mode

Your agent acts as the generator, critic, and implementer. Crucis provides the prompts, validates your work, and verifies correctness.

Best for: interactive development, learning the TDD flow, fine-grained control.

```
crucis_get_prompt(step="generation") → write tests yourself →
crucis_submit_test_suite → crucis_run_probe → crucis_write_tests →
implement code → crucis_verify_implementation
```

---

## Tools (19)

### Pipeline tools

| Tool | Annotation | Description |
|---|---|---|
| `crucis_init` | mutating | Scaffold a workspace with starter files |
| `crucis_run` | llm | Full pipeline: fit + evaluate (spawns agents) |
| `crucis_run_fit` | llm | Fit phase only: generate and harden tests |
| `crucis_run_evaluate` | llm | Evaluate phase only: implement and verify |
| `crucis_run_plan` | llm | Generate a structured plan.md |
| `crucis_dry_run` | read-only | Preview pipeline config without API calls |
| `crucis_reset` | destructive | Reset checkpoint (all tasks or specific ones) |
| `crucis_validate` | read-only | Validate objective.yaml structure and semantics |
| `crucis_summary` | read-only | Pipeline status and per-task progress |
| `crucis_doctor` | read-only | Environment and workspace diagnostics |
| `crucis_promote` | mutating | Promote an optimizer candidate to active |
| `crucis_optimizer_worker` | llm | Run background optimizer |
| `crucis_check_constraints` | read-only | Check source code against constraint profiles |

### Step-by-step tools

| Tool | Annotation | Description |
|---|---|---|
| `crucis_get_prompt` | read-only | Get the system prompt for any pipeline step |
| `crucis_submit_test_suite` | mutating | Save and validate an agent-written test suite |
| `crucis_submit_adversarial_report` | mutating | Save adversarial review findings |
| `crucis_run_probe` | llm | Run cheating probe against test suite |
| `crucis_write_tests` | mutating | Materialize checkpoint tests to disk |
| `crucis_verify_implementation` | read-only | Run tests + holdout evals against code |

---

## Resources (7)

Read-only data your agent can pull for context.

| URI | Content |
|---|---|
| `crucis://objective` | Parsed objective definition (JSON) |
| `crucis://checkpoint` | Full checkpoint state (JSON) |
| `crucis://task/{name}/test-suite` | Generated test suite source for a task |
| `crucis://task/{name}/adversarial-report` | Adversarial report for a task (JSON) |
| `crucis://constraints/{profile}` | Constraint profile definition (JSON) |
| `crucis://plan` | Generated plan.md content |
| `crucis://curriculum` | Implementation brief markdown |

---

## Prompts (5)

Canned workflow templates your agent can invoke.

| Prompt | Description |
|---|---|
| `setup-crucis` | Guide: scaffold workspace and configure objective |
| `tdd-workflow` | Guide: full pipeline run with subprocess agents |
| `verify-code-quality` | Guide: check a source file against constraints |
| `harden-tests` | Guide: run fit phase and review adversarial findings |
| `agent-tdd-workflow` | Guide: step-by-step TDD where the agent does everything |

---

## Agent-friendly design

The MCP server is designed to minimize round-trips and guide agents through workflows.

### Tool annotations

Every tool declares its safety profile via MCP tool annotations. MCP clients that support annotations can auto-approve read-only tools and prompt for destructive ones.

| Annotation | Tools | Meaning |
|---|---|---|
| `readOnlyHint` | validate, summary, doctor, dry_run, check_constraints, get_prompt, verify_implementation | Safe to auto-approve — no side effects |
| `destructiveHint` | reset | Deletes data — prompt for confirmation |
| `openWorldHint` | run, run_fit, run_evaluate, run_plan, run_probe, optimizer_worker | Calls external LLMs — may incur cost |
| *(mutating)* | init, promote, submit_test_suite, submit_adversarial_report, write_tests | Writes files or state |

### Next-step hints

Every tool response includes a `next_steps` array that tells the agent exactly what to do next. The hints are contextual — success and failure produce different guidance:

```json
{
  "valid": true,
  "name": "calculator",
  "next_steps": [
    "Run crucis_doctor to check environment prerequisites",
    "Run crucis_dry_run to preview the pipeline configuration",
    "Run crucis_run to execute the full pipeline"
  ]
}
```

### Structured errors

Error responses include the exception type and an actionable hint:

```json
{
  "error": "Objective validation failed: ...",
  "error_type": "ValueError",
  "hint": "Fix the issue and retry."
}
```

### Pre-validation

Long-running tools (`crucis_run`, `crucis_run_fit`) pre-validate the objective and profiles before starting the pipeline. This catches typos and missing files immediately instead of failing minutes later.

### Smart output truncation

`crucis_verify_implementation` keeps the **tail** of pytest output (where failures and the summary appear) rather than the head, so agents can see what actually failed.

---

## Security

The MCP server enforces several security boundaries.

### Workspace authorization

Every tool call verifies the workspace is authorized before proceeding. A workspace must opt in via one of:

- **Marker file**: `.crucis/mcp_enabled` in the workspace root
- **Environment variable**: `CRUCIS_MCP_AUTHORIZED=1`

Unauthorized workspaces receive a `WorkspaceNotAuthorizedError`.

### Path traversal prevention

All file path arguments are validated against the workspace boundary:

- Paths are resolved (including symlinks) before checking containment
- Null bytes in paths are rejected
- Paths exceeding 4,096 characters are rejected
- Any resolved path outside the workspace is blocked with a `PathTraversalError`

### Input size limits

Source code inputs (for `crucis_check_constraints` and `crucis_submit_test_suite`) are limited to **1 MB** to prevent resource exhaustion.

### Credential handling

API keys and secrets are read from environment variables, never from tool parameters. The server itself stores no credentials.

### STDIO isolation

The server redirects Rich console output to stderr to prevent UI text from corrupting the JSON-RPC protocol on stdout.

---

## Common parameters

Most tools accept these optional parameters:

| Parameter | Description |
|---|---|
| `workspace` | Workspace directory. Defaults to `CRUCIS_WORKSPACE` env var or cwd. |
| `objective_path` | Path to objective YAML. Defaults to `objective.yaml` in workspace. |
| `profiles` | Path to constraint profiles YAML. Defaults to `constraints/profiles.yaml`. |
| `checkpoint` | Path to checkpoint JSON. Defaults to `.checkpoint.json`. |

All paths can be relative (resolved against workspace) or absolute (validated to stay within workspace).

---

## Tool reference

### `crucis_init`

Scaffold a new Crucis workspace with starter files. Use as the first step when starting a new project.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `name` | string | `"my_project"` | Project name for the objective template |
| `existing_codebase` | bool | `false` | Treat workspace as an existing codebase |
| `workspace` | string | — | Workspace directory |

Returns: `{"workspace": "...", "created": [...], "existing_codebase": bool, "next_steps": [...]}`

### `crucis_run`

Run the complete pipeline: fit then evaluate. Pre-validates objective and profiles before starting. Use `crucis_dry_run` first to preview without API calls.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `objective_path` | string | — | Path to objective YAML |
| `task_names` | list[string] | — | Specific tasks to process |
| `no_sandbox` | bool | `true` | Run pytest on host instead of Docker |
| `profiles` | string | — | Path to profiles YAML |
| `checkpoint` | string | — | Path to checkpoint JSON |
| `workspace` | string | — | Workspace directory |

Returns: Checkpoint summary with per-task status and contextual `next_steps`.

### `crucis_run_fit`

Run the fit phase only: generate test suites and harden them adversarially. Pre-validates before starting. Same parameters as `crucis_run` (minus `no_sandbox`).

### `crucis_run_evaluate`

Run the evaluate phase: implement code and verify. Requires fit phase complete. Same parameters as `crucis_run`. Use `crucis_summary` to check readiness before calling.

### `crucis_run_plan`

Generate a structured plan.md for test-suite generation strategy.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `objective_path` | string | — | Path to objective YAML |
| `force` | bool | `false` | Regenerate even if plan.md exists |
| `profiles` | string | — | Path to profiles YAML |
| `workspace` | string | — | Workspace directory |

Returns: `{"plan_path": "...", "content": "...", "next_steps": [...]}`

### `crucis_dry_run`

Preview what the pipeline would do without calling any LLM agents. Returns task names, descriptions, current status, constraint profiles with thresholds, eval counts, and resolved file paths.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `objective_path` | string | — | Path to objective YAML |
| `task_names` | list[string] | — | Specific tasks to preview |
| `profiles` | string | — | Path to profiles YAML |
| `workspace` | string | — | Workspace directory |

Returns:

```json
{
  "dry_run": true,
  "objective_name": "calculator",
  "has_plan": false,
  "tasks": [
    {
      "task_name": "add",
      "description": "Return the sum of two integers.",
      "current_status": "pending",
      "has_existing_suite": false,
      "constraint_profile": "recommended",
      "primary_constraints": {
        "max_complexity": 10,
        "max_lines_per_function": 50
      },
      "train_eval_count": 3,
      "holdout_eval_count": 1
    }
  ],
  "resolved_paths": {
    "objective": "/path/to/objective.yaml",
    "profiles": "/path/to/profiles.yaml",
    "checkpoint": "/path/to/.checkpoint.json"
  },
  "next_steps": [...]
}
```

### `crucis_reset`

Reset checkpoint state. Destructive — deletes progress.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `task_names` | list[string] | — | Tasks to reset. Omit to reset all. |
| `checkpoint` | string | — | Path to checkpoint JSON |
| `workspace` | string | — | Workspace directory |

### `crucis_validate`

Validate an objective YAML file. Fast read-only check. Set `static=true` to skip the LLM semantic review.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `objective_path` | string | — | Path to objective YAML |
| `profiles` | string | — | Path to profiles YAML to validate against |
| `workspace` | string | — | Workspace directory |
| `static` | bool | `false` | Skip LLM semantic review |

Returns: `{"valid": bool, "name": "...", "tasks": [...], "issues": [...], "next_steps": [...]}`

### `crucis_summary`

Get pipeline status from the checkpoint. Without `task_name`: overview of all tasks. With `task_name`: detailed view including test suite source and adversarial report. Returns contextual `next_steps` based on the current pipeline state.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `task_name` | string | — | Get detail for a specific task |
| `checkpoint` | string | — | Path to checkpoint JSON |
| `workspace` | string | — | Workspace directory |

### `crucis_doctor`

Run environment diagnostics. Read-only health check. Returns failed checks with their remediation hints as `next_steps`.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `workspace` | string | — | Workspace directory |
| `objective_path` | string | — | Objective file to validate |
| `profiles` | string | — | Profiles file to validate |
| `checkpoint` | string | — | Checkpoint file to validate |
| `require_docker` | bool | `false` | Treat missing Docker as failure |

Returns: `{"ok": bool, "checks": [{"id": "...", "status": "ok|warn|fail", "message": "...", "hint": "..."}], "next_steps": [...]}`

### `crucis_promote`

Promote an optimizer candidate policy to active. Returns the full optimizer state after promotion.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `run_id` | string | *(required)* | Run ID to promote |
| `force` | bool | `false` | Skip readiness checks |
| `workspace` | string | — | Workspace directory |

Returns: `{"run_id": "...", "promoted": true, "optimizer_state": {...}}`

### `crucis_optimizer_worker`

Run the background optimizer worker.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `loop` | bool | `false` | Run continuously |
| `workspace` | string | — | Workspace directory |

### `crucis_check_constraints`

Check Python source code against constraint profiles. Read-only static analysis. Reports primary (blocking) and secondary (advisory) results with full metrics.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `source_code` | string | *(required)* | Python source to check (max 1 MB) |
| `task_name` | string | — | Task for constraint overrides |
| `scope` | string | `"tests"` | `"tests"` or `"implementation"` |
| `objective_path` | string | — | Path to objective YAML |
| `profiles` | string | — | Path to profiles YAML |

Returns: `{"primary": {"passed": bool, "violations": [...], "metrics": {...}}, "secondary": {...}, "next_steps": [...]}`

### `crucis_get_prompt`

Get the system prompt for any pipeline step. Read-only — use this in step-by-step mode to get the prompt, then do the work yourself.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `step` | string | *(required)* | `"generation"`, `"adversary"`, or `"evaluation"` |
| `task_name` | string | — | Task name (required for generation/adversary) |
| `constraint_feedback` | string | `""` | Constraint feedback for generation retry |
| `adversary_feedback` | string | `""` | Adversarial feedback for generation retry |
| `error_feedback` | string | `""` | Error feedback for evaluation retry |

Returns: `{"step": "...", "prompt": "...", "task_name": "...", "next_steps": [...]}`

### `crucis_submit_test_suite`

Save an agent-generated test suite. Validates syntax (AST parse) and constraints, then saves to checkpoint. If constraints fail, fix violations and resubmit.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `task_name` | string | *(required)* | Task this suite belongs to |
| `test_source` | string | *(required)* | Complete pytest source code (max 1 MB) |

Returns: `{"accepted": bool, "syntax_valid": bool, "constraints_passed": bool, "primary": {...}, "secondary": {...}, "next_steps": [...]}`

### `crucis_submit_adversarial_report`

Save adversarial findings. Returns a `findings_count` summary showing how many items were submitted in each category.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `task_name` | string | *(required)* | Task this report belongs to |
| `attack_vectors` | list[string] | *(required)* | Ways a cheat could pass |
| `generalization_gaps` | list[string] | *(required)* | Missing edge cases |
| `suggested_probe_tests` | list[string] | *(required)* | Test cases to probe weaknesses |
| `correctness_issues` | list[string] | `[]` | Issues with test correctness |

Returns: `{"accepted": true, "task_status": "adversarially_reviewed", "findings_count": {...}, "next_steps": [...]}`

### `crucis_run_probe`

Run a cheating probe against a task's test suite. If `probe_passed=true`, the tests are **weak** (a cheat passes them — regenerate). If `probe_passed=false`, the tests are **robust** (proceed to implement).

| Parameter | Type | Default | Description |
|---|---|---|---|
| `task_name` | string | *(required)* | Task whose tests to probe |

Returns: `{"probe_passed": bool, "tests_are_weak": bool, "probe_code": "...", "next_steps": [...]}`

### `crucis_write_tests`

Write test suites from checkpoint to disk. Required before `crucis_verify_implementation`.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `test_dir` | string | `"tests"` | Directory for test files |

Returns: `{"written": ["tests/test_add.py", ...], "test_count": 3, "next_steps": [...]}`

### `crucis_verify_implementation`

Run tests and holdout evals to verify implementation. The `test_output` field contains the **tail** of pytest output (last 4000 chars, where failures appear).

| Parameter | Type | Default | Description |
|---|---|---|---|
| `task_name` | string | — | Specific task to verify |
| `no_sandbox` | bool | `true` | Skip Docker sandbox |
| `test_dir` | string | `"tests"` | Directory with test files |

Returns: `{"tests_passed": bool, "holdout_passed": bool, "overall": bool, "test_output": "...", "next_steps": [...]}`

---

## Environment variables

| Variable | Description |
|---|---|
| `CRUCIS_WORKSPACE` | Override workspace path (instead of cwd) |
| `CRUCIS_MCP_AUTHORIZED` | Set to `1` to authorize workspace for MCP access |
| `ANTHROPIC_API_KEY` | API key for Claude agent |
| `OPENAI_API_KEY` | API key for Codex agent |

All standard Crucis environment variables are respected. See [Configuration](configuration.md) for the full list.
