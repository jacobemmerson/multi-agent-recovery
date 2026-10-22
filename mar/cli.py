"""Command line: `mar run <config>`, `mar aggregate`, `mar day1`."""

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

    agg = sub.add_parser("aggregate", help="runs/ -> parquet")
    agg.add_argument("--runs-dir", type=Path, default=Path("runs"))
    agg.add_argument("--out", type=Path, default=Path("runs/aggregate.parquet"))

    day1 = sub.add_parser("day1", help="clean single-agent runs: must pass before any fault work; probes throughput")
    day1.add_argument("--model", default="api-glm-5.3")
    day1.add_argument("--suite", default="workspace")
    day1.add_argument("--version", default="v1.2")
    day1.add_argument("--n", type=int, default=5)

    args = parser.parse_args(argv)
    {"run": _run, "aggregate": _aggregate, "day1": _day1}[args.command](args)


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
    raise NotImplementedError("mar run arrives with the experiment runner")


def _aggregate(args: argparse.Namespace) -> None:
    raise NotImplementedError("mar aggregate arrives with metrics.aggregate")
