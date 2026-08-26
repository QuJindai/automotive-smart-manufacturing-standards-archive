# P-AAS Reference Executor V1 — Public Subset Amendment

## Reason
During Task 1, the original plan assumed the full concrete `P-AAS + P-AI` Profile/Test instance would be committed to the public repository. That was broader than required for the P-AAS executor and would unnecessarily duplicate the governed full machine-asset package.

## Approved implementation boundary
The public executor commits only the machine-readable subset required to execute P-AAS V1:

- `reference-implementation/p-aas-v1/profile/p-aas-profile.v1.json` — 14 P-AAS rules;
- `reference-implementation/p-aas-v1/profile/p-aas-test-cases.v1.json` — AAS-T001 through AAS-T019.

The complete 26-rule `P-AAS + P-AI` Profile, 39-test corpus, procurement/FAT-SAT workbook and Evidence assets remain governed as the long-term project machine-asset package.

## Invariants preserved
- P-AAS rule/test semantics are unchanged.
- AAS-T001..T019 IDs remain the same as the governed full test corpus.
- Every public P-AAS rule retains source traceability and linked TestIDs.
- No standards PDF, private Drive ID/URL or real production data is added to the public repository.
- P-AI execution remains explicitly out of scope for this phase.

## Result
This amendment reduces public duplication and keeps the reference executor self-contained without broadening the repository's disclosure surface. The P-AAS reference implementation and CI consume this 14-rule/19-test public subset.
