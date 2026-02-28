# MCP Server

Crucis ships an MCP (Model Context Protocol) server that exposes its autonomy scaffold as tools, resources, and prompts. AI agents running inside Claude Code, OpenCode, Codex, or any MCP-compatible host can use Crucis natively without shelling out to the CLI.

## Two modes of operation

**Pipeline mode** — Crucis spawns its own subprocess agents (Claude, Codex) to handle generation, adversarial review, and implementation. You call a single tool like `crucis_run` and get results when done. Best for: automated workflows, CI-style runs, hands-off execution.

**Step-by-step mode** — Your agent acts as the generator, critic, and implementer. Crucis provides the prompts, validates your work, and verifies correctness. Best for: interactive development, learning the TDD flow, fine-grained control.

## Quick start

```bash
# 1. Authorize the workspace
mkdir -p .crucis && touch .crucis/mcp_enabled
# or: export CRUCIS_MCP_AUTHORIZED=1

# 2. Configure your MCP host
# .mcp.json
```

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

```bash
# 3. Use the tools (19 available)
crucis_validate -> crucis_doctor -> crucis_run -> crucis_summary
```

## Tools (19)

| Tool | Annotation | Description |
|---|---|---|
| `crucis_run` | llm | Full pipeline: fit + evaluate (spawns agents) |
| `crucis_run_fit` | llm | Fit phase only: generate and harden tests |
| `crucis_run_evaluate` | llm | Evaluate phase only: implement and verify |
| `crucis_get_prompt` | read-only | Get the system prompt for any pipeline step |
| `crucis_submit_test_suite` | mutating | Save and validate an agent-written test suite |
| `crucis_validate` | read-only | Validate objective.yaml structure and semantics |
| `crucis_summary` | read-only | Pipeline status and per-task progress |
| `crucis_run_probe` | llm | Run cheating probe against test suite |
| `crucis_doctor` | read-only | Environment and workspace diagnostics |
| `crucis_init` | mutating | Scaffold a workspace with starter files |
| `crucis_run_plan` | llm | Generate a structured plan.md |
| `crucis_dry_run` | read-only | Preview pipeline config without API calls |
| `crucis_reset` | destructive | Reset checkpoint (all tasks or specific ones) |
| `crucis_submit_adversarial_report` | mutating | Save adversarial review findings |
| `crucis_write_tests` | mutating | Materialize checkpoint tests to disk |
| `crucis_verify_implementation` | read-only | Run tests + holdout evals against code |
| `crucis_promote` | mutating | Promote an optimizer candidate to active (requires optimizer enabled) |
| `crucis_optimizer_worker` | llm | Run background optimizer (requires optimizer enabled) |
| `crucis_check_constraints` | read-only | Check source code against required/advisory constraints |

## Resources (7)

| Resource URI | Description |
|---|---|
| `crucis://objective` | Parsed objective definition (JSON) |
| `crucis://checkpoint` | Full checkpoint state (JSON) |
| `crucis://task/{name}/test-suite` | Generated test suite source for a task |
| `crucis://task/{name}/adversarial-report` | Adversarial report for a task (JSON) |
| `crucis://constraints/{profile}` | Constraint profile definition (JSON) |
| `crucis://plan` | Generated plan.md content |
| `crucis://curriculum` | Implementation brief markdown |

## Security

**Workspace authorization** — Every tool call verifies the workspace is authorized before proceeding. A workspace must opt in via a marker file (`.crucis/mcp_enabled`) or the environment variable `CRUCIS_MCP_AUTHORIZED=1`. Unauthorized workspaces receive a `WorkspaceNotAuthorizedError`.

**Path traversal prevention** — All file path arguments are resolved (including symlinks) and checked against the workspace boundary. Null bytes in paths are rejected. Paths exceeding 4,096 characters are rejected. Any resolved path outside the workspace is blocked with a `PathTraversalError`.

**Input size limits** — Source code inputs (for `crucis_check_constraints` and `crucis_submit_test_suite`) are limited to 1 MB to prevent resource exhaustion.

**Credential handling** — API keys and secrets are read from environment variables, never from tool parameters. The server itself stores no credentials.

**STDIO isolation** — The server redirects Rich console output to stderr to prevent UI text from corrupting the JSON-RPC protocol on stdout.

## Prompts (5)

Canned workflow templates your agent can invoke.

| Prompt | Description |
|---|---|
| `setup-crucis` | Guide: scaffold workspace and configure objective (uses auto-holdout) |
| `tdd-workflow` | Guide: full pipeline run with subprocess agents |
| `verify-code-quality` | Guide: check a source file against required/advisory constraints |
| `harden-tests` | Guide: run fit phase and review adversarial findings |
| `agent-tdd-workflow` | Guide: step-by-step TDD where the agent does everything |

## Agent-friendly design

The MCP server is designed to minimize round-trips and guide agents through workflows.

**Tool annotations** — Every tool declares its safety profile via MCP tool annotations. MCP clients that support annotations can auto-approve read-only tools and prompt for destructive ones.

**Next-step hints** — Every tool response includes a `next_steps` array that tells the agent exactly what to do next. The hints are contextual: success and failure produce different guidance.

**Structured errors** — Error responses include the exception type and an actionable hint.

**Pre-validation** — Long-running tools (`crucis_run`, `crucis_run_fit`) pre-validate the objective and profiles before starting. This catches typos and missing files immediately instead of failing minutes later.

**Smart output truncation** — `crucis_verify_implementation` keeps the tail of pytest output (where failures and the summary appear) rather than the head, so agents can see what actually failed.
