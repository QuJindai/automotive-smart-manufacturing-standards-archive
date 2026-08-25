# Archive Workflow

## Operating model

`Official public source -> Public GitHub Actions runner -> one-day artifact -> Google Drive long-term archive`

GitHub is only the temporary network/compute relay. Google Drive is the authoritative long-term asset store.

## Adding a public asset

1. Confirm that the source is official/public and redistribution is permitted.
2. Add one entry to `manifest/standards.json`.
3. Set `redistributable` to `true` only when automatic archival is allowed.
4. Supply `expected_size_bytes` when known so CI can reject an artifact group that would exceed the Drive transfer ceiling.
5. If the source itself is too large, set `split_parts` to an integer that keeps each part below 95 MiB.
6. Commit the manifest change; CI validates and downloads the source.
7. Transfer successful GitHub Actions artifacts to the matching logical Drive folder.
8. Update `archive/drive-status.json` with logical path/status only. Never commit Drive file IDs or private URLs.

## Evidence

Every transfer artifact includes `evidence.csv` with:

- stable asset ID;
- official source URL;
- expected and actual byte sizes;
- source SHA-256;
- output filename and SHA-256;
- split part index/total where applicable;
- success/failure diagnostics.

Split artifacts also contain `reconstruct.json` with the exact ordered part list and reconstruction commands.

## Copyright-restricted standards

Do not add direct full-text download entries for copyright-restricted ISO, IEC, IATF, AIAG, VDA, SAE or equivalent publications unless the specific source/license explicitly permits redistribution. Track those standards through official acquisition links and research metadata instead.

## Cost controls

- Repository: public.
- Runner: `ubuntu-latest` only.
- Artifact retention: one day.
- No release assets for downloaded standards.
- No standards binaries in Git commits.
- No redundant complete-bundle artifact.

## Drive transfer ceiling

The current connector path used by this project rejects a single transfer object above 100 MiB. This repository therefore uses a 95 MiB payload guard and deterministic multi-part transfer for larger assets.
