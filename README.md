# Knowledge Management PoC — Minister's Office

**Retrieval-first, not generation-first.** The system finds and ranks the
right records using local, self-hosted hybrid search — no paid LLM and
near-zero token cost per query. A language model is used only as an optional
final step to phrase a short answer, and can be switched off entirely.

This repository is a **runnable proof of concept** of the approach plan in
[`docs/APPROACH.md`](docs/APPROACH.md). It ingests messy, multilingual
(English / Marathi / Hindi) records, tags them against one metadata schema,
indexes them for hybrid keyword + semantic search, and answers plain-language
questions with **cited** results.

---

## Quickstart (zero dependencies)

The core runs on the Python 3.10+ **standard library only**. No pip install,
no network, no model download.

```bash
# 1. Build the index from the sample data (ingest → tag → index)
python -m km ingest

# 2. Run the representative questions from the plan (Section 8)
python -m km demo

# 3. Ask your own question (hybrid search, cited results)
python -m km query "Letters to the President in 2025"

# 4. Filter by metadata
python -m km query "पाणीपुरवठा" -f language=mar -f "category=War Room"

# 5. Optional: compose a short answer over the results (off by default)
python -m km query "semiconductor manufacturing meetings" --answer

# 6. Thin web search UI
python -m km serve      # then open http://127.0.0.1:8080
```

Run the tests (also standard-library only):

```bash
python -m unittest -v
```

---

## What it demonstrates

Using three sample files + three sample scans that reproduce the mess found in
the real data:

| Query (any language in, any language out) | Correctly returns |
|---|---|
| `Show me everything on Quantum` | Marathi tracker row, English scan note, deck entry |
| `What meetings on semiconductor manufacturing?` | CM-meeting scan, Hindi letter, अर्धवाहक tracker row |
| `Letters to the President in 2025` | English + Marathi + Hindi राष्ट्रपती letters; 2024 letter correctly excluded by the date filter |
| `War room announcements about water supply` | Marathi वॉर रूम / पाणीपुरवठा rows |
| `Cabinet decisions on SAMAGRA` | Cabinet-decision scan, SAMAGRA deck entry |

Every result carries its exact **provenance** (`file · sheet · row/page`), so
answers are always traceable.

**Cross-lingual retrieval** — an English question retrieves Marathi/Hindi
records — works out of the box via a cross-lingual alias lexicon
(`km/vocab.py`). In production this is handled natively by the local
multilingual embedding model (see below); the lexicon is the dependency-free
PoC stand-in.

---

## Architecture — the four stages

```
        ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
files → │ 1. Ingest &  │ → │ 2. Tag &     │ → │ 3. Index     │ → │ 4. Retrieve  │ → cited
        │   normalise  │   │   standardise│   │  (kw+vector) │   │   & answer   │   results
        └──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘
```

| Stage | Module | What it does |
|---|---|---|
| 1. Ingest & normalise | `km/ingest/` | One connector per source type. `spreadsheet.py` detects the *real* header row (not row 1), dedupes duplicate columns, emits one clean record per data row; `xlsx.py` reuses that logic per worksheet and fills merged cells. `pdf.py` reads the text layer and OCRs scanned pages. `pptx.py` pulls slide text + presenter notes; `docx.py` splits by headings. `ocr.py` turns image scans into text (Tesseract `mar+hin+eng` when present; sidecar/plain-text fallback otherwise). `deck.py` splits markdown decks/notes into per-section records. |
| 2. Tag & standardise | `km/tagging.py`, `km/vocab.py`, `km/lang.py` | Rule-based only — **no model per record**. Date parsing, script-based language detection, department lookup from a fixed list, category from the 12-value taxonomy (trusting an explicit category column over free text), regex entity/location extraction. |
| 3. Index | `km/store.py`, `km/embeddings.py` | One portable SQLite file holds the records, an **FTS5/BM25 keyword index**, and one **embedding per record**. Embeddings come from a pluggable provider. |
| 4. Retrieve & answer | `km/search.py`, `km/answer.py` | Keyword + semantic results fused with **Reciprocal Rank Fusion**. Returns ranked records with citations. Optional 2-line answer sits on top, **off by default**. |

The record schema in `km/schema.py` (Section 6 of the plan) is the **contract**
between the ingestion half and the retrieval half — lock it first, build each
half independently.

### Supported source formats

Dispatched by extension in `km/ingest/__init__.py`. Formats needing a
third-party library are **auto-detected** — if the library isn't installed the
file is skipped with a one-line warning and the rest still ingest, so a mixed
folder always indexes everything it can.

| Format | Connector | Notes | Dependency |
|---|---|---|---|
| `.csv` / `.tsv` | `spreadsheet.py` | header-row detection, dedup columns, explicit-category column | none (stdlib) |
| `.xlsx` / `.xlsm` | `xlsx.py` | per-sheet, merged-cell fill, near-duplicate-sheet skip | `openpyxl` |
| `.pdf` | `pdf.py` | text layer per page; scanned pages rasterised → OCR | `pymupdf` (+ Tesseract) |
| `.pptx` | `pptx.py` | slide text **+** presenter notes, one record per slide | `python-pptx` |
| `.docx` | `docx.py` | section-split by Heading styles, tables included | `python-docx` |
| `.md` / `.txt` | `deck.py` | per-section decks/notes | none (stdlib) |
| `.png/.jpg/.tif` | `ocr.py` | Tesseract `mar+hin+eng`, sidecar/text fallback | `pytesseract`, `Pillow` |

