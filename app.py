# SPDX-FileCopyrightText: 2026 Anna Caellas-Camprubí
# SPDX-License-Identifier: EUPL-1.2

from __future__ import annotations

import json
import re
from typing import Any

import pandas as pd
import streamlit as st

from providers import (
    OpenAIREProvider,
    ProviderError,
    clear_oauth_state,
    oauth_state_exists,
)
from reconciliation import (
    authorship_status,
    classify_citation_authorship,
    deduplicate_dataset_records,
    expand_name_variants,
    matching_author,
    normalize_authors,
    normalize_doi,
    normalize_name,
    stable_id,
    strip_html,
    title_key,
)
from visuals import build_researcher_network_html

ORCID_PATTERN = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dXx]$")

st.set_page_config(page_title="Data Footprints", page_icon="🔗", layout="wide")

st.markdown(
    """
<style>
.block-container {padding-top:1.2rem; padding-bottom:3rem; max-width:1500px;}
.df-header {background:linear-gradient(135deg,#263238,#37474f); color:white; padding:1.8rem 2rem; border-radius:15px; margin-bottom:1rem;}
.df-header h1 {margin:0 0 .25rem; font-size:2.1rem;}
.df-header h2 {margin:0; font-size:1.08rem; font-weight:500; opacity:.92;}
.df-header p {margin:.9rem 0 0; max-width:1100px; line-height:1.5; opacity:.9;}
.build-intro {margin:.25rem 0 .5rem;}
.build-intro h3 {margin:0 0 .15rem; font-size:1.18rem;}
.build-intro p {margin:0; color:#667085; font-size:.86rem; line-height:1.45;}
.df-footer {margin-top:2.2rem; padding-top:1rem; border-top:1px solid #e5e7eb; color:#667085; font-size:.82rem; line-height:1.55;}
.metric-grid {display:grid; grid-template-columns:repeat(6,minmax(140px,1fr)); gap:.75rem; margin:.85rem 0 1rem;}
.metric-card {background:#fff; border:1px solid #e5e7eb; border-radius:13px; padding:1rem; box-shadow:0 3px 12px rgba(16,24,40,.04);}
.metric-card .value {font-size:1.8rem; font-weight:780; line-height:1; color:#1f2937;}
.metric-card .label {margin-top:.45rem; color:#667085; font-size:.78rem; line-height:1.35;}
.metric-card.green {border-left:5px solid #00897b;}.metric-card.orange {border-left:5px solid #ef6c00;}.metric-card.red {border-left:5px solid #c62828;}.metric-card.purple {border-left:5px solid #5e35b1;}
.panel-title {background:#fff; border:1px solid #e5e7eb; border-bottom:0; border-radius:14px 14px 0 0; padding:1rem 1.2rem .75rem; margin-top:.8rem;}
.panel-title h3 {margin:0 0 .2rem; font-size:1.18rem;}.panel-title p {margin:0; color:#667085; font-size:.86rem; line-height:1.45;}
.profile-card {border:1px solid #e5e7eb; border-radius:12px; padding:.9rem; background:#fbfcfe; margin-bottom:.65rem;}
.profile-card h4 {margin:0 0 .3rem; font-size:.9rem;}.profile-card strong {font-size:1.08rem;}.profile-card p {margin:.3rem 0 0; color:#667085; font-size:.78rem; line-height:1.4;}
.status-confirmed {background:#eef2f6;color:#344054;padding:.2rem .45rem;border-radius:999px;font-weight:650;}.status-recovered {background:#e0f2f1;color:#00695c;padding:.2rem .45rem;border-radius:999px;font-weight:650;}.status-candidate {background:#fff3e0;color:#ad4d00;padding:.2rem .45rem;border-radius:999px;font-weight:650;}.status-unresolved {background:#ffebee;color:#b71c1c;padding:.2rem .45rem;border-radius:999px;font-weight:650;}
@media(max-width:1100px){.metric-grid{grid-template-columns:repeat(3,1fr);}} @media(max-width:650px){.metric-grid{grid-template-columns:repeat(2,1fr);}}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    """
<div class="df-header">
  <h1>Data Footprints</h1>
  <h2>Tracing dataset citation pathways for responsible research assessment</h2>
  <p><strong>What story do your research data tell?</strong><br>
  Discover your datasets across the OpenAIRE Graph, trace the publications that cite them, and uncover signals of how your data travel within and beyond your research team.</p>
</div>
""",
    unsafe_allow_html=True,
)



def validate_orcid(orcid: str) -> bool:
    return bool(ORCID_PATTERN.match(orcid.strip()))


def _repository(record: dict[str, Any]) -> tuple[str, list[str]]:
    hosted = [str(item) for item in (record.get("hosted_by") or []) if item]
    publisher = str(record.get("publisher") or "").strip()
    repositories = []
    if publisher:
        repositories.append(publisher)
    repositories.extend(item for item in hosted if item not in repositories)
    primary = publisher or (hosted[0] if hosted else "Unknown repository")
    return primary, repositories


def _extract_names(records: list[dict[str, Any]], orcid: str) -> list[str]:
    names: set[str] = set()
    for record in records:
        for author in normalize_authors(record.get("authors")):
            if str(author.get("orcid") or "").lower() == orcid.lower() and author.get("name"):
                names.add(str(author["name"]))
    return sorted(names)


def _first(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _citation_source(link: dict[str, Any]) -> dict[str, Any]:
    """Extract the citing-product stub without confusing an OpenAIRE ID for a DOI."""
    source = link.get("source") if isinstance(link.get("source"), dict) else {}
    raw_identifier = _first(
        link,
        ("sourcePid", "source_pid", "sourceIdentifier", "source_identifier", "source_doi", "doi"),
    ) or _first(source, ("pid", "identifier", "id", "doi"))
    explicit_doi = _first(link, ("sourceDoi", "sourceDOI", "source_doi", "doi")) or _first(source, ("doi", "DOI"))
    title = _first(link, ("sourceTitle", "source_title", "title")) or _first(source, ("title", "mainTitle", "name"))
    authors = _first(link, ("sourceAuthors", "source_authors", "authors", "creators")) or _first(source, ("authors", "creators"))
    date = _first(link, ("sourcePublicationDate", "source_date", "publication_date", "date")) or _first(source, ("publication_date", "date"))
    provenance = link.get("provenance") or []
    if isinstance(provenance, str):
        provenance = [provenance]
    return {
        "identifier": str(raw_identifier).strip() if raw_identifier else None,
        "doi": normalize_doi(explicit_doi) or normalize_doi(raw_identifier),
        "title": str(title) if title else None,
        "authors": normalize_authors(authors),
        "publication_date": str(date) if date else None,
        "provenance": [str(item) for item in provenance if item],
    }


def _merge_publication_metadata(item: dict[str, Any], details: dict[str, Any]) -> dict[str, Any]:
    item["title"] = item.get("title") or details.get("title") or details.get("main_title")
    item["authors"] = item.get("authors") or normalize_authors(details.get("authors") or details.get("creators"))
    item["publication_date"] = item.get("publication_date") or details.get("publication_date")
    item["doi"] = normalize_doi(item.get("doi")) or normalize_doi(details.get("doi"))
    return item


def _enrich_citing_publication(provider: OpenAIREProvider, item: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    """Resolve DOI and authors from the OpenAIRE product record when possible."""
    identifier = item.get("doi") or item.get("identifier")
    needs_metadata = not item.get("doi") or not item.get("title") or not item.get("authors") or not item.get("publication_date")
    if identifier and needs_metadata:
        try:
            details = provider.get_product_details(str(identifier))
        except ProviderError as exc:
            warnings.append(f"Could not enrich citing publication {identifier}: {exc}")
        else:
            _merge_publication_metadata(item, details)

    # Some relationship records expose only an internal OpenAIRE ID and a
    # title. If product-details enrichment still lacks a DOI or authors, use a
    # conservative exact-title lookup rather than displaying the internal ID as
    # though it were a DOI.
    if item.get("title") and (not item.get("doi") or not item.get("authors")):
        try:
            candidates = provider.search_publications_by_title(str(item["title"]), page_size=5)
        except ProviderError as exc:
            warnings.append(f"Could not enrich citing publication by title {item.get('title')}: {exc}")
        else:
            expected = normalize_name(strip_html(item.get("title")))
            exact = next(
                (candidate for candidate in candidates if normalize_name(strip_html(candidate.get("title") or candidate.get("main_title"))) == expected),
                None,
            )
            if exact:
                _merge_publication_metadata(item, exact)

    item["doi"] = normalize_doi(item.get("doi"))
    return item


def _publication_identity_key(publication: dict[str, Any]) -> tuple[str, str]:
    """Identity used for aggregate counts, not for graph relation nodes."""
    doi = normalize_doi(publication.get("doi"))
    if doi:
        return ("doi", doi)
    pid = str(publication.get("pid") or "").strip().lower()
    if pid:
        return ("pid", pid)
    title = normalize_name(strip_html(publication.get("title") or ""))
    return ("title", title)


def _reconciled_citing_author_count(citing_publications: list[dict[str, Any]]) -> int:
    """Count author identities conservatively across citing publications.

    ORCID is the strongest key. A name-only record is merged with an ORCID
    identity only when the exact complete-name token set maps to one unique
    ORCID elsewhere in the retrieved citing-publication metadata.
    """
    name_to_orcids: dict[str, set[str]] = {}
    authors: list[dict[str, Any]] = []

    for publication in citing_publications:
        for author in normalize_authors(publication.get("authors")):
            authors.append(author)
            name_key = " ".join(sorted(normalize_name(str(author.get("name") or "")).split()))
            orcid = str(author.get("orcid") or "").strip().lower()
            if name_key and orcid:
                name_to_orcids.setdefault(name_key, set()).add(orcid)

    identities: set[tuple[str, str]] = set()
    for author in authors:
        name_key = " ".join(sorted(normalize_name(str(author.get("name") or "")).split()))
        orcid = str(author.get("orcid") or "").strip().lower()
        if orcid:
            identities.add(("orcid", orcid))
            continue
        linked_orcids = name_to_orcids.get(name_key, set())
        if len(linked_orcids) == 1:
            identities.add(("orcid", next(iter(linked_orcids))))
        elif name_key:
            identities.add(("name", name_key))

    return len(identities)


@st.cache_data(ttl=3600, show_spinner=False)
def build_live_data(orcid: str, supplied_names: tuple[str, ...], lookup_citations: bool) -> tuple[dict[str, Any], list[str]]:
    provider = OpenAIREProvider()
    warnings: list[str] = []
    direct_records, direct_pages = provider.search_datasets_by_orcid_paginated(orcid)

    original_names = [name.strip() for name in supplied_names if name.strip()]
    inferred_names = _extract_names(direct_records, orcid)
    if not original_names and not inferred_names:
        try:
            profile = provider.get_author_profile(orcid)
            profile_name = profile.get("name") or profile.get("full_name") or profile.get("author_name")
            if profile_name:
                inferred_names.append(str(profile_name))
        except ProviderError as exc:
            warnings.append(f"Researcher name could not be inferred from the MCP profile: {exc}")

    names = expand_name_variants(original_names + inferred_names)
    name_records: list[dict[str, Any]] = []
    name_search_pages = 0
    if names:
        name_records, name_search_pages = provider.search_datasets_by_names_paginated(names)
    else:
        warnings.append("No name variant was available, so only the direct ORCID query was used.")

    raw_combined: dict[str, dict[str, Any]] = {}
    direct_keys: set[str] = set()
    for record in direct_records:
        key = str(record.get("id") or record.get("doi") or record.get("title"))
        raw_combined[key] = record
        direct_keys.add(key)
    for record in name_records:
        key = str(record.get("id") or record.get("doi") or record.get("title"))
        raw_combined[key] = record

    # The OpenAIRE name filter is a candidate generator, not an authorship
    # assertion. Keep only records with target ORCID or an exact token-level
    # match to one supplied/inferred name variant.
    accepted_records: list[dict[str, Any]] = []
    rejected_candidates: list[dict[str, Any]] = []
    for key, record in raw_combined.items():
        status = authorship_status(record, orcid, names)
        direct_hit = key in direct_keys
        if direct_hit and status == "candidate":
            status = "confirmed_orcid_query"
        author = matching_author(record, orcid, names)
        annotated = dict(record)
        annotated["_authorship_status"] = status
        annotated["_matched_author"] = author
        annotated["_direct_orcid_retrieval"] = direct_hit
        if direct_hit or status in {"confirmed_orcid", "confirmed_orcid_query", "matched_name"}:
            accepted_records.append(annotated)
        else:
            rejected_candidates.append({
                "title": strip_html(record.get("title") or "Untitled dataset"),
                "doi": normalize_doi(record.get("doi") or record.get("pid")),
                "authors": normalize_authors(record.get("authors")),
                "repository": _repository(record)[0],
                "reason": "No author matched the ORCID or any supplied name variant after strict token-level validation.",
            })

    reconciled = deduplicate_dataset_records(accepted_records)
    datasets: list[dict[str, Any]] = []
    related_entities: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    citing_publications: list[dict[str, Any]] = []
    entity_ids: set[str] = set()

    for index, record in enumerate(reconciled, start=1):
        dataset_id = f"dataset_{index}"
        title = strip_html(record.get("title") or "Untitled dataset")
        description = strip_html(record.get("abstract") or record.get("description") or "")
        publication_date = str(record.get("publication_date") or "")
        doi = normalize_doi(record.get("doi"))
        repository, repositories = _repository(record)
        dataset = {
            "id": dataset_id,
            "display_id": f"D{index}",
            "doi": doi,
            "title": title,
            "year": int(publication_date[:4]) if publication_date[:4].isdigit() else None,
            "repository": repository,
            "repositories": repositories,
            "publisher": record.get("publisher"),
            "citations": int(record.get("citations") or 0),
            "direct_orcid_retrieval": bool(record.get("_direct_orcid_retrieval")),
            "authors": normalize_authors(record.get("authors")),
            "description": description,
            "authorship_status": record.get("_authorship_status") or authorship_status(record, orcid, names),
            "matched_author": record.get("_matched_author"),
            "member_record_count": int(record.get("member_record_count") or 1),
            "member_dois": record.get("member_dois") or [],
        }
        datasets.append(dataset)

        stripped_title = title_key(title)
        if title.lower().startswith("replication data") and stripped_title:
            try:
                candidates = provider.search_publications_by_title(stripped_title, page_size=5)
            except ProviderError as exc:
                warnings.append(f"Publication matching skipped for {doi or title}: {exc}")
                candidates = []
            if candidates:
                candidate = candidates[0]
                entity_id = stable_id("publication", str(candidate.get("doi") or candidate.get("title")))
                if entity_id not in entity_ids:
                    related_entities.append({
                        "id": entity_id, "type": "publication",
                        "title": strip_html(candidate.get("title") or stripped_title),
                        "pid": normalize_doi(candidate.get("doi")),
                    })
                    entity_ids.add(entity_id)
                relationships.append({
                    "source": dataset_id, "target": entity_id, "relation": "data_for_publication",
                    "status": "candidate", "evidence": "Replication-data title matched to an OpenAIRE publication candidate.",
                    "source_of_evidence": "OpenAIRE title matching",
                })

        resolved_for_dataset: dict[str, dict[str, Any]] = {}
        if lookup_citations and doi:
            try:
                links = provider.get_incoming_publication_links(doi)
            except ProviderError as exc:
                warnings.append(f"Incoming citation identities unavailable for {doi}: {exc}")
                links = []

            for link in links:
                source = _enrich_citing_publication(provider, _citation_source(link), warnings)
                key = str(source.get("doi") or source.get("identifier") or source.get("title") or "").strip()
                if not key:
                    continue
                provenance = ", ".join(source.get("provenance") or [])
                evidence_source = "OpenAIRE Graph API V3"
                if provenance:
                    evidence_source += f" · {provenance}"
                resolved_for_dataset[key.lower()] = source | {"evidence_source": evidence_source}

        for source in resolved_for_dataset.values():
            identifier = source.get("doi") or source.get("identifier") or source.get("title")
            citation_id = stable_id("citing_publication", f"{dataset_id}:{identifier}")
            year_text = str(source.get("publication_date") or "")
            citing_authors = normalize_authors(source.get("authors"))
            authorship_relation = classify_citation_authorship(
                dataset.get("authors"), citing_authors, orcid, names
            )
            citing_publications.append({
                "id": citation_id, "dataset_id": dataset_id,
                "dataset_display_id": dataset.get("display_id"),
                "title": strip_html(source.get("title") or "Untitled citing publication"),
                "doi": normalize_doi(source.get("doi")),
                "pid": source.get("identifier"),
                "year": int(year_text[:4]) if year_text[:4].isdigit() else None,
                "authors": citing_authors,
                "citation_authorship_type": authorship_relation.get("type"),
                "citation_authorship_label": authorship_relation.get("label"),
                "shared_authors": authorship_relation.get("shared_authors", []),
                "shared_author_details": authorship_relation.get("shared_author_details", []),
                "dataset_author_names": authorship_relation.get("dataset_author_names", []),
                "citing_author_names": authorship_relation.get("citing_author_names", []),
                "dataset_author_count": authorship_relation.get("dataset_author_count", 0),
                "citing_author_count": authorship_relation.get("citing_author_count", 0),
                "citation_authorship_evidence": authorship_relation.get("evidence"),
                "status": "confirmed", "evidence_source": source.get("evidence_source"),
            })
            relationships.append({
                "source": dataset_id, "target": citation_id, "relation": "cited_by_publication",
                "status": "confirmed",
                "evidence": "Incoming publication-to-dataset citation returned through OpenAIRE Graph API V3. "
                            + str(authorship_relation.get("evidence") or ""),
                "source_of_evidence": source.get("evidence_source"),
                "authorship_relation": authorship_relation.get("type"),
            })

        unresolved = max(0, dataset["citations"] - len(resolved_for_dataset))
        if unresolved > 0:
            relationships.append({
                "source": dataset_id, "target": f"unresolved_reuse_{dataset_id}", "relation": "cited_or_reused_by",
                "status": "unresolved",
                "evidence": f"The BIP! citation-count indicator is {dataset['citations']}, but {unresolved} indicator count(s) are not matched to identifiable incoming Graph API V3 publication relation(s).",
                "source_of_evidence": "OpenAIRE citation metric",
            })

    unique_citing_publications = {
        _publication_identity_key(publication)
        for publication in citing_publications
        if _publication_identity_key(publication)[1]
    }
    reconciled_citing_authors = _reconciled_citing_author_count(citing_publications)

    resolved_by_dataset: dict[str, int] = {}
    for publication in citing_publications:
        dataset_id = str(publication.get("dataset_id") or "")
        if dataset_id:
            resolved_by_dataset[dataset_id] = resolved_by_dataset.get(dataset_id, 0) + 1

    unresolved_citation_signals = sum(
        max(0, int(dataset.get("citations") or 0) - resolved_by_dataset.get(str(dataset.get("id")), 0))
        for dataset in datasets
    )
    datasets_with_unresolved_signals = sum(
        1
        for dataset in datasets
        if int(dataset.get("citations") or 0) > resolved_by_dataset.get(str(dataset.get("id")), 0)
    )

    citation_relation_counts = {
        key: sum(1 for publication in citing_publications if publication.get("citation_authorship_type") == key)
        for key in ("researcher_self_citation", "dataset_team_citation", "external_citation", "unresolved_authorship")
    }
    repositories = {dataset.get("repository") for dataset in datasets if dataset.get("repository")}
    orcid_confirmed = sum(
        1 for dataset in datasets
        if dataset.get("authorship_status") in {"confirmed_orcid", "confirmed_orcid_query"}
    )
    name_matched = sum(1 for dataset in datasets if dataset.get("authorship_status") == "matched_name")
    researcher_name = original_names[0] if original_names else (inferred_names[0] if inferred_names else "Researcher")
    data = {
        "researcher": {"name": researcher_name, "orcid": orcid},
        "summary": {
            "direct_orcid_datasets": len(direct_records),
            "direct_orcid_pages": direct_pages,
            "raw_name_records": len(name_records),
            "name_search_pages": name_search_pages,
            "raw_records": len(raw_combined),
            "validated_records": len(accepted_records),
            "rejected_records": len(rejected_candidates),
            "unique_datasets": len(datasets),
            "orcid_confirmed_datasets": orcid_confirmed,
            "name_matched_datasets": name_matched,
            "repositories": len(repositories),
            "bip_citation_count_total": sum(dataset["citations"] for dataset in datasets),
            "datasets_with_nonzero_bip_citation_count": sum(1 for dataset in datasets if dataset["citations"] > 0),
            "datasets_with_resolved_incoming_relations": len({
                str(publication.get("dataset_id"))
                for publication in citing_publications
                if publication.get("dataset_id")
            }),
            "resolved_citation_relations": len(citing_publications),
            "resolved_citing_publications": len(unique_citing_publications),
            "resolved_citing_authors": reconciled_citing_authors,
            "unresolved_citation_signals": unresolved_citation_signals,
            "datasets_with_unresolved_citation_signals": datasets_with_unresolved_signals,
            "researcher_self_citations": citation_relation_counts["researcher_self_citation"],
            "dataset_team_citations": citation_relation_counts["dataset_team_citation"],
            "external_citations": citation_relation_counts["external_citation"],
            "unresolved_authorship_relations": citation_relation_counts["unresolved_authorship"],
        },
        "datasets": datasets,
        "rejected_candidates": rejected_candidates,
        "name_variants_used": names,
        "citing_publications": citing_publications,
        "related_entities": related_entities,
        "relationships": relationships,
    }
    return data, warnings

def metric_cards(data: dict[str, Any]) -> None:
    summary = data["summary"]
    cards = [
        (summary.get("direct_orcid_datasets", 0), "dataset records retrieved across all ORCID-query pages", "red"),
        (summary.get("raw_name_records", 0), "candidate records recovered across paginated name searches", "orange"),
        (summary.get("rejected_records", 0), "broad name-search matches rejected after authorship validation", "red"),
        (summary.get("unique_datasets", len(data.get("datasets", []))), "dataset records retained after strict author matching and conservative reconciliation", "green"),
        (summary.get("repositories", 0), "repositories represented in the retained portfolio", "orange"),
        (summary.get("resolved_citing_publications", 0), "unique citing publications whose identity was resolved", "purple"),
    ]
    html = '<div class="metric-grid">' + "".join(
        f'<div class="metric-card {colour}"><div class="value">{value}</div><div class="label">{label}</div></div>'
        for value, label, colour in cards
    ) + "</div>"
    st.markdown(html, unsafe_allow_html=True)


def evidence_profile(data: dict[str, Any]) -> None:
    datasets = data.get("datasets", [])
    summary = data.get("summary", {})
    identified = sum(1 for dataset in datasets if dataset.get("doi"))
    unresolved_authorship = int(summary.get("unresolved_authorship_relations", 0) or 0)

    citation_authorship_finding = (
        f"{summary.get('researcher_self_citations', 0)} self · "
        f"{summary.get('dataset_team_citations', 0)} team · "
        f"{summary.get('external_citations', 0)} external"
    )
    if unresolved_authorship:
        citation_authorship_finding += f" · {unresolved_authorship} unresolved"

    cards = [
        (
            "Discoverability",
            f"{summary.get('direct_orcid_datasets', 0)} via ORCID + "
            f"{summary.get('name_matched_datasets', 0)} name-matched → "
            f"{summary.get('unique_datasets', len(datasets))} retained records",
            "Paginated ORCID retrieval is complemented with validated name matches, "
            "followed by conservative record reconciliation.",
        ),
        (
            "Identifiability",
            f"{identified} of {len(datasets)} retained records with DOI",
            "Persistent identifiers available for retained dataset-type records.",
        ),
        (
            "Authorship evidence",
            f"{summary.get('orcid_confirmed_datasets', 0)} ORCID-supported · "
            f"{summary.get('name_matched_datasets', 0)} name-matched",
            "ORCID-supported records are backed by an explicit ORCID match or the "
            "ORCID-filtered retrieval. Name-only matches remain distinguishable "
            "because homonyms cannot be fully excluded.",
        ),
        (
            "Repository coverage",
            f"{summary.get('repositories', 0)} repositories",
            "Repositories represented in this retained OpenAIRE portfolio; the search "
            "is not restricted to a specific repository.",
        ),
        (
            "Candidate rejection",
            f"{summary.get('rejected_records', 0)} broad name-search matches excluded",
            "Candidates returned by name searches are excluded when no author matches "
            "the target ORCID or an exact complete-name variant.",
        ),
        (
            "Citation visibility",
            f"{summary.get('datasets_with_resolved_incoming_relations', 0)} datasets with resolved incoming citation relations",
            "Retained dataset records for which OpenAIRE Graph API V3 exposes at least one identifiable "
            "incoming publication-to-dataset citation relation.",
        ),
        (
            "Reuse evidence",
            f"{summary.get('resolved_citation_relations', 0)} relations · "
            f"{summary.get('resolved_citing_publications', 0)} unique publications · "
            f"{summary.get('resolved_citing_authors', 0)} author identities",
            "Resolved dataset–publication citation relations, deduplicated citing "
            "publications and conservatively reconciled citing-author identities.",
        ),
        (
            "Citation authorship",
            citation_authorship_finding,
            "Each resolved dataset–publication citation relation is compared with the "
            "dataset creators using ORCID first and exact complete-name matching second.",
        ),
        (
            "Indicator–relation gap",
            f"{summary.get('unresolved_citation_signals', 0)} BIP! citation-count signals not matched to resolved relations",
            "Diagnostic difference between the citation-count indicator returned in OpenAIRE product metadata "
            "and identifiable incoming publication relations exposed by Graph API V3. "
            "The two layers are produced differently and need not be identical.",
        ),
    ]

    columns = st.columns(2)
    for index, (label, finding, description) in enumerate(cards):
        with columns[index % 2]:
            st.markdown(
                f'<div class="profile-card"><h4>{label}</h4><strong>{finding}</strong><p>{description}</p></div>',
                unsafe_allow_html=True,
            )


def render_credits() -> None:
    st.markdown(
        """
<div class="df-footer">
  <strong>Data Footprints · v1.0</strong><br>
  Concept and development: <strong>Anna Caellas-Camprubí</strong> · OpenAIRE AI Hackathon 2026
</div>
        """,
        unsafe_allow_html=True,
    )

def citing_table(data: dict[str, Any], dataset_id: str) -> None:
    rows = []
    for publication in data.get("citing_publications", []):
        if publication.get("dataset_id") != dataset_id:
            continue
        authors = "; ".join(author.get("name", "Unknown") for author in publication.get("authors", []))
        rows.append({
            "Citing publication": publication.get("title"),
            "DOI": publication.get("doi") or "Not available",
            "OpenAIRE ID": publication.get("pid") if not publication.get("doi") else None,
            "Year": publication.get("year"),
            "Authors": authors or "Authors not available",
            "Citation authorship classification": publication.get("citation_authorship_label") or "Authorship relation unresolved",
            "Dataset creators": "; ".join(publication.get("dataset_author_names", [])) or "Dataset creators not available",
            "Shared author(s)": "; ".join(publication.get("shared_authors", [])) or "None identified",
            "Dataset–publication author comparison": publication.get("citation_authorship_evidence"),
            "Evidence source": publication.get("evidence_source"),
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        dataset = next(item for item in data["datasets"] if item["id"] == dataset_id)
        if int(dataset.get("citations") or 0) > 0:
            st.warning("The BIP! citation-count indicator is non-zero for this dataset, but Graph API V3 did not return an identifiable incoming citing publication and its authors.")
        else:
            st.info("No citing publication is currently visible for this dataset in the OpenAIRE Graph.")


def dataset_table(data: dict[str, Any]) -> None:
    rows = []
    resolved_by_dataset: dict[str, int] = {}
    author_count_by_dataset: dict[str, int] = {}
    for publication in data.get("citing_publications", []):
        dataset_id = publication["dataset_id"]
        resolved_by_dataset[dataset_id] = resolved_by_dataset.get(dataset_id, 0) + 1
        author_count_by_dataset[dataset_id] = author_count_by_dataset.get(dataset_id, 0) + len(publication.get("authors", []))
    for index, dataset in enumerate(data.get("datasets", []), start=1):
        rows.append({
            "ID": dataset.get("display_id") or f"D{index}",
            "Dataset": dataset.get("title"), "DOI": dataset.get("doi"), "Year": dataset.get("year"),
            "Repository": dataset.get("repository"), "BIP! citation-count indicator": dataset.get("citations", 0),
            "Citing publications resolved": resolved_by_dataset.get(dataset["id"], 0),
            "Citing authors identified": author_count_by_dataset.get(dataset["id"], 0),
            "Authorship evidence": str(dataset.get("authorship_status") or "").replace("_", " "),
            "Matched author": (dataset.get("matched_author") or {}).get("name") if isinstance(dataset.get("matched_author"), dict) else None,
            "Direct ORCID retrieval": dataset.get("direct_orcid_retrieval", False),
            "Grouped records": dataset.get("member_record_count", 1),
        })
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def rejected_candidates_table(data: dict[str, Any]) -> None:
    rows = []
    for item in data.get("rejected_candidates", []):
        rows.append({
            "Candidate dataset": item.get("title"),
            "DOI": item.get("doi"),
            "Repository": item.get("repository"),
            "Authors returned by OpenAIRE": "; ".join(a.get("name", "Unknown") for a in item.get("authors", [])),
            "Reason excluded": item.get("reason"),
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.info("No candidate records were rejected in this retrieval.")


def relationship_table(data: dict[str, Any]) -> None:
    datasets = {dataset["id"]: dataset for dataset in data.get("datasets", [])}
    entities = {entity["id"]: entity for entity in data.get("related_entities", [])}
    citations = {item["id"]: item for item in data.get("citing_publications", [])}
    rows = []
    for relation in data.get("relationships", []):
        if relation.get("relation") in {"mentions_project", "produced_by_project", "funded_by"}:
            continue
        source = datasets.get(relation.get("source"), {})
        target_id = relation.get("target")
        if target_id in citations:
            target = citations[target_id].get("title")
        elif target_id in entities:
            target = entities[target_id].get("title")
        elif str(target_id).startswith("unresolved_reuse"):
            target = "Citing publication and authors unresolved"
        else:
            target = target_id
        rows.append({
            "Dataset ID": source.get("display_id") or relation.get("source"),
            "Dataset": source.get("title") or relation.get("source"), "Related object": target,
            "Relation": str(relation.get("relation") or "").replace("_", " "),
            "Status": relation.get("status"), "Evidence": relation.get("evidence"),
            "Source": relation.get("source_of_evidence"),
        })
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)



st.markdown(
    '<div class="build-intro"><h3>Build a data-value map</h3><p>Enter an ORCID to reconstruct the researcher’s dataset portfolio and follow visible citation and reuse relations across the OpenAIRE Graph.</p></div>',
    unsafe_allow_html=True,
)

with st.container(border=True):
    input_col, action_col = st.columns([4.5, 1.5])
    with input_col:
        orcid = st.text_input(
            "ORCID",
            placeholder="0000-0000-0000-0000",
            help="Use the ORCID of the researcher whose connected research-data contributions you want to explore.",
        )
    with action_col:
        button_label = "Connect and build map" if not oauth_state_exists() else "Build map"
        run_live = st.button(button_label, type="primary", width="stretch")

    with st.expander("Advanced options and connection", expanded=False):
        if oauth_state_exists():
            st.success("OpenAIRE/Alien login saved on this computer")
        else:
            st.info(
                "The first query may open the Alien login page in your browser. "
                "After authorizing, return to this application."
            )

        names_text = st.text_area(
            "Name variants (optional, one per line)",
            help="The app also tries to infer the researcher name from the direct Graph result or author profile.",
        )
        lookup_citations = st.checkbox("Resolve citing publications and authors", value=True)

        control_col1, control_col2 = st.columns(2)
        with control_col1:
            if st.button("Clear cached result", width="stretch"):
                st.cache_data.clear()
                st.session_state.pop("live_data", None)
                st.session_state.pop("live_warnings", None)
                st.rerun()
        with control_col2:
            if oauth_state_exists() and st.button("Clear saved login", width="stretch"):
                try:
                    clear_oauth_state()
                except ProviderError as exc:
                    st.error(str(exc))
                else:
                    st.cache_data.clear()
                    st.session_state.pop("live_data", None)
                    st.session_state.pop("live_warnings", None)
                    st.rerun()

warnings: list[str] = []
if run_live:
    if not validate_orcid(orcid):
        st.error("Enter an ORCID in the format 0000-0000-0000-0000.")
        render_credits()
        st.stop()
    names = tuple(line.strip() for line in names_text.splitlines() if line.strip())
    with st.spinner("Connecting to OpenAIRE and reconstructing incoming citation relations…"):
        try:
            data, warnings = build_live_data(orcid.strip(), names, lookup_citations)
        except ProviderError as exc:
            st.error(str(exc))
            render_credits()
            st.stop()
    st.session_state["live_data"] = data
    st.session_state["live_warnings"] = warnings
elif "live_data" in st.session_state:
    data = st.session_state["live_data"]
    warnings = st.session_state.get("live_warnings", [])
else:
    st.info("Enter an ORCID and select **Build map** to begin.")
    render_credits()
    st.stop()

st.markdown(f"**{data['researcher']['name']}** · `{data['researcher']['orcid']}`")
metric_cards(data)

if data.get("name_variants_used"):
    st.caption("Name variants queried: " + " · ".join(data["name_variants_used"]))

if warnings:
    with st.expander(f"Live retrieval notes ({len(warnings)})"):
        for warning in warnings:
            st.write(f"- {warning}")

if data.get("rejected_candidates"):
    with st.expander(f"Candidate records excluded after authorship validation ({len(data['rejected_candidates'])})"):
        st.caption("These records were returned by the Graph name search but are not attributed to the researcher in the main results.")
        rejected_candidates_table(data)

datasets = data.get("datasets", [])
if not datasets:
    st.warning(
        "No dataset passed strict authorship matching. The Graph may have returned broad name matches, "
        "but none contained the target ORCID or an author exactly matching a supplied name variant. "
        "Try adding the precise repository form of the researcher's name (for example, surname first)."
    )
    render_credits()
    st.stop()

st.markdown(
    '<div class="panel-title"><h3>Research data value map</h3><p>One interactive graph for the researcher: the researcher is connected to the full dataset portfolio; each dataset is connected to the publications that cite it and to the authors of those publications. Authors who also created the cited dataset are highlighted, making self-citation and team-citation patterns visible.</p></div>',
    unsafe_allow_html=True,
)
with st.expander("Graph display controls", expanded=False):
    graph_col1, graph_col2, graph_col3 = st.columns(3)
    with graph_col1:
        show_citing_publications = st.checkbox("Show citing publications", value=True)
        show_citing_authors = st.checkbox("Show authors of citing publications and overlaps", value=True, disabled=not show_citing_publications)
    with graph_col2:
        show_unresolved = st.checkbox("Show indicator–relation gaps", value=True)
        show_repositories = st.checkbox("Show repository nodes", value=False, help="Repositories remain visible in dataset tooltips and tables even when their nodes are hidden.")
    with graph_col3:
        compact_labels = st.checkbox("Use compact node labels", value=False, help="D = dataset, P = citing publication, A = citing author. Full details appear on hover.")
        enable_physics = st.checkbox("Enable automatic physics layout", value=True, help="The graph separates nodes automatically, then freezes. Every node remains draggable.")

network_html = build_researcher_network_html(
    data,
    show_citing_publications=show_citing_publications,
    show_citing_authors=show_citing_authors and show_citing_publications,
    show_unresolved=show_unresolved,
    show_repositories=show_repositories,
    compact_labels=compact_labels,
    enable_physics=enable_physics,
    pin_researcher=True,
)
st.iframe(network_html, height=900, width="stretch")

st.markdown(
    '<div class="panel-title"><h3>Inspect citing publications and authors</h3><p>Select a dataset to inspect its incoming citations. The selection changes only this table; the graph above always represents the full researcher portfolio.</p></div>',
    unsafe_allow_html=True,
)
resolved_relation_counts: dict[str, int] = {}
for publication in data.get("citing_publications", []):
    dataset_id = str(publication.get("dataset_id") or "")
    if dataset_id:
        resolved_relation_counts[dataset_id] = resolved_relation_counts.get(dataset_id, 0) + 1

citation_first = sorted(
    datasets,
    key=lambda item: (
        resolved_relation_counts.get(str(item.get("id")), 0),
        int(item.get("citations") or 0),
        item.get("year") or 0,
    ),
    reverse=True,
)
default_id = citation_first[0]["id"]
options = {
    f"{dataset.get('display_id') or f'D{index}'} · {dataset.get('title')} · {dataset.get('repository')}": dataset["id"]
    for index, dataset in enumerate(datasets, start=1)
}
default_label = next(label for label, identifier in options.items() if identifier == default_id)
selected_label = st.selectbox("Dataset to inspect", list(options), index=list(options).index(default_label))
selected_id = options[selected_label]
citing_table(data, selected_id)

st.markdown(
    '<div class="panel-title"><h3>Evidence of research data value</h3><p>Evidence coverage for this retrieval, not a score of the dataset or researcher.</p></div>',
    unsafe_allow_html=True,
)
evidence_profile(data)

st.markdown(
    '<div class="panel-title"><h3>Dataset portfolio across OpenAIRE</h3><p>Dataset-type records are retrieved from the whole Graph, regardless of repository, retained only after strict author matching, and reconciled conservatively where metadata supports grouping.</p></div>',
    unsafe_allow_html=True,
)
dataset_table(data)

st.markdown(
    '<div class="panel-title"><h3>Relationships and evidence</h3><p>Resolved citing publications, their authors and indicator–relation gaps remain inspectable.</p></div>',
    unsafe_allow_html=True,
)
relationship_table(data)

with st.expander("Methodology and reuse"):
    st.markdown(
        """
1. Search all available OpenAIRE dataset-result pages using the ORCID.
2. Infer and apply name variants and paginate those searches to recover candidate records missed by the identifier query.
3. Validate name-search candidates against the returned authors and search the whole OpenAIRE Graph without restricting the repository.
4. Reconcile file-level and version-level records conservatively when metadata supports grouping; retain ambiguous records.
5. For every retained dataset record with a DOI, query OpenAIRE Graph API V3 `/research-products/links` using `targetPid`, `relation=Cites`, `sourceType=publication`, zero-based `page` and `pageSize=100`.
6. Retrieve the citing publication DOI, metadata and authors from the Graph V3 relation and enrich incomplete records conservatively when needed.
7. Keep dataset–publication citation relations distinct from counts of unique citing publications and reconciled citing-author identities.
8. Compare the complete citing-publication author list with the complete dataset-creator list. Classify each relation as researcher self-citation, dataset-team citation, external citation or unresolved authorship; shared people are highlighted in the graph.
9. Compare the BIP! citation-count indicator in OpenAIRE product metadata with identifiable incoming publication relations from Graph API V3, and expose any unmatched indicator counts as a diagnostic gap.
10. Treat all displayed measures as evidence coverage for the retrieval, not as a score or as proof of exhaustive citation coverage.
        """
    )
    st.download_button(
        "Download reconciled JSON", data=json.dumps(data, ensure_ascii=False, indent=2),
        file_name=f"data_footprints_{data['researcher']['orcid']}.json", mime="application/json",
    )

render_credits()
