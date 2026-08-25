# Public Standards Download Pipeline Design

## Objective

Build a reusable public GitHub Actions download relay for automotive smart-manufacturing standards assets that are officially public and redistributable. GitHub provides ephemeral network/compute; Google Drive remains the long-term archive.

## Boundaries

The repository stores only metadata, workflow code, validation code and archive-status records. Standards PDFs and large source snapshots are never committed to Git history. Copyright-restricted ISO/IEC/IATF/AIAG/VDA/SAE/etc. full texts are not fetched or redistributed by this pipeline.

## Architecture

1. `manifest/standards.json` is the source of truth for downloadable assets.
2. `scripts/prepare_matrix.py` validates the manifest and creates a GitHub Actions matrix.
3. Small assets sharing an `artifact_group` are fetched together.
4. Large assets declare `split_parts`; each part becomes an independent matrix job/artifact so every artifact stays below the Drive connector's 100 MiB transfer ceiling.
5. `scripts/fetch_assets.py` downloads with retries, checks PDF/ZIP magic, computes byte size/SHA-256, optionally slices a large source into a selected part, and emits a CSV evidence manifest.
6. `.github/workflows/fetch-public-assets.yml` uses only `ubuntu-latest`, uploads artifacts with `retention-days: 1`, and never commits binaries.
7. `archive/drive-status.json` stores only logical Drive paths and archive state, not private Drive file IDs or private URLs.

## Manifest fields

Required per asset:
- `id`: stable machine identifier.
- `title`: human-readable name.
- `url`: official/public download URL.
- `filename`: desired archived filename.
- `kind`: `pdf` or `zip`.
- `artifact_group`: small-file grouping key.
- `license_class`: e.g. `public-government`, `open-specification`, `open-source`.
- `redistributable`: must be `true` for automatic download.

Optional:
- `split_parts`: integer >= 2 for large files. The source is downloaded in each part job, then deterministically split into equal byte ranges; only the selected part is uploaded.
- `notes`.

## Validation and failure behavior

- Reject duplicate IDs or filenames.
- Reject non-HTTPS URLs.
- Reject entries with `redistributable != true`.
- Reject unsupported kinds.
- Verify `%PDF-` for PDFs and `PK` for ZIPs.
- Record SHA-256 and byte size for every successful source.
- Fail a job if the produced artifact payload exceeds 95 MiB, leaving headroom below the 100 MiB Drive connector limit.
- Network failure or invalid file headers fail only the affected matrix item while preserving diagnostics.

## Cost controls

- Public repository.
- Standard `ubuntu-latest` GitHub-hosted runner.
- `retention-days: 1`.
- No binaries in commits/releases.
- No redundant complete-bundle artifact; category/split artifacts are the transfer units.

## Initial acceptance set

Use the already verified 18-source set:
- NIST public PDFs: 6.
- IDTA AAS open specification PDFs: 6.
- Open-source snapshots: 6.

The IDTA `submodel-templates` repository uses split mode because its current archive exceeds the Drive relay limit.

## Success criteria

- Repository remains public and small.
- Manifest validates in CI.
- All initial public/redistributable assets can be downloaded and header-validated.
- All generated artifacts are <= 95 MiB and retained for one day.
- SHA-256/size evidence is available from artifacts/logs.
- Logical Drive archival status is tracked without exposing private Drive identifiers.
