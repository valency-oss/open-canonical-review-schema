# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""All assessments can identify passages with the same evidence location."""

import jsonschema
import pytest

from ocrs import validate_canonical

MINIMAL_REVIEW = {
    "review_id": "review-1",
    "version": "1.0.0",
    "created_at": "2026-10-12T12:00:00Z",
    "provenance": {"source_system": "example-journal"},
    "referees": [{"referee_type": "human", "identity_mode": "double_blind"}],
    "target": {"work_id": "internal_id:manuscript_id:paper-1", "work_type": "article"},
    "opinion": {"summary": "A sound paper."},
}


LINK = {
    "type": "paper_section",
    "ref": "Section 3.2, p.5",
    "location": {
        "section": "3.2 Methods",
        "page": 5,
        "version": "v2",
        "text_anchor": {
            "exact": "We release the training code.",
            "prefix": "Implementation details. ",
            "suffix": " See Appendix A.",
        },
    },
}


def review_with_links(link):
    return {
        **MINIMAL_REVIEW,
        "findings": {"weaknesses": [{"text": "Code is incomplete.", "evidence_links": [link]}]},
        "claim_assessments": [
            {
                "claim_id": "c1",
                "claim_text": "Code is public.",
                "status": "partially_supported",
                "evidence_links": [link],
            }
        ],
        "artifact_assessments": [
            {
                "artifact_type": "code",
                "availability": "public",
                "assessment": "adequate",
                "evidence_links": [link],
            }
        ],
        "metrics": [
            {
                "key": "reproducibility",
                "label": "Reproducibility",
                "scale": {"type": "ordinal", "min": 1, "max": 5},
                "value": 3,
                "evidence_links": [link],
            }
        ],
    }


def test_shared_locations_validate_across_assessments():
    validate_canonical(review_with_links(LINK))


def test_legacy_links_still_validate():
    validate_canonical(
        review_with_links(
            {"type": "paper_section", "ref": "Section 3.2", "quote": "Code is public."}
        )
    )


@pytest.mark.parametrize(
    "location", [{"section": "3.2"}, {"page": 1}, {"text_anchor": {"exact": "A sentence."}}]
)
def test_partial_locations_validate(location):
    validate_canonical(review_with_links({**LINK, "location": location}))


@pytest.mark.parametrize(
    "location",
    [
        {},
        {"page": 0},
        {"page": 1.5},
        {"page": "5"},
        {"section": ""},
        {"version": ""},
        {"text_anchor": {"prefix": "Before"}},
        {"text_anchor": {"exact": ""}},
        {"unknown": "value"},
    ],
)
def test_malformed_locations_are_rejected(location):
    with pytest.raises(jsonschema.ValidationError):
        validate_canonical(review_with_links({**LINK, "location": location}))
