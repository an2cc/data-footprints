# Data Footprints

**Tracing dataset citation pathways for responsible research assessment**

> **What story do your research data tell?**  
> Discover your datasets across the OpenAIRE Graph, trace the publications that cite them, and uncover signals of how your data travel within and beyond your research team.

**Version 1.0 — OpenAIRE AI Hackathon 2026**

Data Footprints is a reusable analytical workflow and interactive Streamlit application that starts from a researcher ORCID and reconstructs an evidence map around research datasets. It uses the OpenAIRE MCP connector powered by Alien Intelligence for dataset discovery and OpenAIRE Graph API V3 for incoming publication-to-dataset citation relations.

The result is not a research score. It is a transparent evidence layer designed to make research-data contributions more inspectable, traceable and reusable for responsible research assessment.

## Why this artifact

Research assessment increasingly asks institutions and researchers to recognise a wider range of contributions, including research data. Yet a dataset citation count alone tells us little about what happened behind that citation.

Was the dataset cited by the researcher who created it? By another member of the data-producing team? Or by authors with no detected overlap with the original creators? Can the underlying relationship actually be inspected and verified?

Data Footprints follows the identifiers, records, relationships and people behind dataset citations so that these pathways can be interpreted in context rather than collapsed into a single metric.

## What it does

Starting from an ORCID, the application:

1. retrieves dataset-type records across all available pages of the OpenAIRE search;
2. complements ORCID retrieval with searches across researcher name variants;
3. validates name-search candidates against the authors returned by OpenAIRE;
4. applies conservative record reconciliation where the metadata supports it, while retaining records that cannot be safely merged;
5. queries incoming publication-to-dataset citation relations through OpenAIRE Graph API V3;
6. retrieves or enriches citing-publication metadata and authors;
7. compares the complete creator list of the cited dataset with the complete author list of the citing publication;
8. distinguishes researcher self-citations, dataset-team citations, external citations and unresolved authorship;
9. visualizes the resulting researcher → dataset → citing publication → citing author network;
10. exposes the evidence behind each relation in tables, tooltips and an evidence profile.

Data Footprints does not assume that every OpenAIRE dataset-type record represents one distinct conceptual dataset. OpenAIRE can expose research data at different levels of granularity, including datasets, versions, components or individual files. The application reconciles records conservatively and keeps ambiguous cases visible.

## Reading the map

The graph uses a deliberately simple visual language:

- **Yellow** — researcher identified by the searched ORCID.
- **Green** — retained OpenAIRE dataset-type record.
- **Blue** — publication that cites the dataset.
- **Orange** — author of a citing publication, with no identified overlap with the creators of that cited dataset.
- **Pink** — author of a citing publication who is also a creator of the cited dataset.
- **Red** — a BIP! citation-count indicator value that is not matched by an identifiable incoming publication relation in the current Graph API V3 retrieval.

A direct researcher-to-publication link indicates that the searched researcher is also an author of the citing publication.

The map is intended to make complex relationships understandable at a glance. For dense researcher profiles, the dataset portfolio, relation-level tables and evidence profile provide more detailed inspection than the global network view alone.

## Evidence profile

The evidence panel reports **coverage of the current retrieval, not a quality or performance score**.

### Discoverability

Shows how many records are retrieved through paginated ORCID queries, how many additional records are retained through validated name matching, and the resulting retained portfolio after conservative reconciliation.

### Authorship evidence

Separates **ORCID-supported** records from **name-matched** records. ORCID is the strongest identity signal. Exact complete-name matching is used as weaker fallback evidence when an ORCID is unavailable.

### Candidate rejection

Counts broad name-search candidates excluded because the returned authors do not support the target ORCID or an exact validated name variant.

### Identifiability

Reports DOI availability among the retained dataset-type records.

### Repository coverage

Counts the repositories represented in the retained OpenAIRE portfolio. Discovery is not restricted to a specific repository.

### Citation visibility

Counts retained records for which OpenAIRE Graph API V3 exposes at least one identifiable incoming publication-to-dataset citation relation.

### Reuse evidence

Distinguishes three related but different quantities:

- resolved **dataset–publication citation relations**;
- **unique citing publications** after publication deduplication;
- reconciled **citing-author identities**.

These are evidence of citation pathways. They should not automatically be interpreted as demonstrated substantive data reuse.

### Citation authorship

Each resolved dataset–publication citation relation is classified by comparing the complete dataset-creator list with the complete citing-publication author list:

