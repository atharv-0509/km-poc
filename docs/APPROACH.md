# Knowledge Management PoC — Approach Plan

**Minister's Office · Proof of Concept · Prepared by Atharv & Ahaan**

**Design principle: Retrieval-first, not generation-first.** The system finds
and ranks the right records using local, self-hosted search — no paid LLM and
near-zero token cost per query. A language model is used only as an optional
final step to phrase a short answer, and can be switched off entirely.

## 1. Problem, in one line
Information in the office is scattered across formats (minutes, decks, reports,
trackers, scans), is multilingual (English, Marathi, Hindi — often mixed in one
file), and some exists only as scanned images. Anyone should be able to ask a
plain-language question and get the correct records back, with trustworthy
sources, regardless of where the data lives or its language.

## 2. What the sample files confirmed
- **Multilingual & mixed:** the Announcements tracker is entirely Marathi; the
  VIP Letters file mixes English, Marathi and Hindi row-by-row.
- **Messy human-built structure:** headers sit on row 2 or 3 (not row 1), merged
  title cells, duplicate column names, and near-duplicate sheets. Naive parsing
  fails.
- **A ready-made taxonomy:** the deck lists 12 categories (CM Meetings,
  Announcements, Cabinet Decisions, War Room, 100/150 Days, CEGIS, SAMAGRA,
  Databases, Conferences, Key Districts, PS Meetings) — reuse these as the
  top-level metadata vocabulary.

## 3. Hosting decision (confirmed with reviewer)
Host: Google Cloud, India region (Mumbai `asia-south1` / Delhi `asia-south2`)
so all record data physically stays in-country. Open-weight embedding and
language models run self-hosted inside our own GCP project (GPU VMs / GKE) — not
via external embedding or LLM APIs — so record text never leaves the controlled
environment and per-query token cost stays zero. Vector DB (Qdrant / pgvector)
sits in the same project and region. Because the models are open-weight and
portable, the design is identical on any approved environment; only the
deployment target changes.

## 4. Why LLM / token usage stays near zero

| Task | How it's done — and its token cost |
|---|---|
| Semantic search | Local open-weight embedding model. Runs on our hardware; no per-token billing. This is the engine of the whole system. |
| Exact matches | Keyword index (outward no., date, name). No model involved at all. |
| Tagging / metadata | Rule-based: date parsing, regex, department lookup from a fixed list. No LLM per record. |
| OCR for scans | Local OCR (Tesseract with Marathi/Hindi/English packs). No LLM. |
| Final answer | **OPTIONAL:** a small local LLM phrases a 2-line summary over retrieved sources. Off by default — we can just return ranked documents with snippets. |

**Net effect:** a normal query costs essentially nothing. The system works
fully even with the language model turned off.

## 5. Architecture — four stages
1. **Ingest & normalise.** One connector per source type. Spreadsheets: detect
   the real header row, emit one clean record per data row. Scans: OCR to text.
   Everything becomes a common structured record.
2. **Tag & standardise.** Apply one metadata schema to every record. Rule-based
   tagging — no model needed.
3. **Index.** Local embeddings into a self-hostable vector DB (Qdrant /
   pgvector) PLUS a keyword index. Hybrid search covers both meaning and exact
   IDs.
4. **Retrieve & answer.** Query → embed → hybrid search → return ranked records,
   each with its source (file, sheet, row / page). Cross-lingual: an English
   question retrieves Marathi records. Optional short LLM summary on top.

## 6. Metadata standard (the contract between our two halves)

| Field | Purpose |
|---|---|
| title / subject | Human-readable record name |
| date | Parsed, normalised date |
| source_file / sheet / row_or_page | Exact provenance for trust |
| source_type | tracker / letter / minutes / deck / scan … |
| language | mar / hin / eng (auto-detected) |
| department | From a fixed department list |
| category | One of the 12 taxonomy values from the deck |
| location, entities | Place names, people, orgs (rule-extracted) |
| raw_text | Full text for embedding + keyword search |

Implemented as the `Record` dataclass in [`km/schema.py`](../km/schema.py).

## 7. How we split the work (parallel)

| Owner | Responsibility |
|---|---|
| Person A — Ingestion & Knowledge layer | Source connectors, header-detection spreadsheet parser, OCR pipeline for scans, metadata schema + rule-based tagging. "Clean, tagged records out of chaos." |
| Person B — Retrieval & Interface | Vector + keyword indexing, hybrid search, query→results flow with citations, thin search UI. "Ask a question, get trustworthy answers." |

**Day-one agreement:** lock the record schema in Section 6. It is the interface
that lets us build independently.

## 8. PoC scope & success test
- Ingest the 3 sample files + a handful of sample scans.
- Answer ~5 representative questions across languages, each returning the
  correct records with visible sources.
- Example queries: "Show me everything on Quantum", "What meetings on
  semiconductor manufacturing?", "Letters to the President in 2025".

## 9. Two questions to confirm before building
- Rough total volume and how many distinct source formats?
- Is approved on-prem / sovereign infrastructure already available, or should we
  recommend one? (This fixes our model and DB choices.)

---

*This PoC implements the plan above. See [`../README.md`](../README.md) for how
each section maps to code, and the mapping of PoC stand-ins to their production
swaps.*
