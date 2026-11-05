# Phase 1 headline tables

Source: `runs/phase1_flash/aggregate.parquet` (20 dev tasks, agents `api-glm-5.3-flash`, judge `api-glm-5.3`,
2026-11-01). Brackets are 95% percentile-bootstrap intervals on the mean. "Judged" columns use the LLM judge;
"exact" columns use byte-level text diff.

## Table 1: run counts

| condition | runs | faults applied | utility passes |
|---|---|---|---|
| none | 780 | 610 | 595 |
| twin | 610 | - | 552 |
| restart_scratch | 260 | 202 | 241 |
| restart_stage | 260 | 204 | 230 |
| always_verify | 260 | 202 | 231 |

## Table 2: propagation by fault template (condition none, judged)

| fault | n | propagated | downstream artifacts changed | utility |
|---|---|---|---|---|
| finding_accidental_obvious | 19 | 0.37 [0.16, 0.58] | 0.95 [0.32, 1.79] | 0.89 |
| finding_accidental_subtle | 31 | 0.58 [0.42, 0.77] | 1.29 [0.81, 1.97] | 0.77 |
| finding_adversarial_obvious | 60 | 0.65 [0.52, 0.78] | 1.63 [1.22, 2.07] | 0.90 |
| finding_adversarial_subtle | 60 | 0.77 [0.65, 0.87] | 1.62 [1.30, 1.98] | 0.93 |
| finding_other_obvious | 60 | 0.62 [0.50, 0.73] | 2.10 [1.60, 2.62] | 0.87 |
| finding_other_subtle | 60 | 0.42 [0.30, 0.55] | 1.20 [0.78, 1.65] | 0.87 |
| plan_step_accidental_obvious | 52 | 0.62 [0.48, 0.75] | 0.63 [0.50, 0.79] | 0.75 |
| plan_step_accidental_subtle | 60 | 0.38 [0.27, 0.52] | 0.40 [0.27, 0.53] | 0.72 |
| plan_step_adversarial_obvious | 60 | 1.00 [1.00, 1.00] | 1.13 [1.05, 1.22] | 0.92 |
| plan_step_adversarial_subtle | 60 | 1.00 [1.00, 1.00] | 1.15 [1.07, 1.25] | 0.53 |
| plan_step_other_obvious | 60 | 0.92 [0.85, 0.98] | 1.02 [0.92, 1.12] | 0.17 |
| plan_step_other_subtle | 28 | 0.93 [0.82, 1.00] | 1.39 [1.18, 1.61] | 0.21 |

Low n for finding_accidental_obvious/subtle and plan_step_other_subtle: those templates failed to apply on many tasks (regex with no match).

## Table 3: taint by fault stage (RQ1)

| stage | n | ignored | under-taint | over-taint | runs w/ under | runs w/ over | descendants unchanged | changed uncited | exact under / over |
|---|---|---|---|---|---|---|---|---|---|
| finding | 290 | 0.41 | 0.64 [0.52, 0.78] | 0.54 [0.44, 0.64] | 0.32 | 0.33 | 0.37 | 0.41 | 1.92 / 0.03 |
| plan step | 320 | 0.20 | 0.13 [0.10, 0.17] | 0.22 [0.17, 0.26] | 0.13 | 0.22 | 0.22 | 0.15 | 0.73 / 0.01 |

"Descendants unchanged" is over-taint as a fraction of all declared descendants (424 and 320); "changed uncited" is
under-taint as a fraction of all changed artifacts (451 and 294). An artifact with no twin at the same position
counts as changed, as in the floor. Table 8 (`docs/tables/distance.md`) breaks the change rate down by hop.

## Table 4: clean-vs-clean noise floor (per task, 20 tasks)

| artifact kind | judged mean | judged median | tasks at 0 | tasks at 1 | exact mean |
|---|---|---|---|---|---|
| findings | 0.56 | 0.67 | 4 | 3 | 0.97 |
| plan steps | 0.26 | 0.00 | 12 | 3 | 0.93 |
| executed steps | 0.24 | 0.00 | 13 | 3 | 1.00 |

## Table 5: restart baselines over runs whose fault applied

| condition | n | utility | clean utility | LLM calls | completion tokens | seconds | irreversible actions | unauthorized actions | discarded artifacts | recovery calls |
|---|---|---|---|---|---|---|---|---|---|---|
| none | 610 | 0.72 [0.69, 0.76] | 0.88 | 9.3 | 1661 | 34 | 0.31 [0.25, 0.38] | 0.04 | 0.0 | 0.0 |
| restart_stage | 204 | 0.89 [0.84, 0.93] | 0.90 | 13.3 | 2118 | 50 | 0.63 [0.43, 0.86] | 0.07 | 8.6 | 4.1 |
| restart_scratch | 202 | 0.94 [0.90, 0.97] | 0.85 | 18.1 | 3120 | 65 | 0.60 [0.41, 0.82] | 0.05 | 8.6 | 8.7 |
| always_verify | 202 | 0.88 [0.84, 0.93] | 0.90 | 23.6 | 3595 | 82 | 0.28 [0.19, 0.39] | 0.00 | 0.0 | 0.0 |

## Table 6: utility conditional on propagation (condition none)

| fault outcome | n | utility |
|---|---|---|
| ignored | 182 | 0.90 [0.86, 0.94] |
| propagated | 428 | 0.64 [0.60, 0.69] |

## Table 7: adversarial faults, unauthorized actions by condition

| condition | stage | n | runs w/ unauthorized action | unauthorized actions / run | utility |
|---|---|---|---|---|---|
| none | finding | 120 | 0.00 | 0.00 | 0.92 |
| none | plan | 120 | 0.13 | 0.14 | 0.72 |
| restart_stage | finding | 40 | 0.07 | 0.10 | 0.80 |
| restart_stage | plan | 40 | 0.23 | 0.28 | 0.88 |
| restart_scratch | finding | 40 | 0.00 | 0.00 | 0.93 |
| restart_scratch | plan | 40 | 0.17 | 0.20 | 0.95 |
| always_verify | finding | 40 | 0.00 | 0.00 | 0.93 |
| always_verify | plan | 40 | 0.00 | 0.00 | 0.90 |

## Table 8: judged change rate by hop from the fault (condition none)

Cited: artifacts with a citation path from the faulted artifact; uncited: without. Floor: clean-vs-clean judged
floor for that artifact kind. An artifact with no twin at the same position counts as changed. The last two rows
condition a finding fault's executed steps on whether their own plan step changed.

| fault | artifacts | cited | n | uncited | n  | floor |
|---|---|---|---|---|---|---|
| finding | plan steps, 1 hop | 0.63 [0.57, 0.69] | 212 | 0.34 [0.28, 0.39] | 292 | 0.26 |
| finding | executed steps, 2 hops | 0.63 [0.57, 0.69] | 212 | 0.29 [0.25, 0.35] | 292 | 0.24 |
| plan step | executed steps, 1 hop | 0.78 [0.74, 0.83] | 320 | 0.13 [0.10, 0.17] | 323 | 0.24 |
| finding | executed steps, plan step changed | 0.81 [0.74, 0.88] | 133 | 0.69 [0.60, 0.78] | 99 | 0.24 |
| finding | executed steps, plan step unchanged | 0.32 [0.22, 0.42] | 79 | 0.09 [0.06, 0.14] | 193 | 0.24 |
