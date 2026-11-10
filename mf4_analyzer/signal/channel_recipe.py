"""Serializable channel-edit recipes and the one function that evaluates them.

Pure numeric: no PyQt5 and no pandas. The channel editor and project restore
both call :func:`evaluate_derive`, so a saved recipe replays the same
arithmetic the user saw at creation time.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .channel_math import ChannelMath
from .expression import ExpressionError, check_channel_expression

SINGLE_FNS = frozenset({
    "derivative", "integral", "scale", "offset", "moving_avg", "abs",
})
DUAL_FNS = frozenset({"add", "sub", "mul", "div", "max", "min"})
_DUAL_IMPL = {
    "add": ChannelMath.add,
    "sub": ChannelMath.sub,
    "mul": ChannelMath.mul,
    "div": ChannelMath.div,
    "max": ChannelMath.maximum,
    "min": ChannelMath.minimum,
}
_TIME_FNS = frozenset({"derivative", "integral"})


class RecipeError(ValueError):
    """A recipe cannot be evaluated. ``code`` is a stable reason, not UI copy."""

    def __init__(self, code, detail=""):
        self.code = str(code)
        super().__init__(detail or self.code)


def _text(value, label):
    if not isinstance(value, str):
        raise RecipeError("unrecognized", f"{label} 必须是字符串")
    text = value.strip()
    if not text:
        raise RecipeError("unrecognized", f"{label} 不能为空")
    return text


def _unit(value):
    if not isinstance(value, str):
        raise RecipeError("unrecognized", "unit 必须是字符串")
    return value


def _finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RecipeError("unrecognized", "参数必须是有限数值")
    number = float(value)
    if not np.isfinite(number):
        raise RecipeError("unrecognized", "参数必须是有限数值")
    return number


def _window(value):
    number = _finite_number(value)
    if not number.is_integer() or number < 3:
        raise RecipeError("unrecognized", "滑动平均窗长必须是不小于 3 的整数")
    return int(number)


def _reject_unknown(raw, allowed):
    unknown = sorted(set(raw) - set(allowed))
    if unknown:
        raise RecipeError("unrecognized", f"无法识别的字段: {', '.join(unknown)}")


def _vector(value, code="non_numeric"):
    try:
        if np.iscomplexobj(value):
            raise RecipeError(code)
        arr = np.asarray(value, dtype=float)
    except RecipeError:
        raise
    except (TypeError, ValueError, OverflowError) as exc:
        raise RecipeError(code) from exc
    if arr.ndim != 1:
        raise RecipeError(code)
    return np.array(arr, dtype=float, copy=True)


def _time_axis(time, size):
    if time is None:
        raise RecipeError("time_unavailable")
    try:
        axis = _vector(time, "time_unavailable")
    except RecipeError as exc:
        if exc.code == "non_numeric":
            raise RecipeError("time_unavailable") from exc
        raise
    if axis.size != int(size):
        raise RecipeError("length_mismatch")
    if not np.isfinite(axis).all():
        raise RecipeError("time_unavailable")
    return axis


@dataclass(frozen=True)
class DeriveEntry:
    name: str
    unit: str
    kind: str
    fn: str | None = None
    src: str | None = None
    param: float | int | None = None
    a: str | None = None
    b: str | None = None
    expr: str | None = None

    def inputs(self) -> tuple[str, ...]:
        if self.kind == "single":
            return (self.src,)
        if self.kind == "dual":
            return (self.a, self.b)
        names = []
        if self.a:
            names.append(self.a)
        if self.b:
            names.append(self.b)
        return tuple(names)

    def summary(self) -> str:
        if self.kind == "expression":
            return self.expr or ""
        if self.fn == "derivative":
            return f"d/dt({self.src})"
        if self.fn == "integral":
            return f"∫dt({self.src})"
        if self.fn == "scale":
            return f"{self.src} × {self.param:g}"
        if self.fn == "offset":
            return f"{self.src} + {self.param:g}"
        if self.fn == "moving_avg":
            return f"moving_avg({self.src}, {self.param})"
        if self.fn == "abs":
            return f"|{self.src}|"
        joiner = {
            "add": " + ",
            "sub": " - ",
            "mul": " × ",
            "div": " ÷ ",
        }.get(self.fn)
        if joiner is not None:
            return f"{self.a}{joiner}{self.b}"
        if self.fn == "max":
            return f"max({self.a}, {self.b})"
        if self.fn == "min":
            return f"min({self.a}, {self.b})"
        return self.name

    def to_dict(self) -> dict:
        payload = {
            "op": "derive",
            "name": self.name,
            "unit": self.unit,
            "kind": self.kind,
        }
        if self.kind == "single":
            payload.update(fn=self.fn, src=self.src, param=self.param)
        elif self.kind == "dual":
            payload.update(fn=self.fn, a=self.a, b=self.b)
        else:
            payload["expr"] = self.expr
            if self.a is not None:
                payload["a"] = self.a
            if self.b is not None:
                payload["b"] = self.b
        return payload


@dataclass(frozen=True)
class RemoveEntry:
    names: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"op": "remove", "names": list(self.names)}


def make_single(name, unit, fn, src, param) -> DeriveEntry:
    fn = _text(fn, "fn")
    if fn not in SINGLE_FNS:
        raise RecipeError("unrecognized", f"不支持的单通道运算: {fn}")
    if fn in {"scale", "offset"}:
        stored = _finite_number(param)
    elif fn == "moving_avg":
        stored = _window(param)
    elif param is not None:
        raise RecipeError("unrecognized", f"{fn} 不使用参数")
    else:
        stored = None
    return DeriveEntry(
        name=_text(name, "name"),
        unit=_unit(unit),
        kind="single",
        fn=fn,
        src=_text(src, "src"),
        param=stored,
    )


def make_dual(name, unit, fn, a, b) -> DeriveEntry:
    fn = _text(fn, "fn")
    if fn not in DUAL_FNS:
        raise RecipeError("unrecognized", f"不支持的双通道运算: {fn}")
    return DeriveEntry(
        name=_text(name, "name"),
        unit=_unit(unit),
        kind="dual",
        fn=fn,
        a=_text(a, "a"),
        b=_text(b, "b"),
    )


def make_expression(name, unit, expr, a=None, b=None) -> DeriveEntry:
    return DeriveEntry(
        name=_text(name, "name"),
        unit=_unit(unit),
        kind="expression",
        expr=_text(expr, "expr"),
        a=None if a is None else _text(a, "a"),
        b=None if b is None else _text(b, "b"),
    )


def derive_from_dict(raw) -> DeriveEntry:
    if not isinstance(raw, dict) or raw.get("op") != "derive":
        raise RecipeError("unrecognized")
    kind = raw.get("kind")
    if kind == "single":
        _reject_unknown(raw, {"op", "name", "unit", "kind", "fn", "src", "param"})
        if "param" not in raw:
            raise RecipeError("unrecognized", "缺少 param")
        return make_single(raw.get("name"), raw.get("unit"), raw.get("fn"), raw.get("src"), raw.get("param"))
    if kind == "dual":
        _reject_unknown(raw, {"op", "name", "unit", "kind", "fn", "a", "b"})
        return make_dual(raw.get("name"), raw.get("unit"), raw.get("fn"), raw.get("a"), raw.get("b"))
    if kind == "expression":
        _reject_unknown(raw, {"op", "name", "unit", "kind", "expr", "a", "b"})
        return make_expression(
            raw.get("name"), raw.get("unit"), raw.get("expr"), raw.get("a"), raw.get("b"),
        )
    raise RecipeError("unrecognized")


def remove_from_dict(raw) -> RemoveEntry:
    if not isinstance(raw, dict) or set(raw) != {"op", "names"} or raw.get("op") != "remove":
        raise RecipeError("unrecognized")
    names = raw.get("names")
    if isinstance(names, str) or not isinstance(names, (list, tuple)) or not names:
        raise RecipeError("unrecognized")
    cleaned = tuple(_text(name, "names") for name in names)
    if len(set(cleaned)) != len(cleaned):
        raise RecipeError("unrecognized", "删除名单有重复")
    return RemoveEntry(cleaned)


def entry_from_dict(raw):
    if isinstance(raw, (DeriveEntry, RemoveEntry)):
        return raw
    if not isinstance(raw, dict):
        raise RecipeError("unrecognized")
    if raw.get("op") == "remove":
        return remove_from_dict(raw)
    return derive_from_dict(raw)


def evaluate_derive(entry, time, lookup) -> np.ndarray:
    """Evaluate one derive recipe.

    ``lookup(name)`` returns that input's samples. ``time`` is the source
    time axis; arithmetic that does not use time still rejects a result whose
    length differs from the inputs.
    """
    if not isinstance(entry, DeriveEntry):
        entry = derive_from_dict(entry)
    if entry.kind == "single":
        signal = _vector(lookup(entry.src))
        if entry.fn in _TIME_FNS:
            axis = _time_axis(time, signal.size)
            if entry.fn == "derivative" and signal.size < 2:
                raise RecipeError("length_mismatch")
            produced = (
                ChannelMath.derivative(axis, signal)
                if entry.fn == "derivative"
                else ChannelMath.integral(axis, signal)
            )
        elif entry.fn == "scale":
            produced = ChannelMath.scale(signal, entry.param)
        elif entry.fn == "offset":
            produced = ChannelMath.offset(signal, entry.param)
        elif entry.fn == "moving_avg":
            produced = ChannelMath.moving_avg(signal, entry.param)
        else:
            produced = np.abs(signal)
        return _vector(produced)
    if entry.kind == "dual":
        left = _vector(lookup(entry.a))
        right = _vector(lookup(entry.b))
        if left.size != right.size:
            raise RecipeError("length_mismatch")
        return _vector(_DUAL_IMPL[entry.fn](left, right))
    channels = {}
    if entry.a is not None:
        channels["A"] = _vector(lookup(entry.a))
    if entry.b is not None:
        channels["B"] = _vector(lookup(entry.b))
    try:
        checked = check_channel_expression(entry.expr, time, channels)
    except ExpressionError as exc:
        raise RecipeError("expression_error", str(exc)) from exc
    if not checked.can_create:
        raise RecipeError("expression_all_invalid")
    return _vector(checked.values)
