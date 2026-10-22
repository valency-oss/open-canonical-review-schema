# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""The 0.9 hierarchy and a private view for the existing source-format codecs.

Codecs retain their source-specific parsing and writing rules. Their intermediate 0.8
shape is translated at the registry boundary; public OCRS records always use 0.9.
Only legacy fields without a faithful new home are retained in extensions, never an
entire duplicate review. No new judgment or reasoning edge is inferred from a score.
"""

from __future__ import annotations

import copy
import json
from fractions import Fraction
from typing import Any

LEGACY_SCHEMA = (
    "https://valency-oss.github.io/open-canonical-review-schema/v0.8.0/canonical-review.schema.json"
)
KINDS = ("strengths", "weaknesses", "questions", "comments", "changes")
ID_PREFIX = {
    "strengths": "strength",
    "weaknesses": "weakness",
    "questions": "question",
    "comments": "comment",
    "changes": "change",
}


def upgrade_content(
    review: dict[str, Any],
    paths: dict[str, str] | None = None,
    *,
    unbounded_fallback: bool = False,
) -> dict:
    """Translate a codec's 0.8 content without changing the input. `paths` records moves
    for the AI mapping record. Published 0.8 migrations call this after the 0.7 steps.
    """
    out = copy.deepcopy(review)
    moves = paths if paths is not None else {}
    rest: dict[str, Any] = {}
    # Fields of an addressable record are kept under its ID, not its position, so they
    # stay with that record when findings are later added, removed or reordered.
    owned: list[tuple[str, str, str]] = []
    occupied: set[str] = set()
    entity_ids: set[str] = set()
    generated = []

    def collect(value):
        if isinstance(value, dict):
            if isinstance(value.get("id"), str):
                occupied.add(value["id"])
                entity_ids.add(value["id"])
            if isinstance(value.get("claim_id"), str):
                occupied.add(value["claim_id"])
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(out)

    def identify(item, prefix):
        if item.get("id"):
            return item["id"]
        n = 1
        while f"{prefix}-{n}" in occupied:
            n += 1
        item["id"] = f"{prefix}-{n}"
        occupied.add(item["id"])
        generated.append(item["id"])
        return item["id"]

    def keep(path, value):
        rest[path] = value
        moves[path] = f"extensions.ocrs_0_8.fields.{path}"

    def keep_on(owner, path, key, value):
        rest.setdefault(f"record:{owner}", {})[key] = value
        owned.append((f"{path}.{key}", f"record:{owner}", key))

    def move(old, new):
        moves[old] = new

    claim_id_map = {}
    for claim in out.get("claim_assessments", []):
        old_id = claim["claim_id"]
        # An empty ID names nothing, so several of them are not ambiguous links.
        if old_id and old_id in claim_id_map:
            raise ValueError("Duplicate legacy claim IDs cannot be linked unambiguously")
        if not old_id or old_id in entity_ids:
            id = identify({}, "claim")
            claim["claim_id"] = id
            keep(f"claim_original_id.{id}", old_id)
        else:
            id = old_id
        if old_id:
            claim_id_map[old_id] = id

    def point(item, path, category):
        owner = identify(item, ID_PREFIX[category])
        if not item.get("text", "").strip() and item.get("title", "").strip():
            keep_on(owner, path, "text", item.get("text", ""))
            item["text"] = item["title"]
        if "scope" in item:
            scope = item.pop("scope")
            tags = item.setdefault("tags", [])
            if scope not in tags:
                tags.append(scope)
            keep_on(owner, path, "scope", scope)
        u = {k: item.pop(k) for k in ("probability", "credence") if k in item}
        if u:
            if category in ("strengths", "weaknesses", "questions", "comments"):
                item["uncertainty"] = u
                for key in u:
                    move(path + "." + key, path + ".uncertainty." + key)
            else:
                keep_on(owner, path, "uncertainty", u)
        if "claim_ids" in item:
            claim_ids = item.pop("claim_ids")
            if category != "changes":
                item["about"] = [
                    *item.get("about", []),
                    *({"type": "claim", "id": claim_id_map.get(id, id)} for id in claim_ids),
                ]
                move(path + ".claim_ids", path + ".about")
            else:
                keep_on(owner, path, "claim_ids", claim_ids)
        allowed = {"id", "text", "title", "evidence_links", "tags", "group"}
        allowed |= (
            {"severity", "suggested_edits", "addresses"}
            if category == "changes"
            else {"about", "uncertainty"}
        )
        if category == "weaknesses":
            allowed.add("severity")
        for key in list(item):
            if key not in allowed:
                keep_on(owner, path, key, item.pop(key))

    findings = out.setdefault("findings", {})
    for category, items in list(findings.items()):
        for i, item in enumerate(items):
            point(item, f"findings.{category}[{i}]", category)
    opinion = out.setdefault("opinion", {})
    summary = out.setdefault("work_summary", {})
    contributions = opinion.pop("contributions", [])
    if contributions:
        summary["contributions"] = contributions
        move("opinion.contributions", "work_summary.contributions")
        for i, item in enumerate(contributions):
            path = f"work_summary.contributions[{i}]"
            owner = identify(item, "contribution")
            if not item.get("text", "").strip() and item.get("title", "").strip():
                keep_on(owner, path, "text", item.get("text", ""))
                item["text"] = item["title"]
            for key in list(item):
                if key not in {"id", "text", "title", "evidence_links"}:
                    keep_on(owner, path, key, item.pop(key))
    if "text" in opinion:
        text = opinion.pop("text")
        if "summary" in opinion:
            # The old text itself, not an offset, so an edited summary is never cut apart.
            keep("opinion.text", text)
            opinion["summary"] += "\n\n" + text
        else:
            opinion["summary"] = text
            keep("opinion.text_only", True)
        move("opinion.text", "opinion.summary")
    reason_ids = []
    for reason in opinion.pop("high_level_reasons", []):
        if not reason.strip():
            continue
        existing = next(
            (f for k in KINDS[:-1] for f in findings.get(k, []) if f["text"] == reason), None
        )
        if existing is None:
            existing = {"text": reason}
            identify(existing, "reason")
            findings.setdefault("comments", []).append(existing)
        if existing["id"] not in opinion.setdefault("supported_by", []):
            opinion["supported_by"].append(existing["id"])
        reason_ids.append(existing["id"])
    if reason_ids:
        keep("opinion.reason_ids", reason_ids)
    if decision := out.pop("decision", None):
        if "summary_rationale" in decision:
            decision["rationale"] = decision.pop("summary_rationale")
            move("decision.summary_rationale", "opinion.decision.rationale")
        if "credence" in decision:
            keep("decision.credence", decision.pop("credence"))
        opinion["decision"] = decision
        move("decision", "opinion.decision")

    # A claim is extracted once. Its assessment is an explicit source-stated finding.
    for i, claim in enumerate(out.pop("claim_assessments", [])):
        id = claim.pop("claim_id")
        item = {"id": id, "text": claim.pop("claim_text")}
        if not id:
            id = identify(item, "claim")
            keep(f"claim_original_id.{id}", "")
        if "evidence_links" in claim:
            item["evidence_links"] = claim.pop("evidence_links")
        summary.setdefault("claims", []).append(item)
        move(f"claim_assessments[{i}].claim_text", f"work_summary.claims[{i}].text")
        move(f"claim_assessments[{i}].evidence_links", f"work_summary.claims[{i}].evidence_links")
        status = claim.pop("status")
        notes = claim.pop("notes", None)
        if notes or status != "not_evaluated":
            f = {
                "text": notes or f"Claim assessment: {status}.",
                "about": [{"type": "claim", "id": id}],
            }
            identify(f, "claim-assessment")
            # Source categories carry through without manufacturing a rationale.
            category = (
                "weaknesses" if status in {"unsupported", "partially_supported"} else "comments"
            )
            findings.setdefault(category, []).append(f)
            keep(
                f"claim_status.{id}",
                {"status": status, "finding_id": f["id"], "had_notes": notes is not None},
            )
        else:
            keep(f"claim_status.{id}", {"status": status})
        # These probabilities concern claim truth, not the truth of its support verdict.
        # Claim-local ratings must not silently become work-wide summary metrics.
        if "probability" in claim:
            belief = {
                "text": item["text"],
                "about": [{"type": "claim", "id": id}],
                "uncertainty": {k: claim.pop(k) for k in ("probability", "credence") if k in claim},
            }
            identify(belief, "claim-belief")
            findings.setdefault("comments", []).append(belief)
            keep(f"claim_belief.{id}", belief["id"])
        if claim:
            keep(f"claim_fields.{id}", claim)

    for i, check in enumerate(out.get("checks", [])):
        owner = identify(check, "check")
        path = f"checks[{i}]"
        if "label" in check:
            keep_on(owner, path, "label", check.pop("label"))
        results = check.setdefault("results", [])
        for j, item in enumerate(check.pop("items", [])):
            result = {"status": item["status"], "evidence_links": [item["target"]]}
            identify(result, "result")
            if item.get("notes"):
                result["text"] = item["notes"]
            elif "notes" in item:
                keep_on(result["id"], f"{path}.items[{j}]", "notes", item["notes"])
            if "flagged" in item:
                result["data"] = {"flagged": item["flagged"]}
            results.append(result)
            move(f"{path}.items[{j}].status", f"{path}.results[{j}].status")
            move(f"{path}.items[{j}].notes", f"{path}.results[{j}].text")
            move(f"{path}.items[{j}].flagged", f"{path}.results[{j}].data.flagged")
            move(f"{path}.items[{j}].target", f"{path}.results[{j}].evidence_links[0]")
        if "measurements" in check:
            result = {"data": {"measurements": check.pop("measurements")}}
            identify(result, "result")
            move(path + ".measurements", f"{path}.results[{len(results)}].data.measurements")
            results.append(result)
        for finding_id in check.pop("finding_ids", []):
            for category in KINDS[:-1]:
                for f in findings.get(category, []):
                    if f["id"] == finding_id:
                        f.setdefault("about", []).append({"type": "check", "id": check["id"]})
        if not results:
            check.pop("results")

    assessments = out.pop("artifact_assessments", [])
    if "checks" not in out and any(a.get("checks") for a in assessments):
        keep("checks_absent", True)
    for i, assessment in enumerate(assessments):
        artifact = {
            "type": {"models": "model", "appendix": "supplement"}.get(
                assessment["artifact_type"], assessment["artifact_type"]
            ),
            "reported_availability": assessment["availability"],
        }
        identify(artifact, "artifact")
        if assessment.get("ref"):
            artifact["ref"] = assessment["ref"]
        out["target"].setdefault("artifacts", []).append(artifact)
        evidence = [
            {"resource": {"type": "artifact", "id": artifact["id"]}},
            *assessment.get("evidence_links", []),
        ]
        info = {"artifact_id": artifact["id"], "assessment": assessment["assessment"]}
        if assessment["assessment"] != "not_evaluated" or assessment.get("reproducibility_notes"):
            f = {
                "text": assessment.get("reproducibility_notes")
                or f"Artifact assessment: {assessment['assessment']}.",
                "evidence_links": evidence,
                "tags": ["artifact"],
            }
            identify(f, "artifact-assessment")
            findings.setdefault("comments", []).append(f)
            info["finding_id"] = f["id"]
            info["had_notes"] = "reproducibility_notes" in assessment
        if assessment.get("checks"):
            ids = []
            for j, c in enumerate(assessment["checks"]):
                r = {
                    "status": c["status"],
                    "evidence_links": [{"resource": {"type": "artifact", "id": artifact["id"]}}],
                }
                identify(r, "result")
                if c.get("notes"):
                    r["text"] = c["notes"]
                elif "notes" in c:
                    keep_on(r["id"], f"artifact_assessments[{i}].checks[{j}]", "notes", c["notes"])
                ck = {"kind": "artifact:" + c["key"], "results": [r]}
                identify(ck, "check")
                out.setdefault("checks", []).append(ck)
                ids.append(ck["id"])
            info["check_ids"] = ids
        keep(f"artifact_assessments[{i}]", info)

    if ethics := out.pop("ethics_and_risk", None):
        f = {
            "text": (ethics.get("notes") if ethics.get("notes", "").strip() else None)
            or (
                "Ethical concerns reported."
                if ethics.get("ethical_concerns") is True
                else "No ethical concerns reported."
                if ethics.get("ethical_concerns") is False
                else "Ethical concern categories: "
                + ", ".join(ethics.get("concern_categories", []))
                + "."
            ),
            "tags": ["ethics", *ethics.get("concern_categories", [])],
        }
        identify(f, "ethics")
        findings.setdefault(
            "weaknesses" if ethics.get("ethical_concerns") else "comments", []
        ).append(f)
        keep(
            "ethics_and_risk",
            {k: v for k, v in ethics.items() if k != "notes"}
            | {"finding_id": f["id"], "had_notes": "notes" in ethics},
        )
        if "notes" in ethics and not ethics["notes"].strip():
            keep("ethics_blank_notes", ethics["notes"])

    forms = out.setdefault("review_context", {}).setdefault("metric_schemas", {})
    definitions: dict[str, Any] = {}
    catalog = out.pop("metric_catalog_ref", None)
    source = {"name": out.get("provenance", {}).get("source_system", "local")}
    if catalog:
        source["catalog_ref"] = catalog
    if out.get("target", {}).get("venue"):
        source["venue"] = out["target"]["venue"]
    schema_id = "source-form"
    while schema_id in forms:
        schema_id += "-1"
    for i, m in enumerate(out.get("metrics", [])):
        if "definition_ref" in m:
            continue
        identify(m, "metric")
        if "uncertainty" in m:
            u = m["uncertainty"]
            if "interval" in u and set(u["interval"]) != {"low", "high"}:
                keep(f"metric_interval.{m['id']}", u.pop("interval"))
            if not u:
                keep(f"metric_uncertainty.{m['id']}", m.pop("uncertainty"))
        definition = {"label": m.pop("label"), "scale": m.pop("scale"), "catalog_key": m.pop("key")}
        # A value outside a codec's presumed default means its real form is unknown.
        # This fallback must not be presented as an asserted original rubric.
        value, scale = m["value"], definition["scale"]
        if unbounded_fallback and type(value) in (int, float):
            conflict = ("min" in scale and value < scale["min"]) or (
                "max" in scale and value > scale["max"]
            )
            if "step" in scale and "min" in scale:
                delta = Fraction(str(value)) - Fraction(str(scale["min"]))
                conflict |= (delta / Fraction(str(scale["step"]))).denominator != 1
            if conflict:
                keep(f"metric_assumed_scale.{m['id']}", scale)
                definition["scale"] = {"type": scale["type"]}
                if "normalized" in m:
                    keep(f"metric_assumed_normalized.{m['id']}", m.pop("normalized"))
        if "normalized" in m and "method" not in m["normalized"]:
            # 0.9 requires the method; 0.8 allowed a bare value. Say it is unstated.
            m["normalized"]["method"] = "unspecified"
            keep(f"metric_unstated_method.{m['id']}", True)
        if "aspect" in m:
            definition["dimension"] = m.pop("aspect")
        key = next((k for k, v in definitions.items() if v == definition), None)
        if key is None:
            key = definition["catalog_key"] or "metric"
            while key in definitions:
                key += "_1"
            definitions[key] = definition
        if not definition.get("catalog_key"):
            keep(f"metric_key.{m['id']}", definition.pop("catalog_key", ""))
        m["definition_ref"] = {"schema_id": schema_id, "key": key}
        for k in ["label", "scale", "aspect", "key"]:
            move(
                f"metrics[{i}].{k}",
                f"review_context.metric_schemas.{schema_id}.definitions.{key}."
                + {"key": "catalog_key", "aspect": "dimension"}.get(k, k),
            )
        if "evidence_links" in m:
            keep(f"metric_evidence.{m['id']}", m.pop("evidence_links"))
    if definitions:
        forms[schema_id] = {"source": source, "definitions": definitions}
    elif catalog:
        keep("metric_catalog_ref", catalog)
    if not forms:
        out["review_context"].pop("metric_schemas")
    if not out["review_context"]:
        out.pop("review_context")
    if not summary:
        out.pop("work_summary")
    if not findings:
        out.pop("findings")
    # Only overall scores stand for the opinion; confidence or a single aspect does not.
    overall = []
    for m in out.get("metrics", []):
        try:
            definition = resolve_definition(out, m)
        except KeyError:
            continue
        if "overall" in (definition.get("dimension"), definition.get("catalog_key")):
            overall.append(m["id"])
    if overall:
        opinion.setdefault("metric_refs", overall)

    def evidence(value, path=""):
        if isinstance(value, dict):
            for key, child in list(value.items()):
                child_path = f"{path}.{key}" if path else key
                if key == "evidence_links":
                    value[key] = [upgrade_evidence(e) for e in child]
                    for i, e in enumerate(child):
                        p = f"{child_path}[{i}]"
                        if "ref" in e:
                            move(p + ".ref", p + ".location.label")
                        if "type" in e:
                            move(p + ".type", p + ".resource.type")
                        if "work" in e:
                            move(p + ".work", p + ".resource.work")
                        if "version" in e.get("location", {}):
                            move(p + ".location.version", p + ".version")
                elif key not in {"extensions", "raw_payload", "data", "snapshot"}:
                    evidence(child, child_path)
        elif isinstance(value, list):
            for i, child in enumerate(value):
                evidence(child, f"{path}[{i}]")

    evidence(out)
    if rest:
        fields = (
            out.setdefault("extensions", {}).setdefault("ocrs_0_8", {}).setdefault("fields", [])
        )
        index = {}
        for path, value in rest.items():
            index[path] = len(fields)
            moves[path] = f"extensions.ocrs_0_8.fields[{len(fields)}].value"
            fields.append({"path": path, "value": value})
        for source, path, key in owned:
            moves[source] = f"extensions.ocrs_0_8.fields[{index[path]}].value.{key}"
    if generated:
        out.setdefault("extensions", {}).setdefault("ocrs_0_8", {})["generated_ids"] = generated
    return out


def remap_path(path: str, moves: dict[str, str]) -> str:
    """Follow structural moves and then leaf moves in a mapping-record field path."""
    visited = set()
    while path not in visited:
        visited.add(path)
        changed = False
        for old in sorted(moves, key=len, reverse=True):
            if path == old or path.startswith(old + ".") or path.startswith(old + "["):
                updated = moves[old] + path[len(old) :]
                changed = updated != path
                path = updated
                break
        if not changed:
            return path
    raise ValueError("Cyclic migration path mapping")


def upgrade_evidence(link: dict) -> dict:
    if "resource" in link:
        return copy.deepcopy(link)
    resource = {"type": "work"}
    if link.get("type") == "external" or (link.get("work") and link.get("type") != "bibliography"):
        resource = {"type": "external", "ref": link["ref"]}
        if link.get("work"):
            resource["work"] = copy.deepcopy(link["work"])
    elif link.get("work"):
        resource["work"] = copy.deepcopy(link["work"])
    out = {"resource": resource}
    loc = copy.deepcopy(link.get("location", {}))
    if "ref" in link:
        loc["label"] = link["ref"]
    key = {
        "figure": "figure",
        "table": "table",
        "equation": "equation",
    }.get(link.get("type"))
    if key and link.get("ref"):
        loc.setdefault(key, link["ref"])
    if "version" in loc:
        out["version"] = loc.pop("version")
    if link.get("quote"):
        out["quote"] = link["quote"]
    # Keep the original pointer kind where it carries information beyond location fields.
    if link.get("type") not in {"paper_section", "figure", "table", "equation", "external"}:
        resource["ref"] = link["type"] + ":" + link["ref"]
    if loc:
        out["location"] = loc
    return out


def resolve_definition(review: dict, metric: dict) -> dict:
    """Return the exact metric definition; callers validate missing references first."""
    r = metric["definition_ref"]
    return review["review_context"]["metric_schemas"][r["schema_id"]]["definitions"][r["key"]]


def legacy_evidence(link: dict, artifacts: dict[str, dict] | None = None) -> dict:
    """A source pointer in the private source-codec representation."""
    if "resource" not in link:
        return copy.deepcopy(link)
    resource = link["resource"]
    location = copy.deepcopy(link.get("location", {}))
    kind = next((k for k in ("figure", "table", "equation") if k in location), "paper_section")
    label = location.pop("label", None)
    ref = (
        label
        if label is not None
        else (
            location.get(kind)
            or location.get("section")
            or resource.get("ref")
            or resource.get("id", "source")
        )
    )
    if resource.get("ref", "").split(":", 1)[0] in {
        "appendix",
        "supplement",
        "code",
        "data",
        "bibliography",
    }:
        kind, ref = resource["ref"].split(":", 1)
    elif resource["type"] == "external":
        kind = "external"
    elif resource["type"] == "artifact":
        artifact = (artifacts or {}).get(resource["id"], {})
        kind = (
            "code"
            if artifact.get("type") == "code"
            else "data"
            if artifact.get("type") == "data"
            else "supplement"
        )
        ref = label or artifact.get("ref") or ref
    out = {"type": kind, "ref": ref}
    if resource.get("work"):
        out["work"] = copy.deepcopy(resource["work"])
    if link.get("version"):
        location["version"] = link["version"]
    if link.get("quote"):
        out["quote"] = link["quote"]
        if "prefix" in location or "suffix" in location:
            location["text_anchor"] = {
                "exact": link["quote"],
                **{k: location.pop(k) for k in ("prefix", "suffix") if k in location},
            }
    location = {
        k: v
        for k, v in location.items()
        if k in {"section", "page", "page_end", "version", "text_anchor"}
    }
    if location:
        out["location"] = location
    return out


def legacy_view(review: dict[str, Any]) -> dict:
    """Read-only projection for source-format writers, not an alternative public schema.
    A source format may not express every 0.9 link. It must not invent judgments to do so.
    Any valid 0.9 record projects, including one edited after migration: retained fields
    whose records were since removed are dropped, never looked up.
    """
    out = copy.deepcopy(review)
    kept = out.get("extensions", {}).pop("ocrs_0_8", {})
    rest = {f["path"]: f["value"] for f in kept.get("fields", [])}
    generated = set(kept.get("generated_ids", []))
    artifacts = {a["id"]: a for a in out.get("target", {}).get("artifacts", [])}
    findings = out.get("findings", {})
    all_findings = {f["id"]: f for k in KINDS for f in findings.get(k, [])}
    opinion = out.setdefault("opinion", {})
    if "opinion.text" in rest:
        text = rest["opinion.text"]
        # After an edit that removed the appended text, the summary stays whole.
        if opinion.get("summary", "").endswith("\n\n" + text):
            opinion["summary"] = opinion["summary"][: -len(text) - 2]
            opinion["text"] = text
    elif rest.get("opinion.text_only") and "summary" in opinion:
        opinion["text"] = opinion.pop("summary")
    if "decision" in opinion:
        decision = opinion.pop("decision")
        if "rationale" in decision:
            decision["summary_rationale"] = decision.pop("rationale")
        if "decision.credence" in rest:
            decision["credence"] = rest["decision.credence"]
        out["decision"] = decision
    opinion.pop("metric_refs", None)
    opinion.pop("supported_by", None)
    descriptive = out.pop("work_summary", {})
    if descriptive.get("summary") and not opinion.get("summary"):
        # Source codecs have one overall prose slot; descriptive text remains verbatim.
        opinion["summary"] = descriptive["summary"]
    if descriptive.get("contributions"):
        opinion["contributions"] = descriptive["contributions"]
        for item in opinion["contributions"]:
            item.update(rest.get(f"record:{item['id']}", {}))
    remove_findings = set()
    if reason_ids := rest.get("opinion.reason_ids"):
        reason_ids = [id for id in reason_ids if id in all_findings]
        opinion["high_level_reasons"] = [all_findings[id]["text"] for id in reason_ids]
        remove_findings.update(id for id in reason_ids if id in generated)
    for claim in descriptive.get("claims", []):
        id = claim["id"]
        info = rest.get(f"claim_status.{id}", {"status": "not_evaluated"})
        assessment = all_findings.get(info.get("finding_id"))
        legacy = {
            "claim_id": rest.get(f"claim_original_id.{id}", id),
            "claim_text": claim["text"],
            "status": info["status"] if assessment else "not_evaluated",
        }
        if claim.get("evidence_links"):
            legacy["evidence_links"] = claim["evidence_links"]
        if assessment:
            f = assessment
            if info.get("had_notes"):
                legacy["notes"] = f.get("text", "")
            remove_findings.add(info["finding_id"])
        legacy.update(rest.get(f"claim_fields.{id}", {}))
        if (belief_id := rest.get(f"claim_belief.{id}")) in all_findings:
            legacy.update(all_findings[belief_id].get("uncertainty", {}))
            remove_findings.add(belief_id)
        out.setdefault("claim_assessments", []).append(legacy)
    checks = {c["id"]: c for c in out.get("checks", [])}
    remove_checks = set()
    for path, info in rest.items():
        if not path.startswith("artifact_assessments["):
            continue
        artifact = artifacts.get(info["artifact_id"])
        if artifact is None:
            continue
        a = {
            "artifact_type": {"model": "models", "supplement": "appendix"}.get(
                artifact["type"], artifact["type"]
            ),
            "availability": artifact.get("reported_availability", "unknown"),
            "assessment": (
                info["assessment"] if info.get("finding_id") in all_findings else "not_evaluated"
            ),
        }
        if artifact.get("ref"):
            a["ref"] = artifact["ref"]
        if info.get("finding_id") in all_findings:
            f = all_findings[info["finding_id"]]
            if info.get("had_notes"):
                a["reproducibility_notes"] = f.get("text", "")
            evidence = f.get("evidence_links", [])[1:]
            if evidence:
                a["evidence_links"] = evidence
            remove_findings.add(info["finding_id"])
        for id in info.get("check_ids", []):
            if not checks.get(id, {}).get("results"):
                continue
            c = checks[id]
            r = c["results"][0]
            # An edited raw observation need not have an evaluative status. Keep it
            # as an ordinary check rather than restoring the old pass/fail verdict.
            if "status" not in r or "data" in r or len(c["results"]) != 1:
                continue
            item = {"key": c["kind"].removeprefix("artifact:"), "status": r["status"]}
            if r.get("text"):
                item["notes"] = r["text"]
            elif "notes" in rest.get(f"record:{r['id']}", {}):
                item["notes"] = rest[f"record:{r['id']}"]["notes"]
            a.setdefault("checks", []).append(item)
            remove_checks.add(id)
        out.setdefault("artifact_assessments", []).append(a)
    info = rest.get("ethics_and_risk")
    if info and info["finding_id"] in all_findings:
        f = all_findings[info["finding_id"]]
        ethics = {k: v for k, v in info.items() if k not in {"finding_id", "had_notes"}}
        if info.get("had_notes"):
            ethics["notes"] = rest.get("ethics_blank_notes", f.get("text", ""))
        out["ethics_and_risk"] = ethics
        remove_findings.add(info["finding_id"])
    # A consumed legacy assessment/reason may now be the target of a requested
    # change. Keep the actual finding as well so the surviving link still resolves.
    protected = set()
    for id, finding in all_findings.items():
        for field in ("addresses", "summarizes"):
            protected.update(finding.get(field, []))
            protected.update(rest.get(f"record:{id}", {}).get(field, []))
    remove_findings.difference_update(protected)
    for category in list(findings):
        kept = [f for f in findings[category] if f["id"] not in remove_findings]
        if findings[category] and not kept:
            # Only findings that migration made were here, so 0.8 listed none.
            del findings[category]
            continue
        findings[category] = kept
        for f in findings[category]:
            if "uncertainty" in f:
                f.update(f.pop("uncertainty"))
            for r in f.pop("about", []):
                if r["type"] == "claim":
                    f.setdefault("claim_ids", []).append(
                        rest.get(f"claim_original_id.{r['id']}", r["id"])
                    )
                if r["type"] in {"check", "check_result"}:
                    for c in checks.values():
                        if c["id"] == r["id"] or any(
                            x["id"] == r["id"] for x in c.get("results", [])
                        ):
                            c.setdefault("finding_ids", []).append(f["id"])
            for key, value in rest.get(f"record:{f['id']}", {}).items():
                if key == "uncertainty":
                    f.update(value)
                else:
                    f[key] = value
    for c in out.get("checks", []):
        c.update(rest.get(f"record:{c['id']}", {}))
        observations = []
        for r in c.pop("results", []):
            data = r.get("data")
            if (
                isinstance(data, dict)
                and set(data) == {"measurements"}
                and isinstance(data["measurements"], list)
                and all(
                    isinstance(m, dict) and {"key", "value"} <= m.keys()
                    for m in data["measurements"]
                )
            ):
                c.setdefault("measurements", []).extend(data["measurements"])
            elif r.get("status"):
                item = {
                    "status": r["status"],
                    "target": (r.get("evidence_links") or [{"resource": {"type": "work"}}])[0],
                }
                if "text" in r:
                    item["notes"] = r["text"]
                elif "notes" in rest.get(f"record:{r['id']}", {}):
                    item["notes"] = rest[f"record:{r['id']}"]["notes"]
                if "data" in r and not (isinstance(data, dict) and set(data) == {"flagged"}):
                    item["notes"] = "\n\n".join(
                        text
                        for text in (
                            item.get("notes"),
                            "Data: " + json.dumps(data, ensure_ascii=False),
                        )
                        if text
                    )
                if isinstance(data, dict) and "flagged" in data:
                    item["flagged"] = data["flagged"]
                c.setdefault("items", []).append(item)
            else:
                if r.get("text"):
                    observations.append(r["text"])
                if "data" in r:
                    observations.append("Data: " + json.dumps(data, ensure_ascii=False))
        if c.get("execution_status"):
            observations.append("Execution status: " + c["execution_status"])
        if observations:
            c["summary"] = "\n\n".join(
                [*([c["summary"]] if c.get("summary") else []), *observations]
            )
        c.pop("procedure", None)
        c.pop("execution_status", None)
        c.pop("run_ref", None)
        c.pop("results_coverage", None)
    if "checks" in out:
        out["checks"] = [c for c in out["checks"] if c["id"] not in remove_checks]
        for c in out["checks"]:
            if c["kind"] not in {
                "ai_text_detection",
                "reference_verification",
                "fatal_flaw_screen",
                "similarity",
                "image_integrity",
                "statistics",
                "retraction",
                "other",
            }:
                c["label"] = " — ".join(x for x in (c.get("label"), c["kind"]) if x)
                c["kind"] = "other"
        if not out["checks"] and rest.get("checks_absent"):
            out.pop("checks")
    for metric in out.get("metrics", []):
        if "definition_ref" not in metric:
            continue
        definition = resolve_definition(review, metric)
        r = metric.pop("definition_ref")
        metric.update(
            {
                "key": definition.get("catalog_key", r["key"]),
                "label": definition["label"],
                "scale": copy.deepcopy(definition["scale"]),
            }
        )
        if f"metric_key.{metric['id']}" in rest:
            metric["key"] = rest[f"metric_key.{metric['id']}"]
        if f"metric_assumed_scale.{metric['id']}" in rest:
            metric["scale"] = rest[f"metric_assumed_scale.{metric['id']}"]
        if f"metric_assumed_normalized.{metric['id']}" in rest:
            metric["normalized"] = rest[f"metric_assumed_normalized.{metric['id']}"]
        if (
            rest.get(f"metric_unstated_method.{metric['id']}")
            and metric.get("normalized", {}).get("method") == "unspecified"
        ):
            metric["normalized"].pop("method", None)
        if f"metric_uncertainty.{metric['id']}" in rest and "uncertainty" not in metric:
            metric["uncertainty"] = rest[f"metric_uncertainty.{metric['id']}"]
        if f"metric_interval.{metric['id']}" in rest and "interval" not in metric.get(
            "uncertainty", {}
        ):
            metric.setdefault("uncertainty", {})["interval"] = rest[
                f"metric_interval.{metric['id']}"
            ]
        if definition.get("dimension"):
            metric["aspect"] = definition["dimension"]
        if f"metric_evidence.{metric['id']}" in rest:
            metric["evidence_links"] = rest[f"metric_evidence.{metric['id']}"]
        metric.pop("supported_by", None)
        metric.pop("source_value", None)
        metric.pop("id", None)
    forms = out.get("review_context", {}).pop("metric_schemas", {})
    for form in forms.values():
        if form.get("source", {}).get("catalog_ref"):
            out["metric_catalog_ref"] = form["source"]["catalog_ref"]
            break
    if "metric_catalog_ref" in rest:
        out["metric_catalog_ref"] = rest["metric_catalog_ref"]
    out.get("target", {}).pop("artifacts", None)

    def evidence(value):
        if isinstance(value, dict):
            for key, child in list(value.items()):
                if key == "evidence_links":
                    value[key] = [legacy_evidence(e, artifacts) for e in child]
                elif key == "target" and isinstance(child, dict) and "resource" in child:
                    value[key] = legacy_evidence(child, artifacts)
                elif key not in {"extensions", "raw_payload", "data", "snapshot"}:
                    evidence(child)
        elif isinstance(value, list):
            for child in value:
                evidence(child)

    evidence(out)

    referenced = set()
    for items in [*findings.values(), opinion.get("contributions", []), out.get("checks", [])]:
        for item in items:
            for field in ("addresses", "summarizes", "finding_ids"):
                referenced.update(item.get(field, []))

    def strip_ids(value):
        if isinstance(value, dict):
            if value.get("id") in generated and value["id"] not in referenced:
                value.pop("id")
            for key, child in value.items():
                if key not in {"extensions", "raw_payload", "snapshot", "data"}:
                    strip_ids(child)
        elif isinstance(value, list):
            for child in value:
                strip_ids(child)

    strip_ids(out)
    for name in ["findings", "review_context", "extensions"]:
        if not out.get(name):
            out.pop(name, None)
    if "$schema" in out:
        out["$schema"] = LEGACY_SCHEMA
    return out
