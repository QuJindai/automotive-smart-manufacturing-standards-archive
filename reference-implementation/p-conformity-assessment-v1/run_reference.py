#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from pcae.evaluator import validate_package
from pcae.output import write_outputs


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a P-CAE V1 conformity assessment package")
    parser.add_argument("--package", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    run = validate_package(Path(args.package))
    write_outputs(run, Path(args.out))
    for result in run.results:
        if result.result != "PASS":
            print(f"{result.test_id}={result.result} {result.reason}")
    print(f"CAE_REQUIRED_FAILURES={run.required_failures}")
    print(f"CAE_PASS={run.counts['PASS']}")
    print(f"CAE_FAIL={run.counts['FAIL']}")
    print(f"CAE_BLOCKED={run.counts['BLOCKED']}")
    print(f"CAE_OVERALL_DECISION={run.overall_decision}")
    print(f"CAE_LIFECYCLE_STATE={run.lifecycle_state}")
    return 1 if run.required_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
