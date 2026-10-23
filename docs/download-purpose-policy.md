# Purpose-aware admission (0.5.2)

New downloads default to `constraints.purpose = personal_archive`. This is a
private reading/storage copy, not a statement of public redistribution rights.
`public_redistribution` requires affirmative redistribution permission even for
direct URLs. Selecting that purpose does not itself publish or share anything.

For name resolution, `official` remains required. `redistributable` is a truthful
boolean, not a mandatory assertion of rights. A false value is allowed only for
personal archives with `publicly_accessible: true`, `access_restriction: none`, a
nonempty factual `license_class` access basis and an HTTPS `rights_evidence_url`.
Login, paywall, DRM, prohibited personal copying and unknown access restrictions
are not admitted. Public availability does not establish a redistribution license.
These rules apply to all providers and supported formats, not individual papers.
Existing jobs without a purpose retain the original admission/transfer contract.

Personal archives require a private, owner-only My Drive destination and file.
Missing or shared metadata fails closed; existing permissions are never changed.
Without a Drive session, no file is fetched for an artifact fallback. GitHub
artifact upload is skipped for all personal jobs, including result artifacts.
Completion additionally requires independently read Drive SHA-256, parent, name,
size and `private_verified: true` receipts. Runner scratch files remain ephemeral.

Deployment order: tested executor on main, compatible Drive verifier, then MCP.
Stage the MCP contract first. Drain queued/in-progress executor runs pinned to
older SHAs before enabling new personal jobs: pushing main does not update an
already-started workflow. No database migration or OAuth change is required.
The `Download Purpose Acceptance` workflow uses the existing masked MCP secret;
staging tests rejection/acceptance and production submits paper, standard and
large-file jobs through normal tools. It does not generate completion receipts.
Verify those jobs, Drive metadata and zero personal-job artifacts independently.
Never rewrite a previously blocked job to claim a successful historical run.

Rollback: stop new submissions before restoring the saved pre-release MCP and
Drive sources. Keep the personal-artifact suppression in the executor: reverting
that safety gate while personal jobs exist is unsafe. Diagnose/drain or explicitly
cancel outstanding personal jobs before considering any older executor version.
