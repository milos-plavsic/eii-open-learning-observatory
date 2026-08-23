"""Fail when owned modules or functions exceed their ratcheted size budgets."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]
DEFAULT_MODULE_LINES = 400
DEFAULT_FUNCTION_LINES = 120

# Existing debt is explicit and may only move downward. Removing an entry is the
# intended end state; raising a limit requires a reviewed architecture decision.
MODULE_DEBT = {
    "src/eii/appliance.py": 590,
    "src/eii/babelbridge.py": 436,
    "src/eii/cli.py": 558,
    "src/eii/safety.py": 523,
    "src/eii/study.py": 441,
}
FUNCTION_DEBT = {
    "src/eii/appliance.py:make_handler": 170,
    "src/eii/cli.py:main": 470,
    "src/eii/cli_parser.py:parser": 346,
    "src/eii/evidence.py:load_bundle": 190,
    "src/eii/safety.py:SafetyEvaluator.evaluate": 165,
    "src/eii/safety_verification.py:validate_safety_case_document": 200,
    "src/eii/study.py:make_study_handler": 124,
}


def qualified_name(parents: tuple[str, ...], name: str) -> str:
    return ".".join((*parents, name))


def check_file(path: Path) -> list[str]:
    relative = path.relative_to(ROOT).as_posix()
    lines = path.read_text("utf-8").splitlines()
    failures = []
    module_limit = MODULE_DEBT.get(relative, DEFAULT_MODULE_LINES)
    if len(lines) > module_limit:
        failures.append(f"{relative}: {len(lines)} module lines exceed {module_limit}")
    tree = ast.parse("\n".join(lines), filename=relative)

    def visit(nodes: list[ast.stmt], parents: tuple[str, ...] = ()) -> None:
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = qualified_name(parents, node.name)
                length = (node.end_lineno or node.lineno) - node.lineno + 1
                limit = FUNCTION_DEBT.get(f"{relative}:{name}", DEFAULT_FUNCTION_LINES)
                if length > limit:
                    failures.append(f"{relative}:{name}: {length} lines exceed {limit}")
                visit(node.body, (*parents, node.name))
            elif isinstance(node, ast.ClassDef):
                visit(node.body, (*parents, node.name))

    visit(tree.body)
    return failures


def main() -> None:
    failures = [
        failure
        for path in sorted((ROOT / "src" / "eii").rglob("*.py"))
        for failure in check_file(path)
    ]
    if failures:
        raise SystemExit("Maintainability budget failed:\n" + "\n".join(failures))
    print("Maintainability size ratchet passed")


if __name__ == "__main__":
    main()
