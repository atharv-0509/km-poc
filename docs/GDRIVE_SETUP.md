# Google Drive source connector — setup (service account, plain Gmail)

The connector pulls files out of a Drive folder, read-only, using a dedicated
**service account** (a non-human Google identity with its own email). Nothing
personal is connected, access is revocable, and it fits the sovereign GCP
design. Files flow through the same xlsx/pdf/pptx/docx/csv connectors.

## One-time setup (~5 min)

1. **Create the service account**
   - Google Cloud Console → *IAM & Admin → Service Accounts → Create*.
   - Name it e.g. `km-ingest`. No project roles are needed (Drive access comes
     from folder sharing, below).
   - Note its email: `km-ingest@<project>.iam.gserviceaccount.com`.

2. **Enable the Drive API**
   - Console → *APIs & Services → Library → Google Drive API → Enable*
     (on the same project).

3. **Create a key**
   - On the service account → *Keys → Add key → Create new key → JSON*.
   - Download the JSON file and keep it secret (never commit it).

4. **Share the office folder with the service account**
   - In Google Drive, right-click the folder holding the records → *Share* →
     add the service account email as **Viewer**.
   - Sharing the top folder is enough; the connector recurses into subfolders.

## Run it

```bash
pip install -e ".[gdrive,formats]"          # connector + file-format libs

export KM_GDRIVE_CREDENTIALS=/secure/path/km-ingest-key.json
python -m km gdrive <FOLDER_ID>             # pull + tag + index
python -m km query "Letters to the President in 2025"
```

`<FOLDER_ID>` is the last path segment of the folder URL:
`https://drive.google.com/drive/folders/`**`1AbC...xyz`**.

Flags: `--append` (add to an existing index), `--no-recursive`,
`-c/--credentials` (key path if not using the env var),
`--embedder sentence-transformers` (production multilingual embeddings).

## Notes

- **Scope is read-only** (`drive.readonly`); the connector never writes to Drive.
- **Google-native files** are exported on the way out: Sheets→`.xlsx`,
  Docs→`.docx`, Slides→`.pptx`, so they use the normal format connectors.
- **Provenance** keeps the real Drive file name and records the Drive file id
  (`extra.gdrive_id`) so every result still points back to its origin.
- **Google Workspace** (later): instead of per-folder sharing you can grant the
  service account domain-wide delegation to read across the domain and use
  Shared Drives — the same connector code works.
