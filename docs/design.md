# Codebase design

Date: 2026-10-21. Companion to [the proposal](proposal.md).

## Shape

A flat Python package, `mar/`, one module per concern. This is a solo research project due in
December; structure is added only when an experiment needs it.

| Module | Responsibility |
| --- | --- |
| `config.py` | Pydantic models for the YAML files in `configs/` |
| `llm.py` | OpenAI-compatible client (TritonAI); logs model string, system fingerprint, usage per call; `FakeLLM` for tests |
| `env.py` | AgentDojo wrapper: load suite/task, deepcopy snapshot/restore, tool action classes, allowlist, utility/security checks |
| `artifacts.py` | Finding, PlanStep, ExecutedStep, NoteEntry, ToolAction; `ProvenanceGraph.descendants()` |
| `agents.py` | Researcher, Planner (schema-enforced citations), Executor (native tool loop), Verifier |
| `prompts/` | One text file per agent, hashed into the run manifest |
| `notes.py` | Cross-task notes with per-entry provenance; coarse and fine purge |
| `faults.py` | Template loading and hash, seeded schedule, injection, oracle revealed after Δ steps |
| `recovery.py` | One small class per policy or baseline |
| `run.py` | The orchestrator; the only module with side effects |
| `judge.py` | Artifact diff (exact and LLM judge), noise floor, agreement with hand labels |
| `metrics.py` | Taint, divergence, harm, cost; aggregation of `runs/` into one parquet |
| `cli.py` | `mar run`, `mar aggregate`, `mar day1` |

## Two rules

1. **Only `run.py` has side effects.** It calls the LLM, executes tools, and writes files. Agents are
   functions of their inputs given an injected `LLMClient` and `ToolRuntime`, so prompts are identical
   across recovery methods and tests run on `FakeLLM`.
2. **Fault templates are data, not code.** They live in `data/fault_templates/`; the directory hash
   is written to every run manifest. That is the whole freezing mechanism.

## Interfaces

- `LLMClient.complete(messages, tools=None, schema=None) -> LLMResponse`
- `ToolRuntime.call(name, args) -> ToolResult` (implemented in `run.py`; asks the policy first)
- `Agent.run(inputs, llm, tools=None) -> list[Artifact]`
- `RecoveryPolicy.on_tool_request(action, graph) -> allow | buffer | block`
- `RecoveryPolicy.on_reveal(fault_id, graph, run) -> RecoveryPlan`
- `Env.snapshot()`, `Env.restore(snapshot)`, `Oracle.reveal_at(step)`

## Run directory

```
runs/<run_id>/
  manifest.json    experiment, condition, task ids, fault id or "clean", repeat, seed, model string,
                   benchmark version, git sha, templates hash, prompt hashes,
                   parent_run_id + branch_point when the run is a counterfactual twin
  events.jsonl     ordered: llm_call, tool_action, artifact, fault_injected, oracle_revealed,
                   recovery_action, snapshot
  provenance.json
  result.json      checker outcomes and raw metrics
```

Flat. Aggregation filters on manifest fields. Resume skips run ids that already have `result.json`.
The memory scenario is a run whose manifest lists several task ids. A counterfactual twin forks
from the snapshot taken just before injection, so pre-fault artifacts are shared with its parent;
noise-floor clean runs are independent.

## Decisions and their reasons

- **AgentDojo as a pinned pip dependency** (`0.1.35`), wrapped, never modified. Its `AgentPipeline`
  is single-agent, so we use only suites, `TaskEnvironment`, `FunctionsRuntime`, and checkers. The
  executor's messages use AgentDojo `ChatMessage` types so its defense elements can be inserted for
  the built-in-defenses baseline.
- **Messages are plain OpenAI dicts in Phase 1.** AgentDojo `ChatMessage` compatibility, needed only for
  the Phase 2 built-in-defenses baseline, is deferred.
- **AgentDojo tools carry no action class**, so `env.py` keeps a dict from tool name to class.
- **TritonAI endpoint** (`BASE_URL`, `TRITONAI_API_KEY` in `.env`) was probed on 2026-10-21: native
  `tool_calls` and strict JSON-schema `response_format` both work on `api-glm-5.3-flash`. Models
  available: `api-glm-5.3`, `api-glm-5.3-flash`, `api-muse-glimmer-30b`.
- **No LLM response cache** in reported runs. It would corrupt the noise floor.
- **TAMAS supplies fault content, not tasks.** `scripts/adapt_tamas.py` writes templates that run
  inside AgentDojo environments. No second environment backend.
- **Fan-out is sequential** in Phase 1. The Phase 2 parallel researcher parallelizes only read-only
  LLM calls.
- **Dev/eval split** is two YAML files and a `--tasks` flag. No guard machinery.
- Tooling: Python 3.12, `uv`, Pydantic, `argparse`, `pytest`, pandas + pyarrow.

