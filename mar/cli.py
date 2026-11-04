"""Command line: `mar run <config>`, `mar judge`, `mar aggregate`, `mar day1`."""

import argparse
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="mar")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run an experiment config")
    run.add_argument("config", type=Path)
    run.add_argument("--tasks", choices=["dev", "eval"], default="dev")
    run.add_argument("--resume", action="store_true")
    run.add_argument("--runs-dir", type=Path, default=Path("runs"))
    run.add_argument("--workers", type=int, default=1, help="concurrent jobs; TritonAI throughput saturates near 4")

    judge = sub.add_parser("judge", help="LLM-judge twin and clean-repeat pairs; writes judge.json per run")
    judge.add_argument("--runs-dir", type=Path, default=Path("runs"))
    judge.add_argument("--model", default="api-glm-5.3")
    judge.add_argument("--rejudge", action="store_true")
    judge.add_argument("--workers", type=int, default=1, help="concurrent pairs; TritonAI throughput saturates near 4")
    judge.add_argument("--sample", type=int, help="write N judged pairs as a CSV for hand labelling")
    judge.add_argument("--out", type=Path, default=Path("data/judge_sample.csv"))

    agg = sub.add_parser("aggregate", help="runs/ -> parquet")
    agg.add_argument("--runs-dir", type=Path, default=Path("runs"))
    agg.add_argument("--out", type=Path, default=Path("runs/aggregate.parquet"))

    day1 = sub.add_parser("day1", help="clean single-agent runs: must pass before any fault work; probes throughput")
    day1.add_argument("--model", default="api-glm-5.3")
    day1.add_argument("--suite", default="workspace")
    day1.add_argument("--version", default="v1.2")
    day1.add_argument("--n", type=int, default=5)

    args = parser.parse_args(argv)
    {"run": _run, "judge": _judge, "aggregate": _aggregate, "day1": _day1}[args.command](args)


def _day1(args: argparse.Namespace) -> None:
    from agentdojo.task_suite.load_suites import get_suite

    from mar.config import ModelConfig
    from mar.llm import OpenAICompatibleClient
    from mar.run import day1

    task_ids = list(get_suite(args.version, args.suite).user_tasks)[: args.n]
    llm = OpenAICompatibleClient.from_config(ModelConfig(name=args.model))
    rows = day1(task_ids, args.suite, llm, args.version)
    for row in rows:
        print(f"{row['task_id']:<14} {'PASS' if row['utility'] else 'FAIL'}  llm={row['llm_calls']:<3} tools={row['tool_calls']:<3} {row['seconds']:>6.1f}s" + ("  truncated" if row["truncated"] else ""))
    passed = sum(r["utility"] for r in rows)
    print(f"passed {passed}/{len(rows)}, mean {sum(r['seconds'] for r in rows) / len(rows):.1f}s, total llm calls {sum(r['llm_calls'] for r in rows)}")


def _run(args: argparse.Namespace) -> None:
    from mar.run import run_experiment

    run_experiment(args.config, args.tasks, args.runs_dir, args.resume, workers=args.workers)


def _judge(args: argparse.Namespace) -> None:
    from mar.config import ModelConfig
    from mar.judge import judge_runs, sample_for_hand_labels
    from mar.llm import OpenAICompatibleClient

    # 8192: GLM 5.3 reasoning tokens exhausted 4096 on long executed-step outputs and returned no content.
    llm = OpenAICompatibleClient.from_config(ModelConfig(name=args.model, max_tokens=8192))
    counts = judge_runs(args.runs_dir, llm, rejudge=args.rejudge, workers=args.workers)
    print(f"judged {counts['artifacts_judged']} artifacts across {counts['pairs']} pairs, {counts['identical']} identical, skipped {counts['skipped']} already judged")
    if args.sample:
        sample = sample_for_hand_labels(args.runs_dir, n=args.sample)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        sample.to_csv(args.out, index=False)
        print(f"wrote {len(sample)} pairs to {args.out}")


def _aggregate(args: argparse.Namespace) -> None:
    from mar.metrics import aggregate

    aggregate(args.runs_dir, args.out)
