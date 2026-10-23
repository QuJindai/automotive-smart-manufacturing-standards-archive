# Download purpose-aware admission 0.5.2

Status: deployed; production MCP/Drive acceptance passed on 2026-10-23.
Implementation: `876dd902c5812e56bea37153587ee15b8e4d424c`.

## Root cause and scope

The old name-resolution validator, tool schema and server instructions required
`redistributable: true` even for a private reading copy. A real web Chat paper
request therefore correctly refused to invent public redistribution rights and
remained blocked. This was a purpose/admission contract defect, not a PDF transfer
failure. The original blocked record is preserved as evidence; retests are new jobs.

The fix introduces generic personal-archive/public-redistribution purposes,
truthful rights and public-access evidence, private Drive verification and no
personal GitHub artifact fallback. It adds no per-paper or per-domain exception.
Existing providers, formats, fallback/streaming integrity, historical jobs and
queue watchdog are preserved. See [policy and rollback](../download-purpose-policy.md).

Review also reproduced and fixed preflight source probes without a Drive session,
nonterminal private-destination failures, and manual receipt injection through
resume/finalize. Retry now invalidates old personal verification.

## Verification

- Node: 82/82 pass.
- Python executor: 52 pass locally, two browser tests skipped locally and both
  pass in the real Chromium CI job. Existing archive pipeline: 13/13 pass.
- [CI run 39898803913](https://github.com/QuJindai/automotive-smart-manufacturing-standards-archive/actions/runs/39898803913): unit and browser jobs passed.
- Live staging: new schema, personal false-redistribution admission, public
  redistribution rejection, login/paywall/incomplete-public-evidence rejection pass.
- Production source readback exactly matches the implementation bundle.
- No old-SHA executor was queued or running before enabling the new admission.

Production MCP is ACTIVE version 28 (`0.5.2-purpose-aware`); Drive is ACTIVE
version 24. Staging MCP/Drive are versions 31/27. Existing authentication and
OAuth scopes were retained. No permanent token or GitHub secret was added.

## Real production downloads

| Class | File | Bytes | Job | Executor run | Result |
| --- | --- | ---: | --- | --- | --- |
| Paper | Attention-Is-All-You-Need-NeurIPS-2017.pdf | 569417 | download-186bc5f9072740d28edb872aa53777f9 | 39899287035 | COMPLETED |
| Standard | NIST.FIPS.203.pdf | 1252341 | download-de53a80d505041579719dbf5fe5f46b7 | 39899389383 | COMPLETED |
| Large file | blender-4.5.0-linux-x64.tar.xz | 376170648 | download-a593f33fedea4b6091b814b45367592a | 39899476073 | COMPLETED |

All three have independent Google Drive SHA-256 receipts, matching sizes/parents,
`drive_verified=true`, `checksum_verified=true`, and `private_verified=true`.
An independent Drive connector read confirms names, sizes, destination and
owner-only/unshared permissions. That connector normalizes away raw checksum
fields; checksum evidence comes from the gateway's independent Google API read.
All three GitHub runs have zero artifacts. The large-file hash also matches
the official [Blender manifest](https://download.blender.org/release/Blender4.5/blender-4.5.0.sha256).

The paper source explicitly remains `redistributable=false`; its public official
PDF was admitted for personal reading only. The
[NeurIPS copyright FAQ](https://neurips.cc/FAQ/Copyright) is not treated as a
third-party public redistribution grant. No existing Drive permissions were changed.

## Boundaries and test infrastructure

This is fresh production MCP acceptance, not a fresh web Chat UI acceptance.
The browser control channel still exposes only an empty MCP Apps surface, and
the current Chat connector schema is cached from the older release. Refresh the
plugin's tool definitions before expecting an old Chat session to expose the new
fields. The live server's initialize/tools-list contract was verified directly.

Initial GitHub staging attempts (39898817077, 39898821399) could not authenticate
because their referenced repository secret was absent; they did not test service
admission. The same new acceptance script then passed against live staging using
the existing connection in a process-local environment. The newly attempted
credential-dependent workflow was removed rather than provisioning a new secret.
Its reusable script remains. The temporary local connection file was deleted.

Local acceptance JSON retains full job/Drive receipts and deployment hashes:
`outputs/download-purpose-acceptance-20261023.json` in the parent task workspace.
