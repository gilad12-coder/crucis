# FAQ

## :material-rocket-launch: Getting Started

**Which Python versions are supported?**

Python 3.10+ is supported. Python 3.12+ is recommended for the best experience. Versions below 3.10 are rejected at runtime. Run `crucis doctor` to check your version.

**Do I need Docker?**

No. Docker is optional. When Docker is unavailable, Crucis runs pytest directly on the host. Use `--no-sandbox` to explicitly skip Docker. See [Troubleshooting](troubleshooting.md).

**How do I use Crucis with an existing codebase?**

Use `crucis init --existing-codebase` and set `target_files`, `context_files`, and `existing_tests` in your objective. See [Existing Codebase Quickstart](quickstart-existing-codebase.md).

**How much does it cost?**

Crucis itself is free and open source. The only cost is API calls to your chosen LLM provider. A typical run uses 2-5 API calls per task for test generation and 1-3 for implementation.

## :material-source-branch: How It Works

**What happens if fit is interrupted?**

Crucis saves the checkpoint after each task completes. Re-run the same command and it resumes from the last completed task. No work is lost.

**What are holdout evals?**

Hidden input/output pairs that are never shown to any agent. After the implementation agent writes code, Crucis runs these pairs as a final safety net to verify the implementation generalizes beyond the training examples.

You don't need to write them manually. Just list all your examples under `examples:` and Crucis automatically reserves the last ~20% as holdout evals (auto-holdout). You can still provide an explicit `holdout:` section if you prefer full control. See [Objective Format Reference](objective-reference.md).

**What does the optimizer do?**

The background optimizer (GEPA) learns better prompt strategies over time by analyzing generation outcomes across runs. It's experimental and disabled by default. To enable it, set `optimizer.enabled: true` in `.crucis/settings.yaml`. See [Background Optimizer](optimizer.md).

## :material-cog-outline: Configuration & Customization

**How do I switch between Claude and Codex?**

Edit `.crucis/settings.yaml`:

```yaml
agents:
  generation_agent: codex
  implementation_agent: claude
```

Or set environment variables: `GENERATION_AGENT=codex`. See [Configuration](configuration.md) for all agent settings.

**Can I use Crucis from Claude Code / OpenCode / Codex?**

Yes. Crucis ships an MCP server (`crucis-mcp`) that exposes every CLI command as a tool your agent can call. Add it to your MCP config and authorize the workspace:

```bash
mkdir -p .crucis && touch .crucis/mcp_enabled
```

See [MCP Server](mcp-server.md) for setup, tool reference, and the step-by-step agent workflow.

**How do I reset a failed checkpoint?**

```bash
crucis run --reset          # Reset everything
crucis run --reset-task X   # Reset one task
```

See [CLI Reference](cli-reference.md) for details.

**How do I increase the agent timeout?**

The default agent timeout is 300 seconds. For complex objectives or slow models, pass `--timeout`:

```bash
crucis run --timeout 600
```

**Do I need to write constraint profiles?**

No. Built-in defaults (`default` and `recommended`) are used when no `constraints/profiles.yaml` exists. You only need a custom profiles file if you want to adjust constraint thresholds. Constraints use a flat list format and are auto-classified as "required" (blocking) or "advisory" (non-blocking).

**How do I validate my objective?**

```bash
crucis validate objective.yaml
```

By default this runs structural checks and an LLM semantic review that verifies each eval's expected output against the described behavior. The agent streams its progress in real time.

To skip the LLM review and only run fast structural checks:

```bash
crucis validate objective.yaml --static
```

**Can I use Crucis in CI/CD?**

Yes. Use `crucis run --no-sandbox` in your CI pipeline. The CLI exits with code 0 on success and non-zero on failure, making it straightforward to integrate with GitHub Actions, GitLab CI, or any CI system.

## :material-wrench-outline: Troubleshooting

**Does Codex require a git repository?**

Yes. Codex requires a trusted git directory. Run `git init && git add -A && git commit -m "init"` before using Codex. Crucis prints a hint about this after `crucis init` when no `.git` directory exists.