## Day-1 check (2026-10-21)

`mar day1 --model api-glm-5.3 --n 5` on the workspace suite: passed 5/5, mean 6.2 s per task,
13 LLM calls total. GLM 5.3 clears the gate; no model switch needed. The endpoint runs vLLM and the
model spends reasoning tokens, both captured in the per-call usage log.

## Pipeline live check (2026-10-21, api-glm-5.3-flash)

user_task_0 and user_task_17: utility True on both, 7 to 8 LLM calls, 5 to 6 findings, one plan step
citing 2 to 3 findings. Planner needed 1 and 2 retries to produce valid citations; the retry rate is
recorded per step and should be watched (proposal risk: "planner does not cite findings").

## Noise floor, smoke runs (2026-10-21, api-glm-5.3-flash, exact diff)

| Task | findings | plan steps | executed steps | tool sequence differs |
| --- | --- | --- | --- | --- |
| user_task_0 | 1.00 | 1.00 | 1.00 | False |
| user_task_17 | 1.00 | 1.00 | 1.00 | True |
| user_task_13 | 1.00 | 1.00 | 1.00 | True |

Exact diff puts the floor at or near 1.0 for every kind: two clean runs almost never produce byte-identical artifacts, so the LLM judge below is what propagation numbers are read against.

## LLM judge and judged noise floor (2026-10-31, judge api-glm-5.3)

`mar judge --runs-dir <dir>` runs after an experiment, over finished run directories. It pairs each
applied-fault `none` run with its twin and the two lowest clean repeats per (task, condition), asks the
judge once per matched artifact pair whether a downstream agent would act the same on either
(`mar/prompts/judge.md`, strict `{same, reason}` schema), and writes `judge.json` into the left run's
directory. `mar aggregate` then reports exact and judged numbers side by side (`floor_judged_*`,
`judged_counterfactual_changed`, `judged_under_taint`, `judged_over_taint`, `judged_ignored`).
Judgments are cached by design: the no-cache rule protects agent calls, and a judge verdict is a
measurement that should not change between aggregations. A malformed verdict counts as a difference.

Same smoke runs as above, judged:

| Task | findings | plan steps | executed steps |
| --- | --- | --- | --- |
| user_task_0 | 0.00 | 0.00 | 0.00 |
| user_task_17 | 0.00 | 0.00 | 0.00 |
| user_task_13 | 0.50 | 0.50 | 0.50 |

The 0.5 on user_task_13 is real: the two clean runs split the sources into findings differently, so
ids pair different facts, and one run's plan step cites a guidance file the other's does not.
On the 8-task fault sample (`runs/live8`, 19 applied faults with twins): exact diff marks 0/19 faults
ignored; the judge marks 8/19 ignored, and over-taint rises from 0 to 1 or 2 on those runs because the
declared descendants of an ignored fault are all over-taint. 41 of 65 twin artifact pairs were
byte-identical (copied from the checkpoint) and were not sent to the judge; 24 judge calls took about
5 minutes including run loading, so judging the full Phase 1 run is roughly 2 to 3 hours.

`mar judge --sample 50` writes judged pairs with an empty `hand_differs` column for the 50-artifact
agreement check the proposal commits to; `judge.agreement` scores it.

## Phase 1 dev run (2026-11-01, agents api-glm-5.3-flash, judge api-glm-5.3)

`configs/phase1.yaml` on the 20-task dev split: 1,560 jobs plus 610 twins, 2,170 finished runs in
`runs/phase1_flash`, about 6 hours wall clock at 4 workers (median 18 s per run; task 25 runs took
25 to 90 s). 610 of 720 faults applied.

**Why flash, not GLM 5.3.** The first launch used `api-glm-5.3`. Its reasoning tokens made every
planner call 20 to 30 s and the restart and verify baselines 30+ calls, so runs took 100 to 600 s and
the grid projected to about 100 hours at 4 workers; a TritonAI outage overnight on 2026-10-31 added
16 error results. The 54 finished GLM 5.3 runs (all task 25) stay in `runs/phase1` for reference and
are not mixed into the Phase 1 tables. On task 25 flash passes utility in most runs where GLM 5.3
failed most, apparently because the heavier model over-researched and the checker penalised extra
emails; that is one task and is not generalised.

**Incidents.** A network change mid-run left the four workers on half-dead sockets for 10 minutes
(the endpoint answered a fresh connection in 0.3 s); the process was killed and relaunched with
`--resume`, which retried the 15 jobs that had errored with `APIConnectionError`. Three faulted runs
from that window finished but their twins failed (`twin_error`); resume did not retry those (only
`error` results), contrary to the comment in `run_job`. Fixed: a failed twin now reruns the whole
job, since the twin needs the faulted run's in-memory checkpoint, so those three faulted runs are
fresh samples. One restart_scratch run on task 11 ended in `PlanRejected` after three plans; the same
resume reran it and it passed. The final set has 0 error results.

