"""Safe, numpy-vectorised evaluation of user-typed channel expressions.

Backs the channel editor's 自定义表达式 row: the user types something like
``sqrt(A^2 + B^2) * 0.5`` and gets a new channel. ``eval()`` is never used —
the string is parsed with :mod:`ast` and walked through a strict node/name
whitelist, so an expression can only do arithmetic on the variables it is
handed and call the functions listed in :data:`FUNCTIONS`.

Everything here is pure numeric (no PyQt5 / matplotlib import), per the
``mf4_analyzer/signal`` boundary enforced by
``tests/test_signal_no_gui_import.py``.
"""
from __future__ import annotations

import ast

import numpy as np

__all__ = [
    "ExpressionError",
    "CONSTANTS",
    "FUNCTIONS",
    "normalize",
    "referenced_names",
    "evaluate",
]

# An expression is a one-liner typed into a narrow input; these caps exist to
# keep a pathological paste (deeply nested, or ``9**9**9``) from burning CPU
# inside the GUI thread, not as a security boundary (the whitelist is that).
MAX_LENGTH = 2000
MAX_NODES = 400
MAX_POW_EXPONENT = 1024


class ExpressionError(ValueError):
    """Raised for anything the user can fix by editing the expression."""


def _min(*args):
    """``min(A)`` → scalar minimum; ``min(A, B, ...)`` → elementwise."""
    if len(args) == 1:
        return np.min(args[0])
    out = args[0]
    for other in args[1:]:
        out = np.minimum(out, other)
    return out


def _max(*args):
    if len(args) == 1:
        return np.max(args[0])
    out = args[0]
    for other in args[1:]:
        out = np.maximum(out, other)
    return out


def _rms(x):
    x = np.asarray(x, dtype=float)
    if x.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(x))))


CONSTANTS = {
    "pi": np.pi,
    "e": np.e,
    "inf": np.inf,
    "nan": np.nan,
}

#: Whitelisted callables. Keys are what the user types (lower-case lookup, so
#: ``SQRT`` works too). Elementwise unless noted.
FUNCTIONS = {
    # elementwise
    "sqrt": np.sqrt,
    "cbrt": np.cbrt,
    "abs": np.abs,
    "exp": np.exp,
    "log": np.log,
    "ln": np.log,
    "log2": np.log2,
    "log10": np.log10,
    "sin": np.sin,
    "cos": np.cos,
    "tan": np.tan,
    "asin": np.arcsin,
    "acos": np.arccos,
    "atan": np.arctan,
    "atan2": np.arctan2,
    "sinh": np.sinh,
    "cosh": np.cosh,
    "tanh": np.tanh,
    "sign": np.sign,
    "floor": np.floor,
    "ceil": np.ceil,
    "round": np.round,
    "clip": np.clip,
    "hypot": np.hypot,
    "deg": np.degrees,
    "degrees": np.degrees,
    "rad": np.radians,
    "radians": np.radians,
    "where": np.where,
    "cumsum": np.cumsum,
    "min": _min,
    "max": _max,
    # whole-signal scalars (useful for de-biasing / normalising)
    "mean": np.mean,
    "median": np.median,
    "std": np.std,
    "sum": np.sum,
    "rms": _rms,
}

_BIN_OPS = {
    ast.Add: np.add,
    ast.Sub: np.subtract,
    ast.Mult: np.multiply,
    ast.Div: np.divide,
    ast.FloorDiv: np.floor_divide,
    ast.Mod: np.mod,
    ast.Pow: np.power,
    ast.BitAnd: np.logical_and,   # boolean masks: (A > 0) & (B < 1)
    ast.BitOr: np.logical_or,
}

_CMP_OPS = {
    ast.Lt: np.less,
    ast.LtE: np.less_equal,
    ast.Gt: np.greater,
    ast.GtE: np.greater_equal,
    ast.Eq: np.equal,
    ast.NotEq: np.not_equal,
}

_UNARY_OPS = {
    ast.UAdd: lambda v: +v,
    ast.USub: lambda v: -v,
    ast.Invert: np.logical_not,
}

# Typographic characters users paste in from the UI labels / docs, mapped to
# their Python equivalents. ``^`` is power here (engineering convention), not
# bitwise xor — xor on float channels is meaningless, so nothing is lost.
_SUBSTITUTIONS = {
    "^": "**",
    "×": "*",
    "·": "*",
    "÷": "/",
    "−": "-",
    "–": "-",
    "π": "pi",
    "（": "(",
    "）": ")",
    "，": ",",
    "　": " ",
}


def normalize(expr: str) -> str:
    """Rewrite engineering/full-width notation into Python syntax."""
    text = str(expr)
    for src, dst in _SUBSTITUTIONS.items():
        text = text.replace(src, dst)
    return text


def _parse(expr: str) -> ast.Expression:
    text = normalize(expr).strip()
    if not text:
        raise ExpressionError("表达式为空")
    if len(text) > MAX_LENGTH:
        raise ExpressionError(f"表达式过长（上限 {MAX_LENGTH} 字符）")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"表达式语法错误：{exc.msg}") from exc
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise ExpressionError("表达式过于复杂，请拆成多个通道分步计算")
    return tree