- **Researcher self-citation** — the researcher identified by the searched ORCID is also an author of the citing publication.
- **Dataset-team citation** — the focal researcher is not an author of the citing publication, but at least one other dataset creator is.
- **External citation** — no shared person is identified between dataset creators and citing-publication authors.
- **Unresolved authorship** — the available metadata is insufficient for a reliable comparison.

ORCID is used first. Conservative exact-name matching is used as fallback evidence.

### Indicator–relation gap

Data Footprints keeps the product-level **BIP! citation-count indicator** separate from the incoming publication relations resolved through Graph API V3.

The two evidence layers can diverge. A non-zero gap is therefore surfaced as a diagnostic difference rather than silently converted into a single citation value.

A zero gap does not imply exhaustive citation coverage outside the evidence currently available through OpenAIRE.

## Analytical workflow

1. Start from a researcher ORCID.
2. Retrieve all available OpenAIRE dataset-result pages through the Alien Intelligence MCP connector.
3. Run supplementary searches across name variants and validate the returned candidates.
4. Apply conservative reconciliation where records can be safely associated; retain ambiguous records.
5. For every retained record with a DOI, query OpenAIRE Graph API V3 `/research-products/links` using `targetPid=<dataset DOI>`, `relation=Cites`, `sourceType=publication`, `page` and `pageSize`.
6. Retrieve and, when needed, enrich citing-publication metadata and authors.
7. Compare the complete dataset-creator list with the complete citing-publication author list.
8. Classify each relation as researcher self-citation, dataset-team citation, external citation or unresolved authorship.
9. Keep calculated BIP! citation-count indicators separate from explicit Graph relations.
10. Present the reconstructed evidence through the interactive map, portfolio, tables and evidence profile.

## Data sources and infrastructure

Data Footprints uses:

- **OpenAIRE Graph** for research-product metadata;
- **OpenAIRE Graph API V3** for incoming publication-to-dataset relations;
- the **OpenAIRE MCP connector powered by Alien Intelligence** for researcher-level dataset discovery and enrichment;
- **ORCID** supplied by the user as the researcher identity anchor.

No separate commercial bibliometric database is required to build the map.

Relationship provenance returned by OpenAIRE may include upstream research-information sources. Data Footprints keeps the evidence exposed by OpenAIRE inspectable rather than treating a calculated indicator as a substitute for the underlying relationship.

## Quick start

### Windows

1. Download or clone this repository.
2. Double-click `run_app.bat`.
3. On first launch, allow the script to create the local Python environment and install the documented dependencies.
4. Wait for the browser to open at `http://localhost:8501`.
5. Sign in to **Alien Intelligence** when the OpenAIRE MCP authorization flow is requested.
6. Enter a researcher ORCID.
7. Click **Build map**.

### Test ORCIDs

Two test cases are provided because researcher-level networks can differ substantially in size and structure:

- `0000-0001-9815-6190` — a relatively compact dataset-citation network.
- `0009-0005-4979-9778` — a much more highly connected citation network.

These examples allow evaluators and reusers to test different behaviours of the application without first having to identify suitable researcher profiles.

> **Access requirement:** Data Footprints requires an Alien Intelligence account with access to the OpenAIRE MCP connector. No API key needs to be entered manually in the application.

## Platform compatibility

Data Footprints is a **cross-platform Python/Streamlit application**. It is not Windows-dependent.

- **Windows:** `run_app.bat` — tested during development.
- **macOS / Linux:** `run_app.sh` — provided for equivalent environment setup and launch, but not yet tested directly by the author on those platforms.

The platform-specific launchers are convenience scripts only. The application itself runs through Python and Streamlit.

## Installation and environment requirements

### Requirements

- **Python 3.10 or later**
- **Streamlit 1.56 or later**
- internet connection
- an **Alien Intelligence account with access to the OpenAIRE MCP connector**

The remaining Python dependencies are listed in `requirements.txt`.

### Windows

Tested during development:

```powershell
run_app.bat
```

### macOS / Linux

Cross-platform launcher provided; not yet tested directly by the author:

```bash
chmod +x run_app.sh
./run_app.sh
```

On first launch, the platform launcher creates a local `.venv`, installs the dependencies from `requirements.txt`, and starts Streamlit.

The repository deliberately **does not include `.venv`**. Virtual environments contain platform-specific, regenerable files and are created locally from the documented dependencies. The repository also excludes caches and authentication credentials.

### Authentication

The first live query may open the Alien Intelligence authorization flow in the browser. OAuth credentials are stored under the current user's home directory, outside the artifact folder, and are **not included in the distributed repository**. Each evaluator or reuser must authenticate with their own eligible Alien Intelligence account.

