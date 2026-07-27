# How to run the PoC

A step-by-step guide to running the Knowledge Management PoC on your own
machine. **The core needs only Python 3.10+ — no other install, no internet,
no cost.**

---

## 1. Install Python (3.10 or newer)

Check whether you already have it:

- **Windows** (Command Prompt): `python --version`
- **macOS / Linux**: `python3 --version`

If you see `Python 3.10.x` or higher, skip to step 2. Otherwise install it:

- **Windows** — easiest: `winget install -e --id Python.Python.3.12`
  then **close the terminal and open a new one**.
  (Or download from https://www.python.org/downloads/ and tick
  **“Add python.exe to PATH”** on the first installer screen.)
- **macOS** — `brew install python` (or from python.org).
- **Linux** — `sudo apt install python3` (Debian/Ubuntu) or your package manager.

> **Windows note:** if `python` opens the Microsoft Store instead of running,
> go to **Settings → Apps → Advanced app settings → App execution aliases** and
> turn **off** the `python.exe` / `python3.exe` toggles, then reopen the terminal.

Throughout this guide, **Windows users type `python`**, **macOS/Linux users type
`python3`**.

---

## 2. Get the code

```bash
git clone -b claude/knowledge-management-poc-lsu0w2 https://github.com/atharv-0509/km-poc.git
cd km-poc
```

---

## 3. Run it (no installs needed)

Type each command on its own — **do not paste lines that start with `#`, they
are just comments.**

**Build the index from the sample data** (ingest → tag → index):

```bash
python -m km ingest
```

**Run the 5 representative questions** with cited results (quickest “does it
work?” check):

```bash
python -m km demo
```

**Ask your own question:**

```bash
python -m km query "Letters to the President in 2025"
python -m km query "semiconductor manufacturing meetings"
```

**Filter by metadata** (language, category, date range):

```bash
python -m km query "water supply" -f language=mar -f "category=War Room"
```

**Web search UI** — then open **http://127.0.0.1:8080** in your browser
(leave the window running; press `Ctrl+C` to stop):

```bash
python -m km serve
```

*(macOS/Linux: use `python3` in place of `python` above.)*

---

## 4. See the live automation

Auto-reindex as files arrive — drop a file into the `data/` folder and it
becomes searchable within seconds, no restart:

```bash
python -m km serve --watch
```

Then copy any `.csv`, `.xlsx`, `.pdf`, `.pptx`, `.docx` or `.txt` file into the
`data/` folder and search for its contents. The UI header shows the live record
count and last-updated time.

---

## 5. Test it on your own files (optional)

The real Office formats (Excel, PDF, PowerPoint, Word) need a few free
libraries. A virtual environment keeps them tidy:

```bash
# Windows
python -m venv .venv && .venv\Scripts\activate
# macOS / Linux
python3 -m venv .venv && source .venv/bin/activate

pip install -e ".[formats]"
```

Then drop your files into `data/` and rebuild:

```bash
python -m km ingest
python -m km serve
```

---

## 6. Turn on the multilingual model (optional, free)

The default search is fully free and offline but uses a lightweight embedding
fallback. For stronger cross-lingual and meaning-based results (e.g. an English
question matching a Marathi record, or telling “President of India” apart from
“president of a council”), install the free local model:

```bash
pip install fastembed
# Windows
set KM_EMBEDDER=fastembed
# macOS / Linux
export KM_EMBEDDER=fastembed

python -m km ingest    # downloads a ~0.22 GB model once, then fully offline
python -m km serve
```

---

## Command reference

| Command | What it does |
|---|---|
| `python -m km ingest [PATH]` | Ingest + tag + index `data/` (or a given file/folder) |
| `python -m km query "..."` | Hybrid search; add `--answer` for a short summary, `--json` for JSON |
| `python -m km demo` | Run the representative questions |
| `python -m km serve [--watch]` | Web UI; `--watch` auto-reindexes as files change |
| `python -m km watch` | Headless auto-reindex loop |
| `python -m km stats` | Show what’s in the index |
| `python -m km gdrive <FOLDER_ID>` | Pull + index a Google Drive folder (see `docs/GDRIVE_SETUP.md`) |

Run the tests (standard library only):

```bash
python -m unittest
```

---

## Troubleshooting

- **`'python3' is not recognized` (Windows)** — use `python`, not `python3`.
- **“Python was not found; run … Microsoft Store”** — Python isn’t installed, or
  the Store alias is intercepting. See the Windows notes in step 1.
- **`'#' is not recognized …`** — you pasted a comment line. Skip any line
  starting with `#`.
- **Nothing in results / empty index** — run `python -m km ingest` first.
- **`.xlsx/.pdf/.pptx/.docx` skipped with a warning** — install the format
  libraries: `pip install -e ".[formats]"`.
- **Port 8080 in use** — set a different port: `set KM_PORT=8090` (Windows) /
  `export KM_PORT=8090` (macOS/Linux), then `python -m km serve`.

Everything here runs offline and free; the only network use is the optional
one-time model download in step 6.
