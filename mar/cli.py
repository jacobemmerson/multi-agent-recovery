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

    sub.add_parser("day1", help="5 clean tasks must pass with a 5-step plan; probe throughput")

    args = parser.parse_args(argv)
    raise NotImplementedError(args.command)