**Exact-diff columns are still uninformative at scale.** Clean-vs-clean floor by exact diff is
0.97 / 0.99 / 1.00 (findings / plan steps / executed steps) and exact `ignored` is 0.7% of 610
applied faults with twins. The judged columns are the ones to read.

**Cost and utility over runs whose fault applied** (means; `none` is the unrecovered pipeline):

| condition | utility | LLM calls | completion tokens | seconds | irreversible actions |
|---|---|---|---|---|---|
| none | 0.72 | 9.3 | 1,661 | 34 | 0.31 |
| restart_stage | 0.89 | 13.3 | 2,118 | 50 | 0.63 |
| restart_scratch | 0.94 | 18.0 | 3,119 | 65 | 0.61 |
| always_verify | 0.88 | 23.6 | 3,595 | 82 | 0.28 |

Clean runs pass at 0.85 to 0.90 in every condition, so the faults cost about 0.15 of utility and the
restart baselines recover almost all of it at 1.4 to 2 times the calls. Both restart baselines double
the irreversible-action count, because re-execution repeats the side-effecting steps the first attempt
already took and environment rollback hides that from the checker (see "Restart baselines and
environment rollback"). Token totals come from the `llm_call` events (`metrics.cost`). Wasted work:
restart_scratch discards 8.6 artifacts and spends 8.7 recovery calls per run, restart_stage discards
8.6 and spends 4.1 (the restart keeps the findings but the plan and executed steps are redone).

**Deviations from the proposal.** Note-entry faults (the third stage in the proposal's fault table)
have no templates and were not run. Reported runs use flash, not GLM 5.3, for the reason above.

**Judge (api-glm-5.3, 630 pairs, 1,397 LLM verdicts, 1,505 byte-identical pairs, about 1 h at 4
workers).** 29 verdicts first came back with no content because reasoning tokens exhausted the 4,096
budget; an error verdict is now retried on resume and the judge runs at 8,192, after which 0 remain.

Judged clean-vs-clean floor, mean over the 20 tasks: findings 0.56, plan steps 0.26, executed steps
0.24. Findings vary a lot between clean runs on several tasks (1.0 on tasks 11, 20, 36; 0.0 on tasks
4, 17, 18, 39), so finding-level propagation must be read per task against that task's floor.

Judged propagation over the 610 applied faults with twins: 30% of faults are ignored (no downstream
artifact changed in the judge's view), against 0.7% by exact diff.

| fault stage | ignored | under-taint (artifacts) | over-taint (artifacts) |
|---|---|---|---|
| finding | 0.41 | 0.64 | 0.54 |
| plan step | 0.20 | 0.13 | 0.22 |

Adversarial plan steps are never ignored (0/120) and `other` plan steps almost never (8%); the
accidental and `other` finding faults are ignored 39 to 63% of the time, i.e. the planner routinely
works around a corrupted finding. Utility is 0.90 when the fault was ignored and 0.64 when it
propagated. 22% of faulted runs have under-taint and 27% have over-taint under the judge; the
declared descendant set (citations) is therefore wrong in about half the runs where the fault
propagated, in both directions.

`data/judge_sample_phase1.csv`: 50 LLM-judged pairs (21 judged different, 29 same; 35 executed
steps, 13 plan steps, 2 findings), `hand_differs` empty, for the agreement check.

## Frozen fault templates (2026-10-21)

12 templates in `data/fault_templates/` (finding, plan_step x accidental, adversarial, other x obvious, subtle).
sha256 of the directory: `62a28fd8dfe1855d3800127012ef660ecc5f83f6a15928cd8f763e4719820f3f`. Templates are not edited after this point; a new grid is a new directory.

## Fault injection live check (2026-10-21, api-glm-5.3-flash, 2 tasks x 12 templates, condition none)

19 of 24 faults applied; the 5 that did not (regex with no match, stale copy with a single artifact)
are recorded as `fault_applied: false` and excluded. Twins forked for all 19. One adversarial plan
step landed: user_task_17 / plan_step_adversarial_subtle produced 1 unauthorized irreversible email.
Under-taint of 2 to 4 appears where the planner did not cite the faulted finding, but with exact diff
every downstream artifact counts as changed, so these numbers are upper bounds until the LLM judge
exists. `ignored` was never true for the same reason.

## Restart baselines and environment rollback

Restart-from-scratch and restart-from-stage restore the environment (to the pre-task state or to the
stage checkpoint), so emails already sent by a contaminated step disappear from the environment and
the task checker scores a clean world. The only record that harm occurred is the tool-action log:
`unauthorized_actions` and `irreversible_actions` count every action of the run, including those
before the restart. Baseline comparisons must read those counts, not the checker alone.
