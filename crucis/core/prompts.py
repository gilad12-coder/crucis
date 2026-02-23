"""Prompt builders for generation, adversarial review, and evaluation."""

from pathlib import Path

from crucis.models import ParsedObjective, TaskConstraints
from crucis.persistence.policy import OptimizerPolicy
from crucis.prompts import render


def build_generation_prompt(
    objective: ParsedObjective,
    constraints: TaskConstraints,
    constraint_feedback: str = "",
    adversarial_feedback: str = "",
    policy: OptimizerPolicy | None = None,
    plan_content: str = "",
    context_files_content: dict[str, str] | None = None,
) -> str:
    """Build a prompt for generating pytest train-suite tests from an objective.

    Args:
        objective: Parsed objective data for the current run.
        constraints: Resolved constraints for the current task or objective.
        constraint_feedback: Constraint failure feedback from the prior generation attempt.
        adversarial_feedback: Value for `adversarial_feedback` used by `build_generation_prompt`.
        policy: Active optimizer policy used for prompt steering.
        plan_content: Optional structured plan from plan.md to guide generation.
        context_files_content: Existing file contents keyed by relative path.

    Returns:
        Computed text result for this operation.
    """
    return render(
        "generation.jinja2",
        objective=objective,
        constraints=constraints,
        constraint_feedback=constraint_feedback,
        adversarial_feedback=adversarial_feedback,
        policy=policy,
        plan_content=plan_content,
        context_files_content=context_files_content or {},
    )


def build_adversary_prompt(
    train_suite_source: str,
    objective: ParsedObjective,
    constraints: TaskConstraints | None = None,
    policy: OptimizerPolicy | None = None,
) -> str:
    """Build an adversarial prompt to attack train-suite quality.

    Args:
        train_suite_source: Generated pytest train-suite source code.
        objective: Parsed objective data for the current run.
        constraints: Resolved constraints for the current task or objective.
        policy: Active optimizer policy used for prompt steering.

    Returns:
        Computed text result for this operation.
    """
    return render(
        "adversary.jinja2",
        train_suite_source=train_suite_source,
        objective=objective,
        constraints=constraints,
        policy=policy,
    )


def build_probe_prompt(
    train_suite_source: str,
    objective: ParsedObjective,
    policy: OptimizerPolicy | None = None,
) -> str:
    """Build a prompt for generating a deliberately cheating probe.

    Args:
        train_suite_source: Generated pytest train-suite source code.
        objective: Parsed objective data for the current run.
        policy: Active optimizer policy used for prompt steering.

    Returns:
        Computed text result for this operation.
    """
    return render(
        "probe.jinja2",
        train_suite_source=train_suite_source,
        objective=objective,
        policy=policy,
    )


def build_evaluation_prompt(
    test_paths: list[Path],
    curriculum_path: Path | None = None,
    error_feedback: str = "",
    policy: OptimizerPolicy | None = None,
) -> str:
    """Build the evaluation-agent prompt from generated train suite file paths.

    Args:
        test_paths: Value for `test_paths` used by `build_evaluation_prompt`.
        curriculum_path: Filesystem path for `curriculum_path`.
        error_feedback: Value for `error_feedback` used by `build_evaluation_prompt`.
        policy: Active optimizer policy used for prompt steering.

    Returns:
        Computed text result for this operation.
    """
    if not test_paths:
        return "No generated train suites were provided. Make no changes."

    files = ", ".join(str(path) for path in test_paths)
    return render(
        "evaluation.jinja2",
        files=files,
        curriculum_path=curriculum_path,
        error_feedback=error_feedback,
        policy=policy,
    )
