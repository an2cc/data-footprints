# SPDX-FileCopyrightText: 2026 Anna Caellas-Camprubí
# SPDX-License-Identifier: EUPL-1.2

"""Normalization, authorship validation and dataset reconciliation helpers."""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from urllib.parse import unquote
from collections import Counter
from typing import Any

DOI_PREFIX = re.compile(r"^https?://(?:dx\.)?doi\.org/", flags=re.IGNORECASE)
FILE_SUFFIX = re.compile(r"^(10\.34810/data\d+)/(\d+)$", flags=re.IGNORECASE)
VERSION_SUFFIX = re.compile(r"^(10\.\d{4,9}/.+?)\.v\d+$", flags=re.IGNORECASE)
MENDELEY_VERSION_SUFFIX = re.compile(r"^(10\.17632/[^.]+)\.\d+$", flags=re.IGNORECASE)
HTML_TAG = re.compile(r"<[^>]+>")
DOI_VALUE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", flags=re.IGNORECASE)


def normalize_doi(value: str | None) -> str | None:
    """Return a real DOI, never an OpenAIRE internal identifier.

    OpenAIRE relationship records may expose identifiers such as
    ``50|doi_dedup___::...``.  Those values are useful as internal PIDs but
    must not be displayed in a field labelled DOI.  This function therefore
    extracts only strings that match the DOI syntax.
    """
    if not value:
        return None
    text = html.unescape(unquote(str(value))).strip()
    text = DOI_PREFIX.sub("", text)
    match = DOI_VALUE.search(text)
    if not match:
        return None
    cleaned = match.group(0).rstrip(".,;:)]}>")
    return cleaned.lower() or None


def parent_pid(doi: str | None) -> str | None:
    doi = normalize_doi(doi)
    if not doi:
        return None
    file_match = FILE_SUFFIX.match(doi)
    if file_match:
        return file_match.group(1)
    version_match = VERSION_SUFFIX.match(doi)
    if version_match:
        return version_match.group(1)
    mendeley_match = MENDELEY_VERSION_SUFFIX.match(doi)
    if mendeley_match:
        return mendeley_match.group(1)
    return doi


def strip_html(value: Any) -> str:
    """Return readable plain text for tooltips, tables and labels."""
    text = html.unescape("" if value is None else str(value))
    text = HTML_TAG.sub(" ", text)
    return " ".join(text.split())


def normalize_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-zA-Z0-9]+", " ", ascii_text).lower().split())


def _name_tokens(value: str) -> tuple[str, ...]:
    return tuple(normalize_name(value).split())


def names_match(author_name: str, target_name: str) -> bool:
    """Strict order-insensitive match that accepts 'Surname, Given' forms.

    The Graph's authorFullName filter is broad and can return records where the
    query terms occur across different authors or name components.  We therefore
    only accept a name-based record when one author has exactly the same token
    multiset as one supplied variant.  This accepts e.g. ``Marco A Perez`` and
    ``Perez, Marco A`` but rejects ``Leyva, Marco A`` and unrelated long lists.
    """
    author_tokens = _name_tokens(author_name)
    target_tokens = _name_tokens(target_name)
    if not author_tokens or not target_tokens:
        return False
    return Counter(author_tokens) == Counter(target_tokens)



def expand_name_variants(names: list[str] | tuple[str, ...] | set[str]) -> list[str]:
    """Add safe comma/non-comma order variants without inventing initials."""
    expanded: set[str] = set()
    for raw in names:
        name = strip_html(raw).strip()
        if not name:
            continue
        expanded.add(name)
        if "," in name:
            family, given = (part.strip() for part in name.split(",", 1))
            if family and given:
                expanded.add(f"{given} {family}")
        else:
            parts = name.split()
            if len(parts) >= 2:
                expanded.add(f"{parts[-1]}, {' '.join(parts[:-1])}")
    return sorted(expanded)

