#!/usr/bin/env python3
"""Build the GitHub Pages site: schema docs, plus every released schema version.

Each release's schema files are kept in `versions/v<version>/` and published at
`<site>/v<version>/<file>`, the URL in that schema's `$id`.
"""

import shutil
from pathlib import Path

from json_schema_for_humans.generate import generate_from_filename
from json_schema_for_humans.generation_configuration import GenerationConfiguration

from ocrs.registry import supported_sources, supported_targets


def stroke_icon(paths: str) -> str:
    return (
        '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" '
        f'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{paths}</svg>'
    )


def badge(text: str, background: str, color: str = "#fff", underline: str = "") -> str:
    """A square of a site's own colors, for a system with no logo that works at icon size."""
    style = f"background: {background}; color: {color}"
    if underline:
        style += f"; box-shadow: inset 0 -3px 0 {underline}"
    return f'<span class="site-badge" style="{style}">{text}</span>'


# The review sources drawn mapping into OCRS, in order: registry key, name, type, icon. A source
# with an exporter in the registry also gets an arrow back. The diagram shows a system's logo
# only when its owner has said it may be used; none has, so each system's icon is its initials
# in a color from its site's stylesheet (DeepReview's from the Google Research page announcing it).
SOURCES = [
    ("openreview", "OpenReview", "conference", badge("OR", "#8c1b13")),
    ("cmt", "CMT", "conference", badge("CMT", "#007ea3")),
    ("hotcrp", "HotCRP", "conference", badge("H", "#ffbbbb", "#f33360", "#f33360")),
    ("openaireview", "OpenAI<wbr>Review", "ai", badge("OAR", "#800000")),
    ("reviewer3", "Reviewer3", "ai", badge("R3", "#171717")),
    ("deepreview", "DeepReview", "ai", badge("DR", "#1a73e8")),
    ("editorialmanager", "Editorial Manager", "journal", badge("EM", "#003462")),
    ("scholarone", "ScholarOne", "journal", badge("S1", "#007262")),
    (
        "jats",
        "JATS",
        "journal",
        stroke_icon(
            '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/>'
            '<path d="M10.5 11.5 8.5 14l2 2.5M13.5 11.5l2 2.5-2 2.5"/>'
        ),
    ),
    (
        "journal_narrative",
        "Journal narrative",
        "journal",
        stroke_icon('<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/><path d="M9 12h6M9 16h6"/>'),
    ),
]
# The review types labelling the sources above them, in the same order as the sources:
# key, name, referee type, color, icon.
GROUPS = [
    (
        "conference",
        "Conference",
        "referee: human",
        "#e11d48",
        stroke_icon(
            '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/>'
            '<path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M18 14.2a6.5 6.5 0 0 1 3.5 5.8"/>'
        ),
    ),
    (
        "ai",
        "AI reviewers",
        "referee: ai",
        "#7c3aed",
        stroke_icon(
            '<path d="M10 3.5l1.8 4.7 4.7 1.8-4.7 1.8L10 16.5l-1.8-4.7L3.5 10l4.7-1.8z"/>'
            '<path d="M18 14l.9 2.1 2.1.9-2.1.9L18 20l-.9-2.1-2.1-.9 2.1-.9z"/>'
        ),
    ),
    (
        "journal",
        "Journal",
        "referee: human",
        "#2563eb",
        stroke_icon(
            '<path d="M2.5 4.5h6a3.5 3.5 0 0 1 3.5 3.5v12a3 3 0 0 0-3-3H2.5z"/>'
            '<path d="M21.5 4.5h-6A3.5 3.5 0 0 0 12 8v12a3 3 0 0 1 3-3h6.5z"/>'
        ),
    ),
]
OCRS_ICON = (
    '<svg viewBox="0 0 24 24" width="28" height="28" fill="currentColor" stroke="currentColor" '
    'stroke-width="1.8" stroke-linecap="round">'
    '<path d="M4 4.5 12 19.5M12 4.5v15M20 4.5 12 19.5" fill="none"/>'
    '<circle cx="4" cy="4.5" r="2.2"/><circle cx="12" cy="4.5" r="2.2"/>'
    '<circle cx="20" cy="4.5" r="2.2"/><circle cx="12" cy="19.5" r="3.2"/></svg>'
)


