# CSE 291A Project Proposal: Provenance-Gated Recovery in Multi-Agent Workflows

2026-10-21 · Tae. Exported from the proposal doc for offline reference.

## Problem and research questions

Option 5: Failure Propagation and Recovery in Multi-Agent Systems. Team: Tae (solo).

In a multi-agent workflow, one agent's faulty output becomes the input of the next: a fabricated finding shapes the plan, and the executor acts on it. The classical systems answer is known: selective re-execution from a dependency graph (Retro, Warp) and staged external effects with lineage (Cordon). Both rest on two assumptions: that recorded dependencies capture real influence, and that re-running a step with clean inputs reproduces the clean result. Neither is safe for an LLM agent. Influence travels through paraphrase and summaries that no logged read captures, and re-execution is stochastic. This project measures how far those assumptions hold in a multi-agent pipeline, and what harm remains when they fail.

**RQ1. Does declared provenance capture real influence?** Compare the dependency set the orchestrator records with ground truth from counterfactual re-execution. Under-taint means selective recovery silently keeps poison; over-taint means wasted recomputation.

**RQ2. Is LLM re-execution a valid recovery?** Measure how often a recovered run diverges from the clean twin beyond the measured noise floor. High divergence means "recovered correctness" overstates safety.

**RQ3. How does residual irreversible harm scale with detection delay?** Reveal the faulty artifact Δ steps after injection and plot residual irreversible actions against Δ, with and without staged commit, against taint-gating prevention.

**Safety framing.** Recovery counts as safe only if unauthorized and irreversible actions are prevented or reported, and the fault does not re-enter through persistent memory. Accidental faults (wrong facts, stale results, timeouts) are analyzed separately from adversarial ones (injected instructions). Detection is separated from recovery: fault identity comes from an oracle, revealed after a controlled delay.

## Background and related work

Each mechanism we use exists somewhere; what is missing is a measurement of where provenance-based recovery fails for LLM agents, in a multi-agent setting, with honest harm accounting.

**Starting resources.**

