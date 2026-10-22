"""Evaluate bounded arithmetic expressions using an AST allowlist.

Only numeric literals, supported operators, and approved functions are allowed.
Expression length and exponents are bounded, and non-finite results are rejected.
"""

import ast
import math

from langchain_core.tools import Tool

from internal.shared import Module, logged


from cmd.api.tools.constants import (
    CALCULATOR_OPERATORS,
    CALCULATOR_UNARY_OPERATORS,
    CALCULATOR_FUNCTIONS,
    CALCULATOR_MAX_EXPRESSION_LENGTH,
    CALCULATOR_MAX_EXPONENT,
    CALCULATOR_DECIMAL_PLACES,
    CALCULATOR_MAX_EXACT_INTEGER,
    CALCULATOR_DESCRIPTION,
)


def _refusal(node: ast.AST) -> str:
    """Describe an unsupported expression node and the permitted arithmetic alternatives."""

    return (
        f"{ast.unparse(node)!r} is not arithmetic. The calculator takes numbers, "
        f"the operators + - * / // % ** and parentheses, and these functions: "
        f"{', '.join(sorted(CALCULATOR_FUNCTIONS))}"
    )


def _number(value: object) -> int | float:
    """Validate a real numeric input, rejecting booleans and unsupported values."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{value!r} is not a number the calculator can use")

    return value


def _real(result: object, node: ast.AST) -> int | float:
    """Validate that a computed result is real and finite."""

    if isinstance(result, complex):
        raise ValueError(f"{ast.unparse(node)!r} has no real number as its answer")

    if isinstance(result, float) and not math.isfinite(result):
        raise ValueError(f"{ast.unparse(node)!r} is too large a number to represent")

    return result


def _binary(node: ast.BinOp) -> int | float:
    """Apply an allowed binary operator with exponent and result validation."""

    left = _evaluate(node.left)
    right = _evaluate(node.right)

    if isinstance(node.op, ast.Pow) and abs(right) > CALCULATOR_MAX_EXPONENT:
        raise ValueError(
            f"an exponent above {CALCULATOR_MAX_EXPONENT} would not finish in "
            f"time, got {right!r}"
        )

    try:
        result = CALCULATOR_OPERATORS[type(node.op)](left, right)
    except ZeroDivisionError as exc:
        raise ValueError(f"{ast.unparse(node)!r} divides by zero") from exc
    except OverflowError as exc:
        raise ValueError(
            f"{ast.unparse(node)!r} is too large a number to represent"
        ) from exc

    return _real(result, node)


def _argument(node: ast.AST) -> int | float | list:
    """Evaluate a numeric argument or a list of numeric expressions for an allowed function."""

    if isinstance(node, (ast.List, ast.Tuple)):
        return [_evaluate(element) for element in node.elts]

    return _evaluate(node)


def _call(node: ast.Call) -> int | float:
    """Evaluate an allowed arithmetic function with validated arguments."""

    name = node.func.id if isinstance(node.func, ast.Name) else ast.unparse(node.func)

    if name not in CALCULATOR_FUNCTIONS:
        raise ValueError(
            f"{name!r} is not a function the calculator knows. It knows: "
            f"{', '.join(sorted(CALCULATOR_FUNCTIONS))}"
        )

    if node.keywords != []:
        raise ValueError(
            f"{name!r} takes its arguments in order, so {node.keywords[0].arg!r} "
            f"cannot be given by name"
        )

    try:
        result = CALCULATOR_FUNCTIONS[name](
            *[_argument(argument) for argument in node.args]
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(
            f"{ast.unparse(node)!r} could not be calculated: {exc}"
        ) from exc

    return _real(result, node)


def _evaluate(node: ast.AST) -> int | float:
    """Evaluate an expression recursively using the numeric AST allowlist."""

    if isinstance(node, ast.Constant):
        return _number(node.value)

    if isinstance(node, ast.UnaryOp) and type(node.op) in CALCULATOR_UNARY_OPERATORS:
        return CALCULATOR_UNARY_OPERATORS[type(node.op)](_evaluate(node.operand))

    if isinstance(node, ast.BinOp) and type(node.op) in CALCULATOR_OPERATORS:
        return _binary(node)

    if isinstance(node, ast.Call):
        return _call(node)

    if isinstance(node, ast.Name):
        raise ValueError(f"{node.id!r} is not a number the calculator knows")

    raise ValueError(_refusal(node))


def _parse_expression(expression: str | None) -> str:
    """Validate and trim the arithmetic expression within the length limit."""

    if not isinstance(expression, str) or expression.strip() == "":
        raise ValueError(
            f"The expression must be the arithmetic to calculate, got {expression!r}."
        )

    expression = expression.strip()

    if len(expression) > CALCULATOR_MAX_EXPRESSION_LENGTH:
        raise ValueError(
            f"The expression must be at most {CALCULATOR_MAX_EXPRESSION_LENGTH} "
            f"characters, got {len(expression)}."
        )

    return expression


def _format_result(value: int | float) -> str:
    """Format a finite result with bounded decimal precision and exact integer handling."""

    if isinstance(value, int):
        return str(value)

    value = round(value, CALCULATOR_DECIMAL_PLACES)

    if value.is_integer() and abs(value) < CALCULATOR_MAX_EXACT_INTEGER:
        return str(int(value))

    return repr(value)


@logged(Module.TOOL, "calculator")
def _calculate(expression: str | None = "") -> str:
    """Parse and evaluate a bounded arithmetic expression and return its formatted result."""

    text = _parse_expression(expression)

    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ValueError(
            f"{expression!r} is not an expression the calculator can read: {exc.msg}. "
            f"Send the arithmetic alone, with no words around it."
        ) from exc

    try:
        value = _evaluate(tree.body)
    except ValueError as exc:
        raise ValueError(f"{expression!r} could not be calculated: {exc}.") from exc

    return _format_result(value)


def get_calculator_tools() -> list[Tool]:
    """Return the bounded arithmetic tool available to agents."""

    return [
        Tool(
            name="calculator",
            description=CALCULATOR_DESCRIPTION,
            func=_calculate,
        )
    ]
