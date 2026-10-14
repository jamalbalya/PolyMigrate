"""Fail-closed detection for Python intermediate expressions that print booleans differently."""
from __future__ import annotations
import ast

def _is_boolean_value(node: ast.AST, boolean_names: set[str]) -> bool:
    if isinstance(node, ast.Constant) and type(node.value) is bool:
        return True
    if isinstance(node, (ast.Compare, ast.BoolOp)):
        return True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return True
    return isinstance(node, ast.Name) and node.id in boolean_names

def _assigned_boolean_names(tree: ast.AST) -> set[str]:
    boolean_names: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            else:
                continue
            if not _is_boolean_value(value, boolean_names):
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in boolean_names:
                    boolean_names.add(target.id)
                    changed = True
    return boolean_names

def has_boolean_print_expression(tree: ast.AST) -> bool:
    """Detect boolean-valued expressions inside print arguments.

    Python intermediate translators may stringify booleans as True/False, while
    JavaScript console output uses true/false. Comparisons used solely as
    control-flow conditions remain allowed.
    """
    boolean_names = _assigned_boolean_names(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "print":
            continue
        for argument in node.args:
            if any(_is_boolean_value(part, boolean_names) for part in ast.walk(argument)):
                return True
    return False
