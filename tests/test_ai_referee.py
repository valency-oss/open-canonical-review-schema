# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for the ai_referee schema field.

Regression coverage for the `aiReferee` definition, which previously set
`additionalProperties: false` with no sibling `properties` block. Under JSON
Schema draft 2020-12 that combination rejects every key, because
`additionalProperties` does not see properties declared inside `oneOf`
subschemas -- so no AI referee document could validate at all.
"""

import pytest
from jsonschema import ValidationError

from ocrs import validate_canonical

AI_SYSTEM = {
    "critic_framework": {"name": "ReviewCritic", "version": "2.1.0"},
    "models": [{"role": "reviewer", "model_id": "gpt-4o"}],
}

AI_EXECUTION = {
    "started_at": "2026-01-01T00:00:00Z",
    "ended_at": "2026-01-01T00:01:00Z",
}

AI_REFERENCE = {
    "third_party_id": "newco-ai-ref-2sd4f6a",
    "display_name": "NewCo AI Referee",
    "version": "v2",
}


def _review(referee):
    """Create a minimal valid review carrying the given referee block."""
    return {
        "review_id": "test_ai_001",
        "version": "1.0.0",
        "created_at": "2025-01-15T14:30:00Z",
        "provenance": {"source_system": "test"},
        "referees": [referee],
        "target": {"work_id": "internal_id:manuscript_id:paper_123", "work_type": "article"},
        "opinion": {"summary": "Test review."},
    }


class TestAiRefereeAccepted:
    """Both AI referee forms must validate."""

    def test_full_provenance(self):
        """An AI referee with system and execution provenance is valid."""
        validate_canonical(
            _review(
                {
                    "referee_type": "ai",
                    "identity_mode": "open",
                    "ai_referee": {"system": AI_SYSTEM, "execution": AI_EXECUTION},
                }
            )
        )

    def test_full_provenance_with_optional_blocks(self):
        """The optional inputs/outputs/safety blocks are permitted."""
        validate_canonical(
            _review(
                {
                    "referee_type": "ai",
                    "identity_mode": "open",
                    "ai_referee": {
                        "system": AI_SYSTEM,
                        "execution": AI_EXECUTION,
                        "inputs": {"prompts": [{"role": "system", "prompt_hash": "sha256:abc123"}]},
                        "outputs": {"token_usage": {"input_tokens": 12000, "output_tokens": 900}},
                        "safety": {
                            "guardrails_triggered": False,
                            "pii_handling": "not_applicable",
                        },
                    },
                }
            )
        )

    def test_lightweight_reference(self):
        """An AI referee given only as a third-party reference is valid."""
        validate_canonical(
            _review(
                {
                    "referee_type": "ai",
                    "identity_mode": "open",
                    "ai_referee": {"reference": AI_REFERENCE},
                }
            )
        )

    def test_hybrid_referee(self):
        """A hybrid referee carries both ai_referee and hybrid_workflow."""
        validate_canonical(
            _review(
                {
                    "referee_type": "hybrid",
                    "identity_mode": "open",
                    "ai_referee": {"system": AI_SYSTEM, "execution": AI_EXECUTION},
                    "hybrid_workflow": {
                        "human_contributions": [
                            {"type": "final_approval", "time_spent_minutes": 15}
                        ]
                    },
                }
            )
        )


class TestAiRefereeRejected:
    """Constraints that must keep holding after the fix."""

    def test_unknown_key_rejected(self):
        """additionalProperties: false still rejects unknown keys."""
        with pytest.raises(ValidationError):
            validate_canonical(
                _review(
                    {
                        "referee_type": "ai",
                        "identity_mode": "open",
                        "ai_referee": {
                            "system": AI_SYSTEM,
                            "execution": AI_EXECUTION,
                            "not_a_real_field": True,
                        },
                    }
                )
            )

    def test_both_forms_at_once_rejected(self):
        """The two oneOf branches remain mutually exclusive."""
        with pytest.raises(ValidationError):
            validate_canonical(
                _review(
                    {
                        "referee_type": "ai",
                        "identity_mode": "open",
                        "ai_referee": {
                            "system": AI_SYSTEM,
                            "execution": AI_EXECUTION,
                            "reference": AI_REFERENCE,
                        },
                    }
                )
            )

    @pytest.mark.parametrize(
        "extra",
        [
            pytest.param({"system": AI_SYSTEM}, id="system"),
            pytest.param({"execution": AI_EXECUTION}, id="execution"),
            pytest.param({"inputs": {}}, id="inputs"),
            pytest.param({"outputs": {}}, id="outputs"),
            pytest.param({"safety": {}}, id="safety"),
        ],
    )
    def test_reference_with_provenance_key_rejected(self, extra):
        """The lightweight reference form cannot carry provenance keys.

        These combinations satisfy only the reference branch, so they slip past
        the mutual-exclusion check unless that branch admits no other key
        (`maxProperties: 1`). The parent block alone is not enough: it makes
        all six keys legal everywhere.
        """
        with pytest.raises(ValidationError):
            validate_canonical(
                _review(
                    {
                        "referee_type": "ai",
                        "identity_mode": "open",
                        "ai_referee": {"reference": AI_REFERENCE, **extra},
                    }
                )
            )

    def test_system_without_execution_rejected(self):
        """The provenance branch requires both system and execution."""
        with pytest.raises(ValidationError):
            validate_canonical(
                _review(
                    {
                        "referee_type": "ai",
                        "identity_mode": "open",
                        "ai_referee": {"system": AI_SYSTEM},
                    }
                )
            )

    def test_empty_ai_referee_rejected(self):
        """An empty ai_referee satisfies neither branch."""
        with pytest.raises(ValidationError):
            validate_canonical(
                _review({"referee_type": "ai", "identity_mode": "open", "ai_referee": {}})
            )

    def test_ai_type_requires_ai_referee(self):
        """referee_type 'ai' still requires the ai_referee block."""
        with pytest.raises(ValidationError):
            validate_canonical(_review({"referee_type": "ai", "identity_mode": "open"}))
