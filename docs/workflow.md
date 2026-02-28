# How It Works

Crucis automates the full test-implement-verify cycle. Here's what happens under the hood when you run the pipeline.

**Pipeline flow:** Objective → Generate → Harden → Implement → Verify

## Fit Phase

The Fit phase generates and hardens test suites. Each task is processed sequentially. A generation agent builds a pytest file from the objective, then Crucis validates it with syntax and constraint checks. An adversarial reviewer searches for attack vectors and generalization gaps. A cheating probe then builds a deliberately deceptive implementation and runs it against the suite. If the probe passes, adversarial findings feed back into test generation and the cycle restarts.

```bash
crucis run-fit          # Generate + harden tests
crucis summary          # Check Fit phase status
crucis summary task_x   # Detailed view with test source
```

## Evaluation Phase

The Evaluate phase takes the checkpoint and generates an implementation. It writes test files to disk, builds a curriculum from objective metadata and per-task details, and dispatches an implementation agent. The result is verified against both the generated train suites and hidden holdout evaluations. Holdout evals are automatically split from the last ~20% of the examples list — no manual setup needed.

```bash
crucis run-evaluate     # Implement + verify
crucis run              # Full pipeline (fit + evaluate)
```

## Adversarial Testing

The adversarial system has three components:

1. **Review** — the critic agent analyzes test quality, identifying attack strategies and gaps
2. **Probe** — a cheating implementation is generated and tested, measuring actual test robustness
3. **Feedback loop** — adversarial findings feed back into test generation, producing harder tests

This creates an arms race: better attacks produce better tests, which produce better implementations.

## Error Recovery

- **Agent timeout** — treated as a failed attempt, retried with the next iteration (default: 300s)
- **Missing agent binary** — returns exit_code=-1, retried
- **Malformed adversarial JSON** — repaired via json_repair library
- **Docker unavailable** — falls back to host pytest
- **Constraint violations** — violation details fed back to generation prompt for correction

## MCP Server Mode

Crucis is also available as an MCP server for AI agents in Claude Code, OpenCode, or Codex. The MCP server supports two modes:

- **Pipeline mode** — the agent calls `crucis_run` and Crucis manages the full loop internally
- **Step-by-step mode** — the agent acts as generator/critic/implementer itself, using tools like `crucis_get_prompt`, `crucis_submit_test_suite`, and `crucis_verify_implementation`
