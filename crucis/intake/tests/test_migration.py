"""Tests for legacy-to-crucis migration helpers."""

import json

import yaml

from crucis.intake.migration import (
    migrate_checkpoint_data,
    migrate_checkpoint_file,
    migrate_objective_data,
    migrate_objective_file,
)


def test_migrate_objective_data_from_legacy_keys():
    """Legacy objective keys should map to strict new schema keys."""
    legacy = {
        "name": "add",
        "description": "Add",
        "examples": [{"input": "(1, 2)", "output": "3"}],
        "hidden_evals": [{"input": "(10, 20)", "output": "30"}],
        "functions": [{"name": "add", "public_evals": [{"input": "(2, 3)", "output": "5"}]}],
    }
    migrated = migrate_objective_data(legacy)
    assert "examples" not in migrated
    assert "functions" not in migrated
    assert migrated["train_evals"] == [{"input": "(1, 2)", "output": "3"}]
    assert migrated["holdout_evals"] == [{"input": "(10, 20)", "output": "30"}]
    assert migrated["tasks"][0]["name"] == "add"


def test_migrate_objective_data_idempotent_for_new_schema():
    """Already-new schema should survive migration unchanged in semantics."""
    new = {
        "name": "add",
        "description": "Add",
        "verification_granularity": "objective",
        "train_evals": [{"input": "(1, 2)", "output": "3"}],
        "holdout_evals": [{"input": "(10, 20)", "output": "30"}],
        "tasks": [{"name": "add", "target_files": ["src/add.py"]}],
    }
    migrated = migrate_objective_data(new)
    assert migrated["train_evals"] == new["train_evals"]
    assert migrated["holdout_evals"] == new["holdout_evals"]
    assert migrated["tasks"][0]["name"] == "add"
    assert migrated["verification_granularity"] == "objective"
    assert migrated["tasks"][0]["target_files"] == ["src/add.py"]


def test_migrate_checkpoint_data_from_legacy_keys():
    """Legacy checkpoint shape and statuses should map to new schema."""
    legacy = {
        "function_progress": [
            {
                "name": "add",
                "status": "done",
                "test_source": "def test_add(): pass",
                "critique": {
                    "exploit_vectors": ["hardcode"],
                    "missing_edge_cases": ["negatives"],
                    "suggested_counter_tests": ["randomized"],
                    "exploit_code": "def add(a,b): return 3",
                    "exploit_passed": True,
                },
            }
        ]
    }
    migrated = migrate_checkpoint_data(legacy)
    progress = migrated["task_progress"][0]
    assert progress["status"] == "complete"
    assert progress["train_suite_source"] == "def test_add(): pass"
    assert progress["adversarial_report"]["attack_vectors"] == ["hardcode"]
    assert progress["adversarial_report"]["probe_succeeded"] is True


def test_migrate_objective_file_and_checkpoint_file(tmp_path):
    """File-based migrations should write expected output files.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    objective_in = tmp_path / "spec.yaml"
    objective_out = tmp_path / "objective.yaml"
    checkpoint_in = tmp_path / "session.json"
    checkpoint_out = tmp_path / "checkpoint.json"

    objective_in.write_text(
        yaml.safe_dump(
            {
                "name": "add",
                "description": "Add",
                "public_evals": [{"input": "(1, 2)", "output": "3"}],
            }
        ),
        encoding="utf-8",
    )
    checkpoint_in.write_text(
        json.dumps({"function_progress": [{"name": "add", "status": "pending"}]}),
        encoding="utf-8",
    )

    migrate_objective_file(objective_in, objective_out)
    migrate_checkpoint_file(checkpoint_in, checkpoint_out)

    objective_data = yaml.safe_load(objective_out.read_text(encoding="utf-8"))
    checkpoint_data = json.loads(checkpoint_out.read_text(encoding="utf-8"))

    assert "train_evals" in objective_data
    assert "task_progress" in checkpoint_data


def test_migrate_objective_data_maps_constraint_profile_to_tests():
    """Legacy constraint_profile should map to tests_constraint_profile."""
    legacy = {
        "name": "add",
        "description": "Add",
        "constraint_profile": "strict",
        "tasks": [{"name": "add", "constraint_profile": "recommended"}],
    }
    migrated = migrate_objective_data(legacy)
    assert migrated["tests_constraint_profile"] == "strict"
    assert migrated["implementation_constraint_profile"] == "default"
    assert migrated["tasks"][0]["tests_constraint_profile"] == "recommended"


def test_migrate_objective_data_preserves_new_profile_fields():
    """New-schema profile fields should survive migration unchanged."""
    new = {
        "name": "add",
        "description": "Add",
        "tests_constraint_profile": "strict",
        "implementation_constraint_profile": "recommended",
        "tasks": [
            {
                "name": "add",
                "tests_constraint_profile": "default",
                "implementation_constraint_profile": "strict",
            }
        ],
    }
    migrated = migrate_objective_data(new)
    assert migrated["tests_constraint_profile"] == "strict"
    assert migrated["implementation_constraint_profile"] == "recommended"
    assert migrated["tasks"][0]["tests_constraint_profile"] == "default"
    assert migrated["tasks"][0]["implementation_constraint_profile"] == "strict"
