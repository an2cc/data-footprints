# SPDX-FileCopyrightText: 2026 Anna Caellas-Camprubí
# SPDX-License-Identifier: EUPL-1.2

"""Interactive researcher-level network for Data Footprints.

The graph keeps the researcher as the central entity and represents the full
research-data portfolio. Dataset nodes lead to incoming citing publications and
the authors of those publications. Projects are deliberately excluded from the
visual layer in this version.
"""

from __future__ import annotations

import json
import math
import textwrap
from collections import defaultdict
from typing import Any

from pyvis.network import Network

from reconciliation import names_match, normalize_doi, normalize_name, strip_html

NODE_COLORS = {
    "researcher": "#fdd835",
    "dataset": "#2e7d32",
    "citing_publication": "#1565c0",
    "citing_author": "#f57c00",
    "shared_author": "#ec407a",
    "repository": "#00838f",
    "unresolved": "#c62828",
}

NODE_SHAPES = {
    "researcher": "dot",
    "dataset": "dot",
    "citing_publication": "dot",
    "citing_author": "dot",
    "repository": "dot",
    "unresolved": "dot",
}


def _shorten(text: str, length: int = 24) -> str:
    cleaned = " ".join(str(text or "").split())
    return cleaned if len(cleaned) <= length else f"{cleaned[: length - 1]}…"


def _surname(name: str) -> str:
    cleaned = " ".join(str(name or "Unknown author").split())
    if "," in cleaned:
        return cleaned.split(",", 1)[0]
    parts = cleaned.split()
    return parts[-1] if parts else "Author"


def _polar(radius: float, angle: float) -> tuple[float, float]:
    return radius * math.cos(angle), radius * math.sin(angle)


def _node_title(heading: str, lines: list[tuple[str, Any]]) -> str:
    # Plain text is intentional. Some browser/vis-network combinations display
    # HTML tooltip markup literally inside Streamlit iframes.
    content = [strip_html(heading)]
    for label, value in lines:
        if value not in (None, "", [], {}):
            content.append(f"{strip_html(label)}: {strip_html(value)}")
    return "\n".join(content)


def _wrapped_label(value: str, width: int = 18, max_lines: int = 2) -> str:
    cleaned = strip_html(value) or "Untitled"
    lines = textwrap.wrap(cleaned, width=width, break_long_words=False, break_on_hyphens=False)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _shorten(lines[-1], max(5, width - 1))
    return "\n".join(lines)


def _author_identity_key(author: dict[str, Any]) -> tuple[str, str]:
    """Conservative person key: ORCID first, otherwise exact full-name tokens."""
    orcid = str(author.get("orcid") or "").lower().strip()
    if orcid:
        return ("orcid", orcid)
    tokens = sorted(normalize_name(str(author.get("name") or "Unknown author")).split())
    return ("name", " ".join(tokens))


def _same_person(author: dict[str, Any], other_name: str | None, other_orcid: str | None = None) -> bool:
    author_orcid = str(author.get("orcid") or "").lower().strip()
    candidate_orcid = str(other_orcid or "").lower().strip()
    if author_orcid and candidate_orcid and author_orcid == candidate_orcid:
        return True
    return bool(other_name and names_match(str(author.get("name") or ""), str(other_name)))


def _is_central_researcher(author: dict[str, Any], researcher: dict[str, Any]) -> bool:
    return _same_person(author, researcher.get("name"), researcher.get("orcid"))


def _shared_detail_for_author(author: dict[str, Any], publication: dict[str, Any]) -> dict[str, Any] | None:
    for detail in publication.get("shared_author_details", []) or []:
        if _same_person(author, detail.get("citing_name"), detail.get("citing_orcid")):
            return detail
    for shared_name in publication.get("shared_authors", []) or []:
        if names_match(str(author.get("name") or ""), str(shared_name)):
            return {"citing_name": shared_name, "evidence": "exact full name", "role": "dataset_team_member"}
    return None


