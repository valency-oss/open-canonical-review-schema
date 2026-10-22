# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Reviews written for an earlier OCRS version, in the current one."""

from __future__ import annotations

import copy
from typing import Any

from .hierarchy import upgrade_content
from .schema import is_hierarchical, schema_id

# The named text fields of 0.7's `narrative`, as the parts of 0.8's: (field, role, audience)
NARRATIVE_FIELDS = (
    ("summary", "summary", None),
    ("detailed_review", "review", None),
    ("author_questions", "questions", None),
    ("confidential_to_editors", "review", "editors"),
)
# Where 0.7's `applies_to` places go among a point's evidence links
APPLIES_TO_LINKS = {"section": "paper_section", "figure": "figure", "table": "table"}
# The metric catalog 0.7 reviews name, and the one that adds `expertise` to it
CATALOG_V1, CATALOG_V1_1 = "metric-catalog.core.v1", "metric-catalog.core.v1.1"


def migrate(review: dict[str, Any]) -> dict[str, Any]:
    """Convert a 0.7 or 0.8 review to the current hierarchy without changing the input.

    Normalize referees, expertise and narrative parts, then move decisions, metric
    definitions, extracted material, checks and evidence into the 0.9 records. Source
    fields without a faithful canonical home remain in extensions.ocrs_0_8. A review
    already naming 0.9 is returned unchanged; migration is idempotent. It does not
    infer supporting findings or rewrite ambiguous overview text.
    """
    if is_hierarchical(review.get("$schema", "")):
        return copy.deepcopy(review)
    out = copy.deepcopy(review)
    _referees(out)
    decision = out.get("decision")
    if isinstance(decision, dict) and "confidence" in decision:
        decision.setdefault("credence", decision.pop("confidence"))
        decision.pop("confidence", None)
    _points(out)
    _metrics(out)
    _license(out)
    narrative = out.get("narrative")
    if isinstance(narrative, dict):
        parts = [
            {"role": role, "content": narrative[field]}
            | ({"audience": audience} if audience else {})
            for field, role, audience in NARRATIVE_FIELDS
            if isinstance(narrative.get(field), str)
        ]
        # A section with an empty title has no heading
        parts += [
            {k: v for k, v in s.items() if not (k == "title" and v == "")}
            for s in narrative.get("sections") or []
            if isinstance(s, dict)
        ]
        if parts:
            out["narrative"] = parts
        else:
            out.pop("narrative")
    out = upgrade_content(out)
    out["$schema"] = schema_id()
    return out


def _referees(review: dict[str, Any]) -> None:
    referees = review.get("referees")
    referees = list(referees) if isinstance(referees, list) else []
    referee = review.pop("referee", None)
    if isinstance(referee, dict) and referee not in referees:
        referees.insert(0, referee)
    context = review.get("review_context")
    shared = context.pop("expertise", None) if isinstance(context, dict) else None
    if isinstance(context, dict) and not context:
        review.pop("review_context")
    for ref in referees:
        if not isinstance(ref, dict):
            continue
        human = ref.get("human_referee")
        own = human.pop("expertise", None) if isinstance(human, dict) else None
        expertise = own or shared
        if expertise and "expertise" not in ref:
            ref["expertise"] = expertise
    if referees:
        review["referees"] = referees


def _points(review: dict[str, Any]) -> None:
    findings = review.get("findings")
    findings = findings if isinstance(findings, dict) else {}
    for change in findings.get("changes") or []:
        _as_point(change)
    ethics = review.get("ethics_and_risk")
    mitigations = ethics.pop("required_mitigations", None) if isinstance(ethics, dict) else None
    if isinstance(ethics, dict) and not ethics:
        review.pop("ethics_and_risk")
    if mitigations:
        changes = review.setdefault("findings", {}).setdefault("changes", [])
        for mitigation in mitigations:
            if isinstance(mitigation, dict):
                _as_point(mitigation)
                # Still a change that ethics calls for, whatever its scope
                if mitigation.setdefault("scope", "ethics") != "ethics":
                    tags = mitigation.get("tags")
                    tags = tags if isinstance(tags, list) else []
                    mitigation["tags"] = tags if "ethics" in tags else [*tags, "ethics"]
                changes.append(mitigation)
    opinion = review.get("opinion")
    opinion = opinion if isinstance(opinion, dict) else {}
    for contribution in opinion.get("contributions") or []:
        if isinstance(contribution, dict) and "claim_id" in contribution:
            contribution["claim_ids"] = [contribution.pop("claim_id")]


def _metrics(review: dict[str, Any]) -> None:
    for metric in review.get("metrics") or []:
        if not isinstance(metric, dict) or metric.get("key") != "confidence":
            continue
        label = metric.get("label")
        if isinstance(label, str) and label.strip().casefold() == "reviewer expertise":
            metric["key"] = "expertise"
            if metric.get("aspect") == "confidence":
                metric["aspect"] = "expertise"
    if review.get("metric_catalog_ref") == CATALOG_V1:
        review["metric_catalog_ref"] = CATALOG_V1_1


def _license(review: dict[str, Any]) -> None:
    provenance = review.get("provenance")
    if not isinstance(provenance, dict) or "license" in provenance:
        return
    jats = (review.get("extensions") or {}).get("jats")
    permissions = jats.get("permissions") if isinstance(jats, dict) else None
    licenses = permissions.get("licenses") if isinstance(permissions, dict) else None
    first = licenses[0] if isinstance(licenses, list) and licenses else None
    first = first if isinstance(first, dict) else {}
    # The first license's URL, else its statement, as the JATS reader takes it
    if isinstance(first.get("url"), str) and first["url"]:
        provenance["license"] = {"url": first["url"]}
    elif isinstance(first.get("text"), str) and first["text"]:
        provenance["license"] = {"name": first["text"]}


def _as_point(item: Any) -> None:
    """An action item as a point."""
    if not isinstance(item, dict):
        return
    if "priority" in item:
        item.setdefault("severity", item.pop("priority"))
        item.pop("priority", None)
    applies_to = item.pop("applies_to", None)
    if not isinstance(applies_to, dict):
        return
    links = [
        {"type": link_type, "ref": applies_to[field]}
        for field, link_type in APPLIES_TO_LINKS.items()
        if isinstance(applies_to.get(field), str)
    ]
    if links:
        item["evidence_links"] = [*item.get("evidence_links", []), *links]
    if isinstance(applies_to.get("claim_id"), str):
        item["claim_ids"] = [applies_to["claim_id"]]
    if isinstance(applies_to.get("finding_id"), str):
        item["addresses"] = [applies_to["finding_id"]]
