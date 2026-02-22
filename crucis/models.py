"""Pydantic models for Crucis objective, checkpoint, and reports."""

import ast
from enum import StrEnum

from pydantic import BaseModel, Field

_INPUT_KEY = "input"
_OUTPUT_KEY = "output"


class ConstraintSet(BaseModel):
    """A set of optional code quality constraints."""

    max_cyclomatic_complexity: int | None = Field(default=None, ge=1)
    max_lines_per_function: int | None = Field(default=None, ge=1)
    count_docstrings_in_function_lines: bool = True
    max_total_lines: int | None = Field(default=None, ge=1)
    max_time_complexity: str | None = None
    max_parameters: int | None = Field(default=None, ge=0)
    max_nested_depth: int | None = Field(default=None, ge=1)
    max_return_statements: int | None = Field(default=None, ge=1)
    require_docstrings: bool | None = None
    no_print_statements: bool | None = None
    no_star_imports: bool | None = None
    no_mutable_defaults: bool | None = None
    no_global_state: bool | None = None
    allowed_imports: list[str] | None = None

    # Correctness
    no_bare_except: bool | None = None
    no_try_except_pass: bool | None = None
    no_return_in_finally: bool | None = None
    no_unreachable_code: bool | None = None
    no_duplicate_dict_keys: bool | None = None
    no_loop_variable_closure: bool | None = None
    no_mutable_call_in_defaults: bool | None = None
    no_shadowing_builtins: bool | None = None
    no_open_without_context_manager: bool | None = None

    # Security
    no_eval: bool | None = None
    no_exec: bool | None = None
    no_unsafe_deserialization: bool | None = None
    no_unsafe_yaml: bool | None = None
    no_shell_true: bool | None = None
    no_hardcoded_secrets: bool | None = None
    no_requests_without_timeout: bool | None = None

    # Maintainability
    max_cognitive_complexity: int | None = Field(default=None, ge=1)
    max_local_variables: int | None = Field(default=None, ge=1)
    no_debugger_statements: bool | None = None
    no_nested_imports: bool | None = None
    require_type_annotations: bool | None = None
    no_magic_numbers: bool | None = None
    max_string_literal_repeats: int | None = Field(default=None, ge=1)


class TaskConstraints(BaseModel):
    """Primary and secondary constraint sets with target files."""

    primary: ConstraintSet
    secondary: ConstraintSet
    target_files: list[str]
    guidance: list[str] = Field(default_factory=list)


class CLIResult(BaseModel):
    """Result from running a CLI subprocess."""

    stdout: str
    stderr: str
    exit_code: int
    parsed_json: dict | None = None


class TrainEval(BaseModel):
    """Visible evaluation case used during test generation and critique."""

    input: str
    output: str


class HoldoutEval(BaseModel):
    """Hidden evaluation case used only in final verification."""

    input: str
    output: str


class VerificationGranularity(StrEnum):
    """Verification unit granularity for evaluation and optimizer scoring."""

    task = "task"
    objective = "objective"


class TaskObjective(BaseModel):
    """Task-level objective for multi-task objective files."""

    name: str
    description: str = ""
    signature: str | None = None
    train_evals: list[TrainEval] = Field(default_factory=list)
    holdout_evals: list[HoldoutEval] = Field(default_factory=list)
    tests_constraint_profile: str | None = None
    implementation_constraint_profile: str | None = None
    target_files: list[str] = Field(default_factory=list)


class ParsedObjective(BaseModel):
    """A parsed objective loaded from YAML."""

    name: str
    description: str
    train_evals: list[TrainEval] = Field(default_factory=list)
    holdout_evals: list[HoldoutEval] = Field(default_factory=list)
    signature: str | None = None
    tests_constraint_profile: str = "default"
    implementation_constraint_profile: str = "default"
    target_files: list[str] = Field(default_factory=list)
    tasks: list[TaskObjective] = Field(default_factory=list)
    verification_granularity: VerificationGranularity = VerificationGranularity.task


class AdversarialReport(BaseModel):
    """Adversarial report of generated train-suite quality."""

    __test__ = False

    attack_vectors: list[str]
    generalization_gaps: list[str]
    suggested_probe_tests: list[str]
    probe_code: str | None = None
    probe_succeeded: bool = False


class ConstraintResult(BaseModel):
    """Result of checking constraints against source code."""

    passed: bool
    violations: list[str]
    metrics: dict


class TrainingStatus(StrEnum):
    """Progress status for a task in checkpoint state."""

    pending = "pending"
    train_suite_generated = "train_suite_generated"
    train_suite_approved = "train_suite_approved"
    adversarially_reviewed = "adversarially_reviewed"
    complete = "complete"


class TaskProgress(BaseModel):
    """Tracks progress of one task through the training loop."""

    name: str
    status: TrainingStatus = TrainingStatus.pending
    train_suite_source: str | None = None
    adversarial_report: AdversarialReport | None = None


class CheckpointState(BaseModel):
    """Persisted state of a crucis checkpoint."""

    task_progress: list[TaskProgress]


def validate_eval_expression(expr: str, owner: str, field: str, idx: int) -> None:
    """Validate that an eval expression parses in eval mode.

    Args:
        expr: Expression string to parse and validate.
        owner: Owner path used for validation error messages.
        field: Field name used for validation error messages.
        idx: Index of the eval entry being validated.
    """
    try:
        ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"{owner}[{idx}].{field} is not a valid expression: {exc.msg}") from exc


def validate_holdout_eval_entries(holdout_evals: list[dict], owner: str) -> None:
    """Validate strict holdout schema and expression syntax.

    Args:
        holdout_evals: Value for `holdout_evals` used by `validate_holdout_eval_entries`.
        owner: Owner path used for validation error messages.
    """
    for idx, item in enumerate(holdout_evals):
        if not isinstance(item, dict):
            raise ValueError(f"{owner}[{idx}] must be a mapping")
        if "raw" in item:
            raise ValueError(f"{owner}[{idx}] does not support raw")
        if _INPUT_KEY not in item or _OUTPUT_KEY not in item:
            raise ValueError(f"{owner}[{idx}] must contain both input and output")
        if not isinstance(item[_INPUT_KEY], str) or not isinstance(item[_OUTPUT_KEY], str):
            raise ValueError(f"{owner}[{idx}] input/output must be strings")
        validate_eval_expression(item[_INPUT_KEY], owner, _INPUT_KEY, idx)
        validate_eval_expression(item[_OUTPUT_KEY], owner, _OUTPUT_KEY, idx)
