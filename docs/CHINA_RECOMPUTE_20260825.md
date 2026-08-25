# China Smart-Manufacturing Standards Recompute — 2026-08-25

## Frozen baseline

The Batch2 + Batch3 candidate set was reconciled against the full R09 materialized registry.

- Historical R05 freeze: **157 records / 23 adoption relations** — retained as a historical milestone.
- Previous R09 China integrated baseline: **178 / 32** — retained as the prior integrated milestone.
- New frozen China materialized baseline: **211 / 32**.
- R02–R08 raw materialized instances: **1169**.
- R02–R08 exact-reference unique materialized nodes: **1167**.
- Materialized relation records: **494**.

All 33 Batch2/Batch3 candidates were absent from both the previous `reference` and `canonical_reference` sets. Batch2 and Batch3 also had zero exact-reference overlap.

## R10 delta

`C01 +4, C03 +3, C04 +1, C10 +2, C11 +6, C22 +5, C24 +7, C26 +3, C27 +1, C29 +1`.

The formal recompute also corrected a provisional Batch3 label: R10 C28 is simulation/scenario/virtual validation, not lifecycle operations. Service-oriented manufacturing additions were therefore allocated across C01/C24/C26/C27/C04.

## R11 delta

- A: **159**
- B: **874** (+32)
- C: **63**
- D: **71** (+1)

The single new D-grade record is `20255613-T-610`, an aluminium-extrusion-specific digital-workshop project. The other 32 additions are generic standards directly usable in automotive manufacturing, normally with an automotive Profile or implementation rule.

## New relation evidence

Twelve relations were added: four missing `GB/T 23031` Parts, four `GB/T 43880` Parts, and four `REVISED_BY` project links for GB/T 33007, GB/T 40682, GB/T 37700 and GB/T 37724.

`REVISED_BY` does not mean that the current standard has already been replaced.

## Adoption evidence conflict

For `20254647-T-604`, official sources disagree on whether the referenced IEC 62443-2-4 edition is 2023 or 2024. The previously recorded 2023 adoption relation remains the baseline while the conflict is explicitly retained for later evidence arbitration. It is not counted as a second adoption relation.

## R01 caveat

ISO/TC184 remains an authoritative aggregate block: 929 current published nodes, 2677 lifecycle nodes and 1369 replacement edges. Its 929 current rows are not yet materialized; therefore this repository must not claim a global exact unique count that includes R01.

## Public-repository boundary

This repository stores only public metadata, official evidence links and lifecycle/relationship information. It does not publish Chinese national/industry standard full text and does not store private Google Drive identifiers or URLs.