def title_key(value: str) -> str:
    text = normalize_name(strip_html(value))
    for prefix in ("replication data for", "replication data", "data for", "dataset for"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    return text


def stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{digest}"


def deduplicate_dataset_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reconcile records using a parent PID where available, with normalized title as a fallback."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        doi = normalize_doi(record.get("doi") or record.get("pid"))
        key = parent_pid(doi) or f"title:{title_key(str(record.get('title') or 'untitled'))}"
        groups.setdefault(key, []).append(record)

    reconciled: list[dict[str, Any]] = []
    for key, members in groups.items():
        parent_member = next(
            (
                member for member in members
                if parent_pid(normalize_doi(member.get("doi"))) == normalize_doi(member.get("doi"))
            ),
            members[0],
        )
        result = dict(parent_member)
        result["doi"] = None if key.startswith("title:") else key
        result["member_record_count"] = len(members)
        result["member_dois"] = sorted(
            doi for doi in (normalize_doi(member.get("doi")) for member in members) if doi
        )

        # Preserve the strongest authorship evidence found in any grouped
        # file/version record.  This matters when, for example, a version has
        # the ORCID but the parent record only has the name.
        status_rank = {
            "candidate": 0,
            "matched_name": 1,
            "confirmed_orcid_query": 2,
            "confirmed_orcid": 3,
        }
        strongest = max(
            members,
            key=lambda member: status_rank.get(str(member.get("_authorship_status") or "candidate"), 0),
        )
        result["_authorship_status"] = strongest.get("_authorship_status") or "candidate"
        result["_matched_author"] = strongest.get("_matched_author")
        result["_direct_orcid_retrieval"] = any(bool(member.get("_direct_orcid_retrieval")) for member in members)
        result["id"] = str(result.get("id") or stable_id("dataset", key))
        reconciled.append(result)

    return sorted(
        reconciled,
        key=lambda item: (str(item.get("publication_date") or ""), strip_html(item.get("title"))),
        reverse=True,
    )


def authorship_status(record: dict[str, Any], target_orcid: str, target_names: list[str]) -> str:
    authors = normalize_authors(record.get("authors"))
    target_orcid = target_orcid.lower().strip()
    for author in authors:
        if str(author.get("orcid") or "").lower().strip() == target_orcid:
            return "confirmed_orcid"
    for author in authors:
        author_name = str(author.get("name") or "")
        if any(names_match(author_name, target) for target in target_names if target.strip()):
            return "matched_name"
    return "candidate"


def matching_author(record: dict[str, Any], target_orcid: str, target_names: list[str]) -> dict[str, str | None] | None:
    """Return the author responsible for accepting the record, if any."""
    authors = normalize_authors(record.get("authors"))
    target_orcid = target_orcid.lower().strip()
    for author in authors:
        if str(author.get("orcid") or "").lower().strip() == target_orcid:
            return author
    for author in authors:
        author_name = str(author.get("name") or "")
        if any(names_match(author_name, target) for target in target_names if target.strip()):
            return author
    return None


def normalize_authors(value: Any) -> list[dict[str, str | None]]:
    if not value:
        return []
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return [{"name": strip_html(value), "orcid": None}]

    authors: list[dict[str, str | None]] = []
    seen: set[tuple[str, str | None]] = set()
    for item in value:
        if isinstance(item, str):
            name, orcid = item, None
        elif isinstance(item, dict):
            name = str(
                item.get("name") or item.get("full_name") or item.get("fullName")
                or item.get("creatorName") or item.get("author") or "Unknown author"
            )
            orcid = item.get("orcid") or item.get("ORCID") or item.get("pid")
        else:
            name, orcid = str(item), None
        cleaned_name = strip_html(name) or "Unknown author"
        key = (cleaned_name, str(orcid).strip() if orcid else None)
        if key not in seen:
            seen.add(key)
            authors.append({"name": key[0], "orcid": key[1]})
    return authors

def _usable_authors(value: Any) -> list[dict[str, str | None]]:
    return [
        author for author in normalize_authors(value)
        if normalize_name(str(author.get("name") or "")) not in {"", "unknown author", "unknown"}
    ]


def _author_match_evidence(
    left: dict[str, str | None],
    right: dict[str, str | None],
) -> str | None:
    left_orcid = str(left.get("orcid") or "").lower().strip()
    right_orcid = str(right.get("orcid") or "").lower().strip()
    if left_orcid and right_orcid and left_orcid == right_orcid:
        return "ORCID"
    left_name = str(left.get("name") or "")
    right_name = str(right.get("name") or "")
    if left_name and right_name and names_match(left_name, right_name):
        return "full name"
    return None


def classify_citation_authorship(
    dataset_authors: Any,
    citing_authors: Any,
    target_orcid: str,
    target_names: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    """Classify the authorship relationship behind a dataset citation.

    The complete creator list of the cited dataset is always compared with the
    complete author list of the citing publication before the primary relation
    type is assigned. This preserves all shared authors even when the central
    researcher is also present and the relation is therefore classified as a
    researcher self-citation.

    Matching is deliberately conservative: ORCID is preferred, exact complete
    name matching is accepted as weaker evidence, and incomplete metadata stays
    unresolved rather than being labelled external.
    """
    dataset_people = _usable_authors(dataset_authors)
    citing_people = _usable_authors(citing_authors)
    dataset_names = [str(person.get("name") or "Unknown") for person in dataset_people]
    citing_names = [str(person.get("name") or "Unknown") for person in citing_people]

    base = {
        "dataset_author_count": len(dataset_people),
        "citing_author_count": len(citing_people),
        "dataset_author_names": dataset_names,
        "citing_author_names": citing_names,
        "shared_author_details": [],
    }

    if not dataset_people or not citing_people:
        missing = []
        if not dataset_people:
            missing.append("dataset creators")
        if not citing_people:
            missing.append("citing-publication authors")
        return base | {
            "type": "unresolved_authorship",
            "label": "Authorship relation unresolved",
            "shared_authors": [],
            "evidence": "Could not compare authorship because " + " and ".join(missing) + " are unavailable.",
        }

    target_orcid_norm = str(target_orcid or "").lower().strip()
    target_name_values = [str(name) for name in target_names if str(name).strip()]

    # First compare the complete author lists so that all overlaps are retained,
    # even when the central researcher is one of them.
    shared: list[str] = []
    shared_details: list[dict[str, Any]] = []
    evidence_types: set[str] = set()
    seen_people: set[tuple[str, str]] = set()

    for dataset_author in dataset_people:
        for citing_author in citing_people:
            evidence = _author_match_evidence(dataset_author, citing_author)
            if not evidence:
                continue

            citing_name = str(citing_author.get("name") or dataset_author.get("name") or "Shared author")
            dataset_name = str(dataset_author.get("name") or citing_name)
            person_key = (
                str(citing_author.get("orcid") or dataset_author.get("orcid") or "").lower().strip(),
                normalize_name(citing_name),
            )
            if person_key in seen_people:
                continue
            seen_people.add(person_key)

            if citing_name not in shared:
                shared.append(citing_name)
            evidence_types.add(evidence)

            dataset_orcid = str(dataset_author.get("orcid") or "").lower().strip()
            citing_orcid = str(citing_author.get("orcid") or "").lower().strip()
            is_central = bool(
                (target_orcid_norm and (dataset_orcid == target_orcid_norm or citing_orcid == target_orcid_norm))
                or any(names_match(dataset_name, target_name) for target_name in target_name_values)
                or any(names_match(citing_name, target_name) for target_name in target_name_values)
            )

            shared_details.append({
                "citing_name": citing_name,
                "citing_orcid": citing_author.get("orcid"),
                "dataset_name": dataset_name,
                "dataset_orcid": dataset_author.get("orcid"),
                "evidence": evidence,
                "role": "central_researcher" if is_central else "dataset_team_member",
            })

    # Then determine whether the central researcher authored the citing output.
    central_match: dict[str, Any] | None = None
    for author in citing_people:
        author_orcid = str(author.get("orcid") or "").lower().strip()
        author_name = str(author.get("name") or "")
        if target_orcid_norm and author_orcid and author_orcid == target_orcid_norm:
            central_match = {"name": author_name, "evidence": "ORCID", "probable": False}
            break
        if any(names_match(author_name, target_name) for target_name in target_name_values):
            central_match = {"name": author_name, "evidence": "exact complete name", "probable": True}
            break

    if central_match:
        if central_match["probable"]:
            label = "Probable researcher self-citation"
            first_sentence = (
                "The central researcher is an author of the citing publication, matched by exact complete name; "
                "homonyms cannot be fully excluded."
            )
        else:
            label = "Researcher self-citation"
            first_sentence = "The central researcher is an author of the citing publication, matched by ORCID."

        overlap_sentence = (
            f" Across the complete author lists, {len(shared)} citing author(s) also match creators of the cited dataset."
            if shared
            else " No additional creator overlap could be established from the available author metadata."
        )
        return base | {
            "type": "researcher_self_citation",
            "label": label,
            "shared_authors": shared,
            "shared_author_details": shared_details,
            "evidence": first_sentence + overlap_sentence,
        }

    if shared:
        evidence_label = " and ".join(sorted(evidence_types))
        return base | {
            "type": "dataset_team_citation",
            "label": "Dataset-team citation",
            "shared_authors": shared,
            "shared_author_details": shared_details,
            "evidence": f"{len(shared)} author(s) occur in both the cited dataset and the citing publication, matched by {evidence_label}.",
        }

    return base | {
        "type": "external_citation",
        "label": "External citation",
        "shared_authors": [],
        "shared_author_details": [],
        "evidence": (
            f"Compared {len(citing_people)} citing-publication author(s) with "
            f"{len(dataset_people)} dataset creator(s); no shared person was identified "
            "by ORCID or exact complete-name matching."
        ),
    }