def referenced_names(expr: str) -> set:
    """Names the expression reads, excluding called functions and constants.

    Used by the UI to know which channels an expression actually needs (so an
    ``A``-only expression is not rejected because ``B`` has a different
    length).
    """
    tree = _parse(expr)
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    return {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and node.id not in called
        and node.id.lower() not in CONSTANTS
    }


def _lookup(name: str, variables, lowered):
    if name in variables:
        return variables[name]
    key = name.lower()
    if key in lowered:
        return lowered[key]
    if key in CONSTANTS:
        return CONSTANTS[key]
    available = ", ".join(sorted(variables)) or "无"
    raise ExpressionError(f"未知变量 “{name}”（可用变量：{available}）")


def _resolve_function(name: str):
    func = FUNCTIONS.get(name) or FUNCTIONS.get(name.lower())
    if func is None:
        raise ExpressionError(f"不支持的函数 “{name}”")
    return func


def _eval_node(node, variables, lowered):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, variables, lowered)

    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or isinstance(node.value, (int, float)):
            return node.value
        raise ExpressionError("表达式只能包含数字常量")

    if isinstance(node, ast.Name):
        return _lookup(node.id, variables, lowered)

    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise ExpressionError("不支持的一元运算符")
        return op(_eval_node(node.operand, variables, lowered))

    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise ExpressionError("不支持的运算符")
        if isinstance(node.op, ast.Pow):
            _check_exponent(node.right)
        left = _eval_node(node.left, variables, lowered)
        right = _eval_node(node.right, variables, lowered)
        return op(left, right)

    if isinstance(node, ast.Compare):
        if len(node.ops) != 1:
            raise ExpressionError("暂不支持链式比较，请用 & / | 组合")
        op = _CMP_OPS.get(type(node.ops[0]))
        if op is None:
            raise ExpressionError("不支持的比较运算符")
        left = _eval_node(node.left, variables, lowered)
        right = _eval_node(node.comparators[0], variables, lowered)
        return op(left, right)

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ExpressionError("只能调用内置函数")
        if node.keywords:
            raise ExpressionError("函数调用不支持关键字参数")
        if any(isinstance(a, ast.Starred) for a in node.args):
            raise ExpressionError("函数调用不支持 * 展开")
        func = _resolve_function(node.func.id)
        args = [_eval_node(a, variables, lowered) for a in node.args]
        if not args:
            raise ExpressionError(f"函数 “{node.func.id}” 至少需要一个参数")
        try:
            return func(*args)
        except ExpressionError:
            raise
        except TypeError as exc:
            raise ExpressionError(f"函数 “{node.func.id}” 参数数量或类型不对") from exc

    if isinstance(node, ast.BoolOp):
        raise ExpressionError("请用 & / | 代替 and / or")

    if isinstance(node, ast.IfExp):
        raise ExpressionError("请用 where(条件, 值1, 值2) 代替 if/else")

    raise ExpressionError("表达式中含不支持的语法")


def _check_exponent(node):
    """Reject ``2 ** 10_000_000`` style literals before numpy sees them."""
    value = None
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        value = node.value
    elif (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, (ast.USub, ast.UAdd))
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, (int, float))
    ):
        value = node.operand.value
    if value is not None and abs(value) > MAX_POW_EXPONENT:
        raise ExpressionError(f"指数过大（上限 {MAX_POW_EXPONENT}）")


def evaluate(expr: str, variables, size=None):
    """Evaluate ``expr`` against ``variables`` and return a float array.

    ``variables`` maps names (e.g. ``{"A": arr, "B": arr, "t": time}``) to
    array-likes. ``size`` — when given, a scalar result is broadcast to that
    length and a mismatched array length is rejected, so the caller always
    gets a channel-shaped array.

    Non-finite results (``inf`` from a divide-by-zero, ``nan`` from
    ``sqrt(-1)``) are normalised to ``nan`` so plotting breaks the line
    instead of collapsing the axis range.
    """
    tree = _parse(expr)
    lowered = {str(k).lower(): v for k, v in variables.items()}
    with np.errstate(all="ignore"):
        result = _eval_node(tree, variables, lowered)
        try:
            arr = np.asarray(result, dtype=float)
        except (TypeError, ValueError) as exc:
            raise ExpressionError("表达式结果不是数值") from exc
        if arr.ndim > 1:
            raise ExpressionError("表达式结果必须是一维信号")
        if size is not None:
            if arr.ndim == 0:
                arr = np.full(int(size), float(arr))
            elif arr.size != int(size):
                raise ExpressionError(
                    f"表达式结果长度 {arr.size} 与通道长度 {int(size)} 不一致"
                )
        arr = np.array(arr, dtype=float, copy=True)
        arr[~np.isfinite(arr)] = np.nan
    return arr