def build_researcher_network_html(
    data: dict[str, Any],
    *,
    show_citing_publications: bool = True,
    show_citing_authors: bool = True,
    show_unresolved: bool = True,
    show_repositories: bool = False,
    compact_labels: bool = True,
    enable_physics: bool = True,
    pin_researcher: bool = True,
) -> str:
    """Return a self-contained draggable vis-network graph as HTML.

    The initial layout is concentric and deterministic. Physics can optionally
    be enabled to untangle dense networks. With physics disabled, every node
    except an optionally pinned researcher remains draggable.
    """

    researcher = data.get("researcher", {})
    datasets = data.get("datasets", [])
    citing_publications = data.get("citing_publications", [])
    dataset_by_id = {str(dataset.get("id")): dataset for dataset in datasets}

    network = Network(
        height="820px",
        width="100%",
        bgcolor="#ffffff",
        font_color="#263238",
        directed=True,
        cdn_resources="in_line",
        neighborhood_highlight=False,
        select_menu=False,
        filter_menu=False,
    )

    options = {
        "autoResize": True,
        "layout": {"improvedLayout": False, "randomSeed": 23},
        "interaction": {
            "hover": True,
            "tooltipDelay": 120,
            "navigationButtons": True,
            "keyboard": {"enabled": True, "bindToWindow": False},
            "hideEdgesOnDrag": True,
            "hideEdgesOnZoom": False,
            "multiselect": True,
        },
        "nodes": {
            "borderWidth": 2,
            "borderWidthSelected": 4,
            "shadow": {"enabled": True, "color": "rgba(16,24,40,0.18)", "size": 8, "x": 0, "y": 3},
            "font": {"face": "Arial", "size": 15, "color": "#263238", "strokeWidth": 3, "strokeColor": "#ffffff"},
        },
        "edges": {
            "arrows": {"to": {"enabled": True, "scaleFactor": 0.55}},
            "color": {"color": "#98a2b3", "highlight": "#475467", "hover": "#475467"},
            "smooth": {"enabled": True, "type": "dynamic", "roundness": 0.35},
            "width": 1.35,
            "selectionWidth": 2.2,
            "hoverWidth": 1.8,
        },
        "physics": {
            "enabled": enable_physics,
            "solver": "forceAtlas2Based",
            "forceAtlas2Based": {
                "gravitationalConstant": -70,
                "centralGravity": 0.012,
                "springLength": 185,
                "springConstant": 0.06,
                "damping": 0.55,
                "avoidOverlap": 0.85,
            },
            "stabilization": {"enabled": True, "iterations": 700, "updateInterval": 50, "fit": True},
        },
    }
    network.set_options(json.dumps(options))

    # Researcher at the centre.
    researcher_name = researcher.get("name") or "Researcher"
    network.add_node(
        "target_researcher",
        label=_wrapped_label(researcher_name, 18, 2),
        title=_node_title(researcher_name, [("ORCID", researcher.get("orcid")), ("Role", "Researcher analysed")]),
        color={
            "background": NODE_COLORS["researcher"],
            "border": "#8d6e00",
            "highlight": {"background": "#ffeb75", "border": "#6d4c00"},
            "hover": {"background": "#ffeb75", "border": "#6d4c00"},
        },
        borderWidth=4,
        shape=NODE_SHAPES["researcher"],
        size=38,
        x=0,
        y=0,
        fixed={"x": pin_researcher, "y": pin_researcher},
        physics=not pin_researcher and enable_physics,
        mass=6,
    )

    if not datasets:
        return network.generate_html(notebook=False)

    # Count resolved incoming publication relations per dataset so the tooltip
    # can distinguish them from the BIP! citation-count indicator.
    resolved_relations_by_dataset: dict[str, int] = defaultdict(int)
    for publication in citing_publications:
        dataset_id = str(publication.get("dataset_id") or "")
        if dataset_id:
            resolved_relations_by_dataset[dataset_id] += 1

    # Dataset ring.
    dataset_radius = max(410.0, 300.0 + len(datasets) * 8.0)
    dataset_angles: dict[str, float] = {}
    dataset_index: dict[str, int] = {}
    dataset_display_ids: dict[str, str] = {}
    for index, dataset in enumerate(datasets, start=1):
        angle = -math.pi / 2 + 2 * math.pi * (index - 1) / max(1, len(datasets))
        dataset_id = str(dataset["id"])
        dataset_angles[dataset_id] = angle
        dataset_index[dataset_id] = index
        display_id = str(dataset.get("display_id") or f"D{index}")
        dataset_display_ids[dataset_id] = display_id
        x, y = _polar(dataset_radius, angle)
        label = display_id if compact_labels else _wrapped_label(dataset.get("title") or "Untitled dataset", 17, 2)
        citations = int(dataset.get("citations") or 0)
        size = 22 + min(14, citations * 3)
        network.add_node(
            dataset_id,
            label=label,
            title=_node_title(
                dataset.get("title") or "Untitled dataset",
                [
                    ("DOI", dataset.get("doi") or "PID unresolved"),
                    ("Repository", dataset.get("repository") or "Unknown repository"),
                    ("Year", dataset.get("year")),
                    ("BIP! citation-count indicator", citations),
                    ("Resolved incoming citation relations", resolved_relations_by_dataset.get(dataset_id, 0)),
                    ("Dataset authors", "; ".join(str(a.get("name") or "Unknown") for a in dataset.get("authors", [])) or "Not available"),
                    ("Authorship evidence", str(dataset.get("authorship_status") or "").replace("_", " ")),
                    ("Dataset ID", display_id),
                ],
            ),
            color=NODE_COLORS["dataset"],
            shape=NODE_SHAPES["dataset"],
            size=size,
            x=x,
            y=y,
            physics=enable_physics,
            mass=3,
        )
        network.add_edge(
            "target_researcher",
            dataset_id,
            title="Authored dataset",
            color="#667085",
            width=1.8,
        )

    # Optional repository nodes. They are off by default because shared
    # repository edges can make the portfolio graph difficult to read.
    if show_repositories:
        repositories = sorted({str(d.get("repository") or "Unknown repository") for d in datasets})
        repo_ids = {repo: f"repository_{idx}" for idx, repo in enumerate(repositories, start=1)}
        repo_radius = dataset_radius * 0.55
        for idx, repository in enumerate(repositories, start=1):
            angle = -math.pi / 2 + 2 * math.pi * (idx - 1) / max(1, len(repositories))
            x, y = _polar(repo_radius, angle)
            network.add_node(
                repo_ids[repository],
                label=f"R{idx}" if compact_labels else _wrapped_label(repository, 16, 2),
                title=_node_title(repository, [("Type", "Repository / publishing source")]),
                color=NODE_COLORS["repository"],
                shape=NODE_SHAPES["repository"],
                size=20,
                x=x,
                y=y,
                physics=enable_physics,
                mass=2,
            )
        for dataset in datasets:
            repository = str(dataset.get("repository") or "Unknown repository")
            network.add_edge(
                dataset["id"],
                repo_ids[repository],
                title="Hosted or published by",
                color="#80aeb3",
                dashes=True,
                width=1.0,
            )

    # Incoming publications by dataset.
    publications_by_dataset: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for publication in citing_publications:
        dataset_id = str(publication.get("dataset_id") or "")
        if dataset_id:
            publications_by_dataset[dataset_id].append(publication)

    publication_counter = 0
    author_ids: dict[tuple[str, str], str] = {}
    author_counter = 0
    resolved_counts: dict[str, int] = defaultdict(int)
    shared_dataset_edges: set[tuple[str, str]] = set()

    # Aggregate author roles before drawing. An orange node is simply an author
    # of a citing publication. A pink node means that the same person also
    # created at least one cited dataset in the current map.
    author_contexts: dict[tuple[str, str], dict[str, Any]] = {}
    for publication in citing_publications:
        dataset_id = str(publication.get("dataset_id") or "")
        display_id = str(publication.get("dataset_display_id") or dataset_display_ids.get(dataset_id) or "?")
        for author in publication.get("authors", []) or []:
            key = _author_identity_key(author)
            context = author_contexts.setdefault(key, {
                "name": str(author.get("name") or "Unknown author"),
                "orcid": author.get("orcid"),
                "publication_titles": set(),
                "dataset_ids": set(),
                "shared_dataset_ids": set(),
                "is_central_researcher": False,
            })
            context["publication_titles"].add(str(publication.get("title") or "Untitled publication"))
            context["dataset_ids"].add(display_id)
            detail = _shared_detail_for_author(author, publication)
            if detail:
                context["shared_dataset_ids"].add(display_id)
            if _is_central_researcher(author, researcher):
                context["is_central_researcher"] = True

    if show_citing_publications:
        publication_radius = dataset_radius + 330.0
        author_radius = publication_radius + 285.0
        for dataset_id, publications in publications_by_dataset.items():
            if dataset_id not in dataset_angles:
                continue
            base_angle = dataset_angles[dataset_id]
            count = len(publications)
            spread = min(0.8, 0.18 + 0.14 * max(0, count - 1))
            for pub_pos, publication in enumerate(publications):
                publication_counter += 1
                offset = 0.0 if count == 1 else -spread / 2 + spread * pub_pos / (count - 1)
                angle = base_angle + offset
                x, y = _polar(publication_radius, angle)
                pub_id = str(publication["id"])
                resolved_counts[dataset_id] += 1
                pub_label = f"P{publication_counter}" if compact_labels else _shorten(publication.get("title") or "Untitled publication", 24)
                author_names = "; ".join(str(a.get("name") or "Unknown") for a in publication.get("authors", []))
                cited_dataset = dataset_by_id.get(dataset_id, {})
                dataset_creator_names = "; ".join(
                    str(a.get("name") or "Unknown") for a in cited_dataset.get("authors", [])
                )
                shared_names = "; ".join(publication.get("shared_authors", []) or [])
                publication_doi = normalize_doi(publication.get("doi"))
                publication_pid = publication.get("pid") or (publication.get("doi") if not publication_doi else None)
                network.add_node(
                    pub_id,
                    label=pub_label,
                    title=_node_title(
                        publication.get("title") or "Untitled citing publication",
                        [
                            ("DOI", publication_doi or "Not available"),
                            ("OpenAIRE ID", publication_pid if not publication_doi else None),
                            ("Year", publication.get("year")),
                            ("Citing-publication authors", author_names or "Not available"),
                            ("Relation", "Cites or reuses the dataset"),
                            ("Cited dataset", f"{dataset_display_ids.get(dataset_id, '?')} — {cited_dataset.get('title') or 'Untitled dataset'}"),
                            ("Dataset creators", dataset_creator_names or "Not available"),
                            ("Citation authorship classification", publication.get("citation_authorship_label") or "Authorship relation unresolved"),
                            ("Author overlap", shared_names or "None identified"),
                            ("Dataset–publication comparison", publication.get("citation_authorship_evidence")),
                            ("Evidence source", publication.get("evidence_source")),
                        ],
                    ),
                    color=NODE_COLORS["citing_publication"],
                    shape=NODE_SHAPES["citing_publication"],
                    size=23,
                    x=x,
                    y=y,
                    physics=enable_physics,
                    mass=2.5,
                )
                network.add_edge(
                    pub_id,
                    dataset_id,
                    title=publication.get("citation_authorship_label") or "Cites or reuses dataset",
                    color="#1565c0",
                    width=2.2,
                )

                if not show_citing_authors:
                    continue
                authors = publication.get("authors", [])
                for author_pos, author in enumerate(authors):
                    key = _author_identity_key(author)
                    context = author_contexts.get(key, {})
                    is_researcher = _is_central_researcher(author, researcher)
                    shared_detail = _shared_detail_for_author(author, publication)
                    is_shared = shared_detail is not None

                    # A self-citation is shown by connecting the central
                    # researcher directly to the citing publication rather than
                    # creating a duplicate orange person node.
                    if is_researcher:
                        network.add_edge(
                            "target_researcher",
                            pub_id,
                            title="Central researcher authored the citing publication — researcher self-citation",
                            color="#5e35b1",
                            width=3.0,
                        )
                        continue

                    if key not in author_ids:
                        author_counter += 1
                        author_id = f"citing_author_{author_counter}"
                        author_ids[key] = author_id
                        author_offset = (author_pos - (len(authors) - 1) / 2) * 0.065
                        ax, ay = _polar(author_radius, angle + author_offset)
                        display_name = str(context.get("name") or author.get("name") or "Unknown author")
                        author_label = f"A{author_counter}" if compact_labels else _wrapped_label(_surname(display_name), 14, 1)
                        shared_ids = sorted(context.get("shared_dataset_ids", set()))
                        compared_ids = sorted(context.get("dataset_ids", set()))
                        node_colour: Any = NODE_COLORS["citing_author"]
                        border_width = 2
                        if shared_ids:
                            node_colour = {
                                "background": NODE_COLORS["shared_author"],
                                "border": "#ad1457",
                                "highlight": {"background": "#f06292", "border": "#880e4f"},
                                "hover": {"background": "#f06292", "border": "#880e4f"},
                            }
                            border_width = 4
                        network.add_node(
                            author_id,
                            label=author_label,
                            title=_node_title(
                                display_name,
                                [
                                    ("ORCID", context.get("orcid") or "Not available"),
                                    ("Role", "Author of a citing publication"),
                                    ("Cited dataset(s) connected to their publication(s)", ", ".join(compared_ids) or "Not available"),
                                    ("Also creator of cited dataset(s)", ", ".join(shared_ids) or "No"),
                                ],
                            ),
                            color=node_colour,
                            borderWidth=border_width,
                            shape=NODE_SHAPES["citing_author"],
                            size=18 if shared_ids else 17,
                            x=ax,
                            y=ay,
                            physics=enable_physics,
                            mass=1.5,
                        )

                    author_id = author_ids[key]
                    if is_shared:
                        evidence_text = str(shared_detail.get("evidence") or "author identity match")
                        network.add_edge(
                            author_id,
                            pub_id,
                            title=f"Authored citing publication and also created {dataset_display_ids.get(dataset_id, '?')} — matched by {evidence_text}",
                            color="#ec407a",
                            width=2.5,
                        )
                        overlap_edge = (author_id, dataset_id)
                        if overlap_edge not in shared_dataset_edges:
                            shared_dataset_edges.add(overlap_edge)
                            network.add_edge(
                                author_id,
                                dataset_id,
                                title=f"Also creator of cited dataset {dataset_display_ids.get(dataset_id, '?')}",
                                color="#ec407a",
                                dashes=True,
                                width=1.8,
                            )
                    else:
                        network.add_edge(
                            author_id,
                            pub_id,
                            title="Author of citing publication; no match with the creators of this cited dataset",
                            color="#9c6ade",
                            width=1.0,
                        )

    # Diagnostic BIP! indicator counts not matched to resolved incoming relations.
    if show_unresolved:
        unresolved_radius = dataset_radius + 245.0
        for dataset in datasets:
            dataset_id = str(dataset["id"])
            citation_count = int(dataset.get("citations") or 0)
            unresolved_count = max(0, citation_count - resolved_counts.get(dataset_id, 0))
            if unresolved_count <= 0:
                continue
            angle = dataset_angles[dataset_id] + 0.1
            x, y = _polar(unresolved_radius, angle)
            unresolved_id = f"unresolved_{dataset_id}"
            network.add_node(
                unresolved_id,
                label=f"?{unresolved_count}",
                title=_node_title(
                    f"{unresolved_count} unmatched citation-count indicator(s)",
                    [
                        ("Dataset ID", dataset_display_ids.get(dataset_id)),
                        ("Dataset", dataset.get("title")),
                        ("Meaning", "The BIP! citation-count indicator exceeds the number of identifiable incoming publication relations currently exposed by Graph API V3"),
                    ],
                ),
                color=NODE_COLORS["unresolved"],
                shape=NODE_SHAPES["unresolved"],
                size=19,
                x=x,
                y=y,
                physics=enable_physics,
                mass=1.8,
            )
            network.add_edge(
                unresolved_id,
                dataset_id,
                title="Citation-count indicator not matched to a resolved relation",
                color="#c62828",
                dashes=True,
                width=2.0,
            )

    generated = network.generate_html(notebook=False)
    legend = """
    <div style="font-family:Arial,sans-serif;padding:10px 14px 6px;color:#344054;font-size:13px;line-height:1.5">
      <div style="display:flex;gap:16px;flex-wrap:wrap;align-items:center">
        <span><b style="color:#fdd835;-webkit-text-stroke:1px #8d6e00">●</b> Searched ORCID person</span>
        <span><b style="color:#2e7d32">●</b> Dataset</span>
        <span><b style="color:#1565c0">●</b> Citing publication</span>
        <span><b style="color:#f57c00">●</b> Author of citing publication</span>
        <span><b style="color:#ec407a;-webkit-text-stroke:1px #ad1457">●</b> Citing author who also created the dataset</span>
        <span><b style="color:#c62828">●</b> Indicator–relation gap</span>
      </div>
      <div style="margin-top:5px;color:#667085">All entities are circles. Orange means author of a citing publication; it does not by itself imply an authorship match. A pink node and dashed pink link identify a person who also created the cited dataset. The yellow central node is the person identified by the searched ORCID. A direct purple researcher–publication link identifies a researcher self-citation. Drag nodes to reposition them and hover for the full evidence.</div>
    </div>
    """
    freeze_script = """
    <script>
      if (typeof network !== 'undefined') {
        network.once('stabilizationIterationsDone', function () {
          network.setOptions({physics: {enabled: false}});
          network.fit({animation: {duration: 350}});
        });
      }
    </script>
    """
    generated = generated.replace("</body>", freeze_script + "</body>")
    return generated.replace("<body>", f"<body>{legend}", 1)