def main():
    """Generate HTML documentation for all schemas."""
    root = Path(__file__).parent.parent
    schemas_dir = root / "src" / "ocrs" / "schemas"
    docs_dir = root / "docs"

    # Ensure docs directory exists
    docs_dir.mkdir(exist_ok=True)

    # Configuration for json-schema-for-humans
    config = GenerationConfiguration(
        template_name="js_offline",
        expand_buttons=True,
        show_breadcrumbs=True,
        collapse_long_descriptions=False,
        link_to_reused_ref=True,
        show_toc=True,
        with_footer=True,
    )

    # Generate docs for the main JSON Schema
    # Note: metric-catalog and mapping-spec are data files, not JSON Schemas
    schema_file = "canonical-review.schema.json"
    output_file = "canonical-review.html"
    schema_path = schemas_dir / schema_file
    output_path = docs_dir / output_file

    print(f"Generating {output_file} from {schema_file}...")
    generate_from_filename(schema_path, output_path, config=config)

    shutil.copytree(root / "site", docs_dir, dirs_exist_ok=True)

    versions = sorted(path.name for path in (root / "versions").iterdir() if path.is_dir())
    for version in versions:
        shutil.copytree(root / "versions" / version, docs_dir / version, dirs_exist_ok=True)

    # Create the landing page
    create_landing_page(docs_dir, versions)

    # Create .nojekyll to prevent GitHub Pages from using Jekyll
    (docs_dir / ".nojekyll").touch()

    print(f"\nDocumentation generated in {docs_dir}")
    print("To preview locally: python -m http.server 8000 --directory docs")