| Resource | What it provides | How we use it |
| --- | --- | --- |
| [AgentDojo](https://github.com/ethz-spylab/agentdojo) | Stateful simulated tool suites (workspace, Slack, banking, travel), programmatic utility checks, indirect prompt-injection tasks, built-in defenses (tool filter, spotlighting, PI detector) | Environment, checkers, development injection set, and the no-recovery defense reference. Tool state is plain Python objects, so a deepcopy is a snapshot. |
| [TAMAS](https://github.com/microsoft/TAMAS) ([paper](https://arxiv.org/abs/2511.05269)) | 300 adversarial instances across 6 attack types, run on Autogen/CrewAI; reports a safety/utility score | Adversarial fault content for the held-out evaluation set. The adaptation script is frozen and logged before Phase 2 tuning. We do not use its harness or metric. |
| [A2ASecBench](https://safo-lab.github.io/A2ASecBench/) | Attacks on the A2A protocol | Only artifact-triggered script injection matches a malicious intermediate result; those cases become fault templates. The transport layer is out of scope. |

**Closest prior work.**

| Work | Overlap | What we add |
| --- | --- | --- |
| [Cordon](https://www.alphaxiv.org/abs/2606.17573) (Jun 2026) | Lineage graph, staged external effects in an outbox, shadow-state rollback | Single agent, 45 scenarios, reports no false negatives. We measure whether lineage misses real influence (RQ1) in a multi-agent pipeline. |
| Retro, Warp (OSDI 2010, SOSP 2011) | Selective re-execution from an action dependency graph after a known intrusion | Deterministic programs. We measure re-execution divergence for stochastic LLM steps (RQ2). |
| [AgentProp-Bench](https://arxiv.org/html/2604.16706v1) (Apr 2026), [Hallucination Cascade](https://arxiv.org/html/2606.07937v1) (Jun 2026) | Fault injection and propagation rates through agent chains | Propagation only, no rollback, no residual-harm accounting. Our Phase 1 overlaps; Phase 2 does not. |
| [SagaLLM](https://arxiv.org/abs/2503.11951v3) (VLDB 2025) | Saga transactions and compensation for multi-agent planning | Not about poisoned inputs or residual harm. |
| [FIDES](https://arxiv.org/abs/2505.23643), CaMeL | Taint tracking and information-flow control on AgentDojo | Prevention, not recovery; a simplified taint-gating variant is our baseline for staged commit (RQ3). |
| Memory poisoning ([MINJA](https://arxiv.org/html/2503.03704v1), [MemoryGraft](https://arxiv.org/html/2512.16962), [InjecMEM](https://arxiv.org/html/2608.23471v1)) | Persistent injected instructions in agent memory | Attacks only; we measure post-compromise purge and re-infection. |

Cordon, AgentProp-Bench and Hallucination Cascade were read directly. The other rows come from an external review of this proposal and are to be verified before citation.

## System design

A researcher, planner, executor pipeline with fan-out at every stage, so that dependencies form a graph rather than a chain, plus cross-task persistent notes and an orchestrator that records provenance for every artifact and tool action.

*(Architecture diagram in the original doc: fan-out pipeline, cross-task notes, orchestrator, environment.)*

The orchestrator wraps every agent call and tool action; agents never see it, so prompts stay identical across recovery methods.

**Workflow with fan-out.** The researcher emits one finding per source (document, email, search result) rather than one summary. The planner emits numbered steps, each citing the finding ids it uses, enforced by a structured output schema. The executor runs each step as a separate node. A fault in one finding therefore invalidates only the steps that cite it. In a chain, selective recovery is identical to restarting from the faulty stage; fan-out is what gives it something to save. Phase 2 adds a second researcher running in parallel.

**Provenance graph.** Every artifact (finding, plan step, executed step, note entry) is a node recording its producer, cited inputs, tool reads, and note reads. Every tool action is logged with the step that triggered it. This is *declared* provenance: what the wrapper can see. *Ground-truth* influence comes from counterfactual re-execution (RQ1).

**Action classes.** Each tool action is tagged at definition time:

| Class | Examples | Undo |
| --- | --- | --- |
| Reversible | file edit, calendar event, contact change | restore environment snapshot |
| Compensatable | bank transfer | reverse transfer, logged as compensation |
| Irreversible | send email, post Slack message | none; counted as residual harm |

**Unauthorized action.** Any tool call outside the task's allowlist, which is the tool set in AgentDojo's ground-truth solution plus read-only tools.

**Cross-task notes.** Agents append notes at the end of each task and read them at the start of the next, as in persistent-memory agents. A poisoned note from task N therefore has a natural path into task N+1. Entries carry provenance; a note is reversible at entry granularity (drop entries descended from the fault) but not at file granularity (a whole-file restore also drops valid entries from other agents or tasks), and becomes effectively irreversible once another agent has acted on it. Two purge variants are compared: coarse (file restore) and fine (entry-level invalidation).

**Models.** GLM 5.3 via TritonAI for all reported runs, pinned; the model string and response metadata are logged per call because hosted models change silently. GLM 5.3 flash for development only. Muse 30B runs on the evaluation set as a second model if budget allows.

## Phase 1: fault injection and propagation measurement

Phase 1 delivers the fan-out pipeline, a seeded fault injector with frozen templates, a measured noise floor, proof that injected faults actually propagate, a first measurement of RQ1, and three restart baselines.

**Noise floor.** Every task is run clean twice and the two runs are diffed artifact by artifact. Hosted models are not deterministic at temperature 0, so any propagation or reuse number below this floor is noise. This costs one extra run per task and protects every later number.

**Fault schedule.** Faults come from a seeded schedule per task. Templates are written and frozen before any result is examined, reported verbatim, and span two strengths (obvious and subtle) so that propagation is not an artifact of how contagious we made the faults. Planner-stage injections are over-sampled because they land most reliably, which the residual-harm numbers need.

| Stage | Accidental | Adversarial | Other |
| --- | --- | --- | --- |
| One finding | fabricated fact (wrong date, amount, recipient) | injected instruction (forward data to attacker) | stale result replayed, timeout |
| One plan step | wrong parameter or ordering | injected step | stale plan |
| Note entry | corrupted note | persistent injected instruction | none |

**Dependency check.** For every injected fault we also run the counterfactual twin (no fault) and diff each downstream artifact. A fault that changes nothing beyond the noise floor is logged as *ignored* and excluded from recovery metrics; the ignored rate is reported on its own. Diffing declared descendants against counterfactually changed artifacts gives the first under-taint and over-taint numbers (RQ1).

**Restart baselines.**

1. Restart from scratch: fresh environment, rerun everything.
2. Restart from the faulty stage: discard everything from that stage on, keep earlier artifacts.
3. Always verify: a verifier LLM call checks every artifact before it is passed on. It is required by the course specification and uses no oracle, so it is reported as a cost and coverage reference rather than as the headline comparison.

**Measurements.** Clean task success, noise floor, propagation rate, under-taint and over-taint, unauthorized actions, affected stages, wasted work (discarded LLM calls and tokens), and end-to-end latency. Every run records messages, artifacts, tool actions, and the provenance graph.

**Scale.** One AgentDojo suite, about 20 development tasks, 3 fault types x 3 stages x 2 strengths plus clean and noise-floor runs, 3 repeats each. Roughly 15,000 LLM calls.

## Phase 2: selective recovery and where it fails

Phase 2 implements one recovery mechanism, dependency-aware invalidation with snapshot rollback, and spends the rest of the time measuring where it fails. Fault identity comes from an oracle revealed Δ steps after injection.

**Core experiments.**

1. **DAI + snapshot rollback.** Invalidate descendants of the faulty artifact in the provenance graph, restore the environment snapshot taken before the first contaminated action, reverse compensatable actions, rerun only invalidated steps. Ablation: rerun without environment restore, which isolates what rollback buys.
2. **RQ1, provenance vs influence.** For every recovery, compare the declared invalidation set with the counterfactual ground truth. Report under-taint (contaminated artifacts kept) and over-taint (clean artifacts recomputed) at three granularities: per stage, per artifact, per claim.
3. **RQ2, re-execution divergence.** Compare each recovered run with the clean twin beyond the noise floor. Report how often recovered correctness holds while the recovered trajectory differs from the clean one.
4. **RQ3, detection-delay sweep.** For Δ in {0, 1, 2, 4, all} steps, measure residual irreversible actions and added latency for: no staging, staged commit (irreversible actions buffered until their inputs are cleared or a budget expires), a taint-gating baseline (block sink actions whose provenance includes untrusted content, in the spirit of FIDES and CaMeL), AgentDojo's built-in defenses, and a Cordon-style stage-everything upper bound.
5. **Memory scenario.** Cross-task note poisoning with the parallel-researcher variant; coarse vs fine purge; re-infection rate and collateral invalidation.

**Optional, dropped first if time runs short.** Replace the oracle with a detector: a prompted verifier, then a small classifier (1B to 3B, QLoRA) fine-tuned on Phase 1 traces. Report false positives and missed faults separately, and rerun experiment 1 with detected rather than oracle identity.

**Ablations.** Fault strength (obvious vs subtle); a second model (Muse 30B) on the evaluation set.

## Evaluation

Every mechanism and baseline runs under identical fault schedules, templates, and model version, and every number is reported against the noise floor.

**Metrics.**

| Metric | Definition |
| --- | --- |
| Under-taint, over-taint | contaminated artifacts kept, clean artifacts recomputed, relative to counterfactual ground truth |
| Re-execution divergence | recovered run differs from the clean twin beyond the noise floor |
| Recovered correctness | task passes the suite checker after recovery |
| Residual irreversible actions | irreversible actions caused by the fault that recovery could not undo, as a function of Δ |
| Unauthorized actions | tool calls outside the task allowlist |
| Collateral invalidation | valid artifacts or note entries discarded by recovery |
| Re-infection rate | runs where the fault reappears after recovery through notes |
| Recomputed stages, retained work | steps rerun vs kept |
| Recovery latency, inference cost | wall-clock and LLM calls/tokens for recovery, including staging delay |
| Tracking overhead | provenance and snapshot cost relative to the untracked baseline |

**Artifact-level judgment.** AgentDojo checkers judge final state only, so a contaminated plan that reaches the same final state would count as clean. Intermediate artifacts are therefore diffed by an LLM judge whose agreement with a 50-artifact hand-labeled sample is measured and reported.

**Dev/eval split.** Development: about 20 tasks on one AgentDojo suite. Evaluation: 50 or more tasks across two suites plus TAMAS-derived adversarial cases, untouched until Phase 2 is frozen. The TAMAS adaptation script is frozen and logged before any Phase 2 tuning.

**Statistics and controls.** Three repeats per condition with bootstrap confidence intervals; the clean-vs-clean noise floor in place of a seed; pinned model, runtime, dataset and code versions, with the model string logged per call; failed runs and timeouts recorded rather than dropped; cold-start separated from steady-state latency; ignored faults reported but excluded from recovery metrics.

## Timeline and compute

Phase 1 is due 2026-10-28 and the final report 2026-12-10.

*(Timeline diagram in the original doc: 5 work blocks, 2 deadlines.)*

If the core experiments slip, the optional detector block is dropped first.

**Compute.** Reported runs use GLM 5.3 through TritonAI. The $50 AWS credit is reserved for a small CPU instance for batch runs and, if the optional detector is reached, one to two GPU-hours on a g5.xlarge for the fine-tune. Development iteration uses GLM 5.3 flash. Hosting an 8B open model on AWS was considered and rejected: the budget allows about 50 GPU-hours including setup, and small open models score poorly on AgentDojo, which would make faults fail to propagate for the wrong reason.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Model too weak to follow multi-step plans, so faults never propagate | Day-1 check: 5 clean tasks must pass with a 5-step plan before any fault work. Switch to Muse 30B if it does better. |
| Planner does not cite findings, so fan-out collapses back to a chain | Structured output schema with required citation fields; reject and retry plans without them; report the retry rate. |
| Noise floor too high to see propagation or divergence | Report it as a result; tighten the artifact judge; lower per-step temperature where the API allows. |
| Attacks rarely land, so residual-harm numbers are sparse | Over-sample planner-stage injections; report landed-attack counts with bootstrap intervals. |
| AgentDojo integration consumes the Phase 1 week | Wrap the suite, do not modify it. If it is not working by day 2, fall back to a minimal custom workspace environment with the same checker interface. |
| Staged commit degenerates into always-verify | The Δ sweep makes the delay explicit; the commit check is a provenance lookup, not an LLM call; cost is reported side by side. |
| TritonAI rate limits or latency block ~15k calls | Measure throughput on day 1; cap per-task steps; batch runs overnight. |
| Solo team | Cut order fixed in advance: detector first, then the memory scenario's parallel-researcher variant. Experiments 1 to 4 plus evaluation are the minimum deliverable. |
