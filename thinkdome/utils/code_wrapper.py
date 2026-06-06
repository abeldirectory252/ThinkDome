"""Code wrapping utilities for interactive mode."""

import ast
import textwrap


def wrap_last_expression(code: str) -> str:
    """
    If last_line_interactive is True, wrap the code so the last expression
    is printed automatically (mimicking REPL behavior).
    """
    code = code.rstrip()
    if not code:
        return code

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code

    if not tree.body:
        return code

    last_node = tree.body[-1]

    if isinstance(last_node, ast.Expr):
        # Replace the last expression with a print() call
        lines = code.split("\n")
        # Find the line range of the last expression
        last_line_start = last_node.lineno - 1
        last_line_end = getattr(last_node, "end_lineno", last_node.lineno)

        before = lines[:last_line_start]
        expr_lines = lines[last_line_start:last_line_end]
        expr_code = "\n".join(expr_lines).strip()

        wrapped = f"__thinkbox_result__ = ({expr_code})\nif __thinkbox_result__ is not None:\n    print(__thinkbox_result__)"

        before.append(wrapped)
        return "\n".join(before)

    return code
