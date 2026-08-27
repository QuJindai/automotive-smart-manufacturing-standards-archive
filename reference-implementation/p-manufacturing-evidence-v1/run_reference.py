#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from pme.output import write_outputs
from pme.validator import validate_package


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a P-ME V1 manufacturing evidence package")
    parser.add_argument("--package", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    run = validate_package(Path(args.package))
    write_outputs(run, Path(args.out))
    for result in run.results:
        if result.result != "PASS":
            print(f"{result.test_id}={result.result} {result.reason}")
    print(f"ME_REQUIRED_FAILURES={run.required_failures}")
    print(f"ME_PASS={run.counts['PASS']}")
    print(f"ME_FAIL={run.counts['FAIL']}")
    print(f"ME_BLOCKED={run.counts['BLOCKED']}")
    return 1 if run.required_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
