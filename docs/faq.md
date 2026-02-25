# FAQ

## Which Python versions are supported?

Python 3.10+ is supported. Python 3.12+ is recommended for the best experience. Versions below 3.10 are rejected at runtime. Run `crucis doctor` to check your version.

## How do I switch between Claude and Codex?

Edit `.crucis/settings.yaml`:

```yaml
agents:
  generation_agent: codex   # or "claude"
  generation_model: null     # null = agent default
```

Or set environment variables: `GENERATION_AGENT=codex`. See [Configuration](configuration.md) for all agent settings.

## What happens if fit is interrupted?

Crucis saves the checkpoint after each task completes. Re-run the same command and it resumes from the last completed task. No work is lost.

## How do I reset a failed checkpoint?

```bash
# Reset everything (prompts for confirmation)
crucis run --reset

# Skip the confirmation prompt
crucis run --reset -y

# Reset only specific tasks
crucis run --reset-task my_task
```

See [CLI Reference](cli-reference.md#crucis-run) for details.

## How do I increase the agent timeout?

The default agent timeout is 300 seconds. For complex objectives or slow models, pass `--timeout`:

```bash
crucis run --timeout 600   # 10 minutes
```

## Do I need Docker?

No. Docker is optional. When Docker is unavailable, Crucis runs pytest directly on the host. Use `--no-sandbox` to explicitly skip Docker. See [Troubleshooting](troubleshooting.md#docker-not-available).

## What are holdout evals?

Hidden input/output pairs that are never shown to any agent. After the implementation agent writes code, Crucis runs these pairs as a final safety net to verify the implementation generalizes beyond the training examples.

You don't need to write them manually. Just list all your examples under `examples:` and Crucis automatically reserves the last ~20% as holdout evals (auto-holdout). You can still provide an explicit `holdout:` section if you prefer full control. See [Objective Format Reference](objective-reference.md#eval-schema).

## How do I use Crucis with an existing codebase?

Use `crucis init --existing-codebase` and set `target_files`, `context_files`, and `existing_tests` in your objective. See [Existing Codebase Quickstart](quickstart-existing-codebase.md).

## What does the optimizer do?

The background optimizer (GEPA) learns better prompt strategies over time by analyzing generation outcomes across runs. It's **experimental** and **disabled by default**. To enable it, set `optimizer.enabled: true` in `.crucis/settings.yaml`. See [Background Optimizer](optimizer.md).

## Do I need to write constraint profiles?

No. Built-in defaults (`default` and `recommended`) are used when no `constraints/profiles.yaml` exists. You only need a custom profiles file if you want to adjust constraint thresholds. Constraints use a flat list format and are auto-classified as "required" (blocking) or "advisory" (non-blocking).

## Does Codex require a git repository?

Yes. Codex requires a trusted git directory. Run `git init && git add -A && git commit -m "init"` before using Codex. Crucis prints a hint about this after `crucis init` when no `.git` directory exists.

## Can I use Crucis from Claude Code / OpenCode / Codex?

Yes. Crucis ships an MCP server (`crucis-mcp`) that exposes every CLI command as a tool your agent can call. Add it to your MCP config and authorize the workspace:

```bash
mkdir -p .crucis && touch .crucis/mcp_enabled
```

See [MCP Server](mcp-server.md) for setup, tool reference, and the step-by-step agent workflow.

## How do I validate my objective?

```bash
crucis validate objective.yaml
```

By default this runs structural checks **and** an LLM semantic review that verifies each eval's expected output against the described behavior. The agent streams its progress in real time.

To skip the LLM review and only run fast structural checks:

```bash
crucis validate objective.yaml --static
```