Install the format libraries with `pip install -e ".[formats]"` (or from
`requirements-optional.txt`). Regenerate demo fixtures with
`python scripts/make_fixtures.py`.

### Source connectors (where the files live)

Beyond local paths, `km/ingest/gdrive.py` pulls files straight from a **Google
Drive** folder using a read-only **service account**, then hands each file to
the format connectors above:

```bash
pip install -e ".[gdrive,formats]"
KM_GDRIVE_CREDENTIALS=key.json python -m km gdrive <FOLDER_ID>
```

Full walkthrough (service account, folder sharing, Workspace notes) in
[`docs/GDRIVE_SETUP.md`](docs/GDRIVE_SETUP.md). Google-native files are exported
on the way out (Sheets→xlsx, Docs→docx, Slides→pptx); provenance keeps the real
Drive file name and id.

---

## Why token usage stays near zero

| Task | How it's done here | Token cost |
|---|---|---|
| Semantic search | Local embedding model (`SentenceTransformer` in prod; dependency-free hashing embedder in the PoC) | none — runs on our hardware |
| Exact matches | SQLite FTS5 / BM25 keyword index | none — no model |
| Tagging / metadata | Regex, date parsing, fixed department list | none — no model |
| OCR for scans | Local Tesseract (`mar+hin+eng`) | none — no LLM |
| Final answer | **Optional** local extractive summary, or a small local LLM; **off by default** | none by default |

A normal query costs essentially nothing, and the system works fully with the
language model turned off — you just get ranked documents with snippets.

---

## PoC → production (identical design, different target)

The design is deliberately backend-agnostic. Moving to the sovereign GCP
deployment (Mumbai `asia-south1` / Delhi `asia-south2`) is a set of drop-in
swaps behind the same interfaces — no rewrite:

| Concern | PoC (this repo) | Production swap |
|---|---|---|
| Embeddings | dependency-free hashing embedder | local open-weight multilingual model, e.g. `paraphrase-multilingual-MiniLM-L12-v2`, self-hosted on GCP GPU/CPU — set `KM_EMBEDDER=sentence-transformers` |
| Vector store | brute-force cosine in SQLite | Qdrant / pgvector in the same GCP project & region |
| Keyword store | SQLite FTS5 | same, or Elasticsearch/OpenSearch at scale |
| OCR | Tesseract if present, else text sidecars | Tesseract with language packs on GCP VMs |
| Cross-lingual | alias lexicon (`km/vocab.py`) | native, via the multilingual embedding model |
| Answer step | extractive (no model) | small local open-weight LLM (`KM_LOCAL_LLM=/path/model.gguf`) |

Install any optional upgrade from `requirements-optional.txt`; each is
auto-detected, and the system degrades gracefully if it's absent. Record text
never leaves the controlled environment in either configuration.

---

## Configuration

Everything is env-overridable (see `km/config.py`):

| Variable | Default | Meaning |
|---|---|---|
| `KM_DB` | `km_index.sqlite3` | index file path |
| `KM_DATA` | `data` | source directory |
| `KM_EMBEDDER` | `auto` | `auto` \| `hashing` \| `sentence-transformers` |
| `KM_ANSWER` | `0` | set `1` to compose an answer by default |
| `KM_ANSWER_MODE` | `extractive` | `extractive` \| `llm` |
| `KM_LOCAL_LLM` | — | path to a local GGUF model for `llm` answer mode |
| `KM_HOST` / `KM_PORT` | `127.0.0.1` / `8080` | web UI bind address |

---

## Repository layout

```
km/
  schema.py       Record = the Section 6 metadata contract
  vocab.py        fixed department list, category hints, cross-lingual lexicon
  lang.py         language detection + cross-lingual expansion (no model)
  tagging.py      rule-based date/category/entity/location tagging
  ingest/         Stage 1 connectors: csv/xlsx (header detection), pdf, pptx,
                  docx, deck, ocr — dispatched by extension, optional deps
                  auto-detected
  embeddings.py   pluggable embedder: hashing (default) | sentence-transformers
  store.py        Stage 3: SQLite records + FTS5 keyword + vector store
  search.py       Stage 4: hybrid RRF search with citations
  answer.py       optional final answer (extractive | local LLM), off by default
  pipeline.py     ingest → tag → index orchestration, and search
  cli.py / web.py command line + thin web UI
data/             sample tracker, letters register, taxonomy deck, scans
docs/APPROACH.md  the approach plan this PoC implements
tests/            standard-library unittest suite
```

---

## Known PoC simplifications (deliberate, documented)

- **Hashing embedder** approximates semantics via character n-grams; the real
  multilingual model is a one-line swap (`KM_EMBEDDER=sentence-transformers`).
- **Cross-lingual** relies on the alias lexicon for the demo vocabulary; extend
  `km/vocab.py` or switch to the multilingual embedding model for open coverage.
- **Taxonomy deck sections** are indexed as records, so a category definition
  can rank alongside actual records for a broad query — expected, since the deck
  is itself a knowledge source.
- **Sample data ships as CSV/markdown/text** so the demo runs with zero installs;
  the real `.xlsx/.pdf/.pptx/.docx` connectors are implemented and tested (install
  `".[formats]"` and drop those files into `data/`).

## The two open questions from the plan (Section 9)

1. **Volume & number of distinct source formats** — determines whether the
   brute-force vector search stays fine or we move to Qdrant/pgvector, and how
   many connectors Stage 1 needs.
2. **Approved sovereign infrastructure** — if GCP India is confirmed, we pin the
   embedding model, vector DB and OCR to that project/region; the code above is
   already structured for exactly that swap.
