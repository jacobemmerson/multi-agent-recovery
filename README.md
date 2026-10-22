# multi-agent-recovery

Provenance-gated recovery in multi-agent LLM workflows. CSE 291A project; see
[docs/proposal.md](docs/proposal.md) and [docs/design.md](docs/design.md).

## Quickstart

```sh
cp .env.example .env        # fill in TRITONAI_API_KEY
uv sync
uv run pytest
uv run mar --help
```

## Layout

- `mar/` the package: `llm`, `env`, `artifacts`, `agents`, `notes`, `faults`, `recovery`, `run`, `judge`, `metrics`, `cli`
- `configs/` task splits and the Phase 1 / Phase 2 experiment grids
- `data/fault_templates/` frozen fault templates (hashed into every run manifest)
- `data/labels/` hand-labeled sample for the artifact judge
- `scripts/` TAMAS adaptation, plots
- `runs/` one directory per run (gitignored)