## Using the application

1. Enter an ORCID in the form `0000-0000-0000-0000`.
2. Add exact name variants only when useful.
3. Keep **Resolve citing publications and authors** enabled to reconstruct incoming citation relations.
4. Select **Build map**.
5. Authorize the OpenAIRE / Alien Intelligence connection if the browser authentication flow appears.
6. Inspect the graph, dataset portfolio, citation tables and evidence profile.
7. Use the JSON download if you want to retain the reconstructed evidence for further analysis.

## Reproducibility

Data Footprints is designed so that another user can repeat the **same documented analytical workflow** with a different researcher ORCID.

Because OpenAIRE is a living graph, exact record counts, metadata and relationships may change as the infrastructure is updated. Reproducibility therefore means repeating the same method and inspecting the evidence available at query time, rather than reproducing a permanently fixed historical snapshot.

The two test ORCIDs above provide documented examples with substantially different network sizes. They are intended as reproducibility checks, not as fixed benchmark datasets.

## Interpretation cautions

The artifact is deliberately conservative.

- A **dataset citation is not automatically evidence of substantive data reuse**.
- An **external citation** means that no shared creator/author was identified; it does not by itself prove independent reuse.
- A **name match** is weaker identity evidence than an ORCID match.
- A retained green node is an **OpenAIRE dataset-type record**, not necessarily one unique conceptual dataset.
- Record granularity can vary across repositories and sources.
- OpenAIRE coverage and metadata quality can vary.
- Missing ORCIDs or incomplete author lists can limit authorship classification.
- Citation relations can appear, disappear or be enriched as the Graph evolves.
- A zero indicator–relation gap does not mean that every real-world citation is represented in OpenAIRE.
- Large citation networks may be easier to inspect through the portfolio and relation tables than through the global graph alone.

## Reuse

Another user can take the public GitHub repository, run the application with their own eligible Alien Intelligence account, enter any researcher ORCID, and reproduce the same workflow: dataset discovery, conservative authorship validation, record reconciliation, incoming citation retrieval, author-overlap classification and interactive inspection.

Beyond the interface, the reusable contribution is the method:

- use persistent identifiers as anchors;
- distinguish discovery from validation;
- remain aware of the difference between dataset-type records and conceptual datasets;
- separate calculated indicators from explicit Graph relations;
- compare complete dataset-creator and publication-author lists;
- preserve uncertainty instead of forcing every case into a score.

The resulting evidence can complement **narrative CVs, contribution statements and responsible research assessment dossiers** by showing not only that datasets exist or have been cited, but how citation pathways connect datasets, publications and people.

Data Footprints can also help identify **gaps in research information**. Following records, identifiers and relationships through the Graph can reveal weaknesses in how research data are described, connected or propagated across infrastructures. These observations can inform better dataset citation practices and support improvements in repository metadata, authorship identification and the recording of dataset–publication relationships.

Data Footprints is not intended to produce a score. It helps users see what evidence is available, how it is connected, and where gaps remain.

## Project files

The clean release contains:

```text
data_footprints_v1_0/
├── .gitignore
├── .streamlit/
│   └── config.toml
├── images/
│   ├── analytical-workflow.png
│   ├── citation-pathway-closeup.png
│   ├── demonstration-network.png
│   ├── indicator-relation-gap.png
│   └── workflow-evolution.png
├── app.py
├── providers.py
├── reconciliation.py
├── visuals.py
├── requirements.txt
├── run_app.bat
├── run_app.sh
├── STORY.md
├── LICENSE
├── LICENSE-DOCUMENTATION.md
└── README.md
```

Runtime-generated folders such as `.venv` and `__pycache__` are deliberately excluded from the release.

## Licensing

Data Footprints separates the software licence from the licence for written and media materials:

- **Software code:** EUPL-1.2 (`SPDX-License-Identifier: EUPL-1.2`)
- **Documentation and original media:** CC BY 4.0 (`SPDX-License-Identifier: CC-BY-4.0`)

**Attribution:** © 2026 Anna Caellas-Camprubí.

See `LICENSE` and `LICENSE-DOCUMENTATION.md` for the repository notices.

Third-party research information, identifiers, names, trademarks and other source content retain their respective provenance, rights and applicable terms.



## Credits

**Concept and development:** Anna Caellas-Camprubí  

**Scientific supervision / Methodological advice:**  
- Ignasi Labastida  
- Juan-José Boté-Vericad  

**Context:** OpenAIRE AI Hackathon 2026

## Version

**1.0 — Hackathon release**
