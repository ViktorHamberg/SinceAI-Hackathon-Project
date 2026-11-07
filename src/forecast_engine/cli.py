"""Thin local command adapter; application callers continue to use the Python API."""

import argparse
from pathlib import Path
import sys

from .evaluation import WorkflowError, run_workflow


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # Unknown argument values might be secrets; do not echo them to logs.
        self.exit(2, "Invalid command arguments; use --help for supported options.\n")


def main(argv=None) -> int:
    parser = _Parser(description="Run reproducible local forecasts with the unchanged official tools.")
    commands = parser.add_subparsers(dest="mode", required=True)
    for mode in ("validation", "test"):
        command = commands.add_parser(mode)
        command.add_argument("--starter-dir", type=Path, default=Path("."), help="Starter package directory (default: current directory).")
        command.add_argument("--data-dir", type=Path, help="Defaults to STARTER_DIR/data.")
        command.add_argument("--output-dir", type=Path, help="New/empty directory; defaults to STARTER_DIR/baseline_output/engine/MODE.")
        command.add_argument("--inputs-file", type=Path, help="Explicit CSV/Parquet override; default DATA_DIR/inputs.csv.")
        command.add_argument("--spot-file", type=Path, help="Default DATA_DIR/spot_nordpool.csv.")
        if mode == "validation":
            command.add_argument("--actuals-file", type=Path, help="Scoring only; default DATA_DIR/actuals_validation.csv.")
    arguments = list(sys.argv[1:] if argv is None else argv)
    options = parser.parse_args(arguments)
    try:
        manifest = run_workflow(**vars(options), argv=arguments)
    except WorkflowError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as error:
        print(f"ERROR: workflow initialization or manifest write failed ({type(error).__name__}).", file=sys.stderr)
        return 1
    print(f"Completed {options.mode}: {manifest['origin_count']} origins, {manifest['forecast_rows']} rows.")
    print(f"Run manifest: {manifest['artifacts']['manifest']}")
    return 0
