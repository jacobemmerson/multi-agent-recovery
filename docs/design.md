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
