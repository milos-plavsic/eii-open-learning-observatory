#!/usr/bin/env python3
"""Run every unittest in deterministic shuffled order for flakiness hunting."""

from __future__ import annotations

import argparse
import random
import unittest


def iter_cases(suite: unittest.TestSuite) -> list[unittest.TestCase]:
    cases: list[unittest.TestCase] = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            cases.extend(iter_cases(item))
        else:
            cases.append(item)
    return cases


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    cases = iter_cases(unittest.defaultTestLoader.discover("tests", pattern="test_*.py"))
    random.Random(args.seed).shuffle(cases)
    result = unittest.TextTestRunner(verbosity=1).run(unittest.TestSuite(cases))
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