def create_landing_page(docs_dir: Path, versions: list[str]):
    """Create a landing page linking to all schema docs."""
    landing_html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OCRS - Open Canonical Review Schema</title>
    <style>
        :root {
            --bg-color: #1a1a2e;
            --card-bg: #16213e;
            --primary: #0f3460;
            --accent: #e94560;
            --text: #eaeaea;
            --text-muted: #a0a0a0;
        }
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: system-ui, -apple-system, sans-serif;
            background: var(--bg-color);
            color: var(--text);
            min-height: 100vh;
            padding: 2rem;
        }
        .container {
            max-width: 900px;
            margin: 0 auto;
        }
        header {
            text-align: center;
            margin-bottom: 3rem;
        }
        h1 {
            font-size: 2.5rem;
            margin-bottom: 0.5rem;
            background: linear-gradient(135deg, var(--accent), #ff6b6b);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        .subtitle {
            color: var(--text-muted);
            font-size: 1.1rem;
        }
        .intro {
            background: var(--card-bg);
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 2rem;
            border: 1px solid var(--primary);
        }
        .intro p {
            color: var(--text-muted);
            line-height: 1.8;
        }
        .schemas {
            display: grid;
            gap: 1.5rem;
        }
        .schema-card {
            background: var(--card-bg);
            border-radius: 12px;
            padding: 1.5rem;
            border: 1px solid var(--primary);
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .schema-card:hover {
            transform: translateY(-4px);
            box-shadow: 0 8px 24px rgba(233, 69, 96, 0.2);
        }
        .schema-card h2 {
            font-size: 1.3rem;
            margin-bottom: 0.5rem;
        }
        .schema-card h2 a {
            color: var(--text);
            text-decoration: none;
        }
        .schema-card h2 a:hover {
            color: var(--accent);
        }
        .schema-card p {
            color: var(--text-muted);
            line-height: 1.6;
        }
        .badge {
            display: inline-block;
            background: var(--primary);
            color: var(--accent);
            padding: 0.25rem 0.75rem;
            border-radius: 20px;
            font-size: 0.8rem;
            margin-top: 1rem;
        }
        .features {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-top: 1rem;
        }
        .feature {
            background: rgba(15, 52, 96, 0.3);
            padding: 0.75rem;
            border-radius: 8px;
            font-size: 0.9rem;
            color: var(--text-muted);
        }
        .feature strong {
            color: var(--accent);
        }
        footer {
            text-align: center;
            margin-top: 3rem;
            color: var(--text-muted);
            font-size: 0.9rem;
        }
        footer a {
            color: var(--accent);
            text-decoration: none;
        }
        .flow {
            --line: #c8c8c8;
            position: relative;
            margin-bottom: 3rem;
            padding: 3.5rem 1.5rem 3rem;
            border-radius: 16px;
            background: #fafafa;
            color: #171717;
        }
        .flow-lines {
            position: absolute;
            inset: 0;
            width: 100%;
            height: 100%;
            overflow: visible;
            pointer-events: none;
        }
        .flow-lines path {
            fill: none;
            stroke: var(--line);
            stroke-width: 1;
            stroke-linecap: round;
            stroke-linejoin: round;
            transition: stroke 0.2s;
        }
        .flow-lines .source-head {
            fill: var(--line);
            transition: fill 0.2s, stroke 0.2s;
        }
        /* The arrowhead into OCRS is larger and darker, so it holds up where all the lines meet. */
        .flow-lines .hub-head {
            fill: var(--hub-head, #737373);
            stroke: var(--hub-head, #737373);
            stroke-width: 1.5;
            transition: fill 0.2s, stroke 0.2s;
        }
        /* A column for each source; each type spans the columns of its sources. */
        .flow-row {
            position: relative;
            list-style: none;
            display: grid;
            grid-template-columns: repeat(var(--columns), minmax(0, 1fr));
        }
        .flow-leaves {
            gap: 0.25rem;
        }
        .flow-groups {
            /* The source row's gap, so each type spans exactly its sources. */
            gap: 0.25rem;
            margin-bottom: 1.75rem;
        }
        .node {
            display: flex;
            flex-direction: column;
            align-items: center;
            text-align: center;
        }
        .node-icon {
            width: 28px;
            height: 28px;
            display: grid;
            place-items: center;
            margin-bottom: 0.55rem;
            color: #525252;
        }
        .site-badge {
            width: 28px;
            height: 28px;
            border-radius: 6px;
            display: grid;
            place-items: center;
            font-size: 0.62rem;
            font-weight: 800;
            letter-spacing: -0.02em;
        }
        .node-name {
            font-size: 0.82rem;
            font-weight: 500;
            line-height: 1.25;
        }
        .node-sub {
            margin-top: 0.15rem;
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            font-size: 0.68rem;
            color: #737373;
        }
        .flow-groups .node {
            position: relative;
            flex-direction: row;
            justify-content: center;
            gap: 0.55rem;
            padding-bottom: 1rem;
            text-align: left;
        }
        /* A bracket under each type, over the sources it labels. */
        .flow-groups .node::after {
            content: "";
            position: absolute;
            left: 0.75rem;
            right: 0.75rem;
            bottom: 0;
            height: 0.45rem;
            border: 1.5px solid var(--group);
            border-bottom: none;
            border-radius: 4px 4px 0 0;
            opacity: 0.5;
        }
        .flow-groups .node-icon {
            width: 22px;
            height: 22px;
            margin: 0;
            color: var(--group);
        }
        .flow-groups .node-icon svg {
            width: 22px;
            height: 22px;
        }
        .flow-groups .node-name {
            font-size: 0.9rem;
            font-weight: 600;
        }
        .node-text {
            display: flex;
            flex-direction: column;
        }
        /* Text for screen readers only, such as what the arrows say about each source. */
        .visually-hidden {
            position: absolute;
            width: 1px;
            height: 1px;
            overflow: hidden;
            clip-path: inset(50%);
            white-space: nowrap;
        }
        .flow-hub {
            position: relative;
            margin: 6rem auto 0;
            width: fit-content;
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        .hub-title {
            display: flex;
            align-items: center;
            gap: 0.6rem;
            font-size: 2rem;
            font-weight: 700;
            letter-spacing: -0.02em;
        }
        @media (max-width: 720px) {
            body {
                padding: 2rem 1rem;
            }
            .flow {
                padding: 2.5rem 0.5rem 2rem;
            }
            .flow-leaves .node-name {
                position: absolute;
                width: 1px;
                height: 1px;
                overflow: hidden;
                clip-path: inset(50%);
            }
            .flow-leaves .node-icon {
                margin: 0;
            }
            .flow-groups {
                margin-bottom: 1.25rem;
            }
            .flow-groups .node {
                flex-direction: column;
                gap: 0.3rem;
                padding-bottom: 0.8rem;
                text-align: center;
            }
            .flow-groups .node::after {
                left: 0.35rem;
                right: 0.35rem;
            }
            .flow-groups .node-name {
                font-size: 0.8rem;
            }
            .flow-groups .node-sub {
                font-size: 0.6rem;
            }
            .flow-hub {
                margin-top: 4.5rem;
            }
        }
        @media (prefers-reduced-motion: reduce) {
            .flow-lines circle {
                display: none;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>OCRS</h1>
            <p class="subtitle">Open Canonical Review Schema - Documentation</p>
        </header>

        <figure class="flow" style="--columns: FLOW_COLUMNS"
            aria-label="Review sources mapped into OCRS, and back where supported">
            <svg class="flow-lines" aria-hidden="true"></svg>
            <ul class="flow-row flow-groups">
FLOW_GROUPS
            </ul>
            <ul class="flow-row flow-leaves">
FLOW_LEAVES
            </ul>
            <div class="flow-hub">
                <div class="hub-title">OCRS_ICON OCRS</div>
                <div class="node-sub">canonical-review LATEST_VERSION</div>
            </div>
        </figure>

        <div class="intro">
            <p>
                OCRS provides a standardized, machine-readable format for representing peer reviews
                across different platforms and systems. It enables interoperability between review
                systems like OpenReview, CMT, and journal workflows while preserving rich provenance
                information for both human and AI-generated reviews.
            </p>
        </div>

        <div class="schemas">
            <div class="schema-card">
                <h2><a href="canonical-review.html">Canonical Review Schema</a></h2>
                <p>
                    The core schema defining the structure of peer reviews in canonical form.
                </p>
                <div class="features">
                    <div class="feature"><strong>Referees:</strong> Human, AI, Hybrid</div>
                    <div class="feature"><strong>Provenance:</strong> Source tracking</div>
                    <div class="feature"><strong>Findings:</strong> Strengths, weaknesses</div>
                    <div class="feature"><strong>Metrics:</strong> Normalized scores</div>
                    <div class="feature"><strong>Decisions:</strong> Recommendations</div>
                    <div class="feature"><strong>AI Info:</strong> Models, prompts</div>
                </div>
                <span class="badge">JSON Schema Draft 2020-12</span>
            </div>
            <div class="schema-card">
                <h2>Schema files</h2>
                <ul>
VERSION_LINKS
                </ul>
            </div>
        </div>

        <footer>
            <p>
                <a href="https://github.com/valency-oss/open-canonical-review-schema">GitHub</a>
                &nbsp;&middot;&nbsp;
                Apache License 2.0
            </p>
        </footer>
    </div>
    <script>
        // Draw a two-way arrow between each source and OCRS, in the color of the source's type.
        (() => {
            const NS = "http://www.w3.org/2000/svg";
            const flow = document.querySelector(".flow");
            const svg = flow.querySelector(".flow-lines");
            const leafRow = flow.querySelector(".flow-leaves");
            const hub = flow.querySelector(".hub-title");
            const svgElement = (name, attributes) => {
                const element = document.createElementNS(NS, name);
                for (const [key, value] of Object.entries(attributes)) {
                    element.setAttribute(key, value);
                }
                return element;
            };

            // Each edge runs from the bottom of `from` to the top of `to`, each centered on `x`,
            // with an arrowhead into OCRS and a dot that travels it every `duration` seconds,
            // starting `delay` seconds in. A `twoWay` edge also has an arrowhead back at the
            // source, and its dot goes down to OCRS, then back up.
            const edges = [];
            const addEdge = (from, to, color, delay, duration, twoWay) => {
                const line = svgElement("g", {});
                const path = svgElement("path", {});
                const heads = [
                    svgElement("path", { class: "source-head" }),
                    svgElement("path", { class: "hub-head" }),
                ];
                const dot = svgElement("circle", { r: 2.5, fill: color, opacity: 0 });
                line.append(path, ...(twoWay ? heads : heads.slice(1)));
                svg.append(line, dot);
                edges.push({ from, to, path, heads, dot, delay, duration, twoWay, length: 0 });
                return line;
            };

            // Hovering a source lights its arrow; hovering a type lights all of its sources'
            // arrows. A lit arrow is raised, so the shared arrowhead into OCRS shows its color.
            const highlight = (element, lines, color) => {
                element.addEventListener("mouseenter", () => lines.forEach((line) => {
                    line.style.setProperty("--line", color);
                    line.style.setProperty("--hub-head", color);
                    svg.append(line);
                }));
                element.addEventListener("mouseleave", () => lines.forEach((line) => {
                    line.style.removeProperty("--line");
                    line.style.removeProperty("--hub-head");
                }));
            };
            const groupLines = new Map();
            flow.querySelectorAll(".flow-leaves .node").forEach((leaf, i) => {
                const group = flow.querySelector(`#group-${leaf.dataset.group}`);
                const color = getComputedStyle(group).getPropertyValue("--group").trim();
                const line = addEdge(
                    { box: leafRow, x: leaf }, { box: hub, x: hub }, color, i * 0.4, 2.8,
                    leaf.dataset.twoWay === "true",
                );
                highlight(leaf, [line], color);
                if (!groupLines.has(group)) groupLines.set(group, { color, lines: [] });
                groupLines.get(group).lines.push(line);
            });
            for (const [group, { color, lines }] of groupLines) {
                highlight(group, lines, color);
            }

            const layout = () => {
                const origin = flow.getBoundingClientRect();
                svg.setAttribute("viewBox", `0 0 ${origin.width} ${origin.height}`);
                const centerX = (element) => {
                    const box = element.getBoundingClientRect();
                    return box.left + box.width / 2 - origin.left;
                };
                // A solid arrowhead with its tip at (x, y), pointing up (-1) or down (1). The line
                // meets the middle of its base, so it enters the head straight.
                const SOURCE_HEAD = { halfWidth: 3.5, length: 6 };
                const HUB_HEAD = { halfWidth: 7, length: 11 };
                const head = (x, y, direction, { halfWidth, length }) =>
                    `M${x - halfWidth},${y - length * direction} L${x},${y} ` +
                    `L${x + halfWidth},${y - length * direction} Z`;
                for (const edge of edges) {
                    const { from, to, path, heads, twoWay } = edge;
                    const x1 = centerX(from.x);
                    const y1 = from.box.getBoundingClientRect().bottom - origin.top + 10;
                    const x2 = centerX(to.x);
                    const y2 = to.box.getBoundingClientRect().top - origin.top - 10;
                    const start = twoWay ? y1 + SOURCE_HEAD.length : y1;
                    const end = y2 - HUB_HEAD.length;
                    const bend = (end - start) / 2;
                    const d =
                        `M${x1},${start} C${x1},${start + bend} ${x2},${end - bend} ${x2},${end}`;
                    path.setAttribute("d", d);
                    heads[0].setAttribute("d", head(x1, y1, -1, SOURCE_HEAD));
                    heads[1].setAttribute("d", head(x2, y2, 1, HUB_HEAD));
                    edge.length = path.getTotalLength();
                }
            };
            new ResizeObserver(layout).observe(flow);
            layout();

            const ease = (t) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2);
            const tick = (now) => {
                for (const { path, dot, delay, duration, twoWay, length } of edges) {
                    const elapsed = now / 1000 - delay;
                    if (elapsed < 0) continue;
                    const t = (elapsed % duration) / duration;
                    const down = !twoWay || Math.floor(elapsed / duration) % 2 === 0;
                    const point = path.getPointAtLength((down ? ease(t) : 1 - ease(t)) * length);
                    dot.setAttribute("cx", point.x);
                    dot.setAttribute("cy", point.y);
                    dot.setAttribute("opacity", Math.min(1, t / 0.15, (1 - t) / 0.15));
                }
                requestAnimationFrame(tick);
            };
            if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
                requestAnimationFrame(tick);
            }
        })();
    </script>
</body>
</html>
"""
    version_links = "\n".join(
        f'{" " * 20}<li><a href="{version}/canonical-review.schema.json">{version}</a></li>'
        for version in reversed(versions)
    )
    unknown = {key for key, *_ in SOURCES} - set(supported_sources())
    if unknown:
        raise ValueError(f"Diagram sources missing from the registry: {sorted(unknown)}")
    targets = supported_targets()
    # What each source's arrow shows, for its tooltip and for screen readers.
    directions = {
        key: "maps to and from OCRS" if key in targets else "maps to OCRS only"
        for key, *_ in SOURCES
    }
    flow_leaves = "\n".join(
        f'{" " * 16}<li class="node" data-group="{group}" '
        f'data-two-way="{str(key in targets).lower()}" '
        f'title="{name.replace("<wbr>", "")}: {directions[key]}">'
        f'<span class="node-icon" aria-hidden="true">{icon}</span>'
        f'<span class="node-name">{name}</span>'
        f'<span class="visually-hidden">, {directions[key]}</span></li>'
        for key, name, group, icon in SOURCES
    )
    flow_groups = "\n".join(
        f'{" " * 16}<li class="node" id="group-{key}" '
        f'style="--group: {color}; grid-column: span {sum(g == key for _, _, g, _ in SOURCES)}">'
        f'<span class="node-icon" aria-hidden="true">{icon}</span><span class="node-text">'
        f'<span class="node-name">{name}</span><span class="node-sub">{referee}</span></span></li>'
        for key, name, referee, color, icon in GROUPS
    )
    landing_html = (
        landing_html.replace("VERSION_LINKS", version_links)
        .replace("FLOW_LEAVES", flow_leaves)
        .replace("FLOW_GROUPS", flow_groups)
        .replace("FLOW_COLUMNS", str(len(SOURCES)))
        .replace("OCRS_ICON", OCRS_ICON)
        .replace("LATEST_VERSION", versions[-1])
    )
    # Write as index.html - the landing page for GitHub Pages
    (docs_dir / "index.html").write_text(landing_html)


if __name__ == "__main__":
    main()
