"""Safe WinWert ``Pars`` formula evaluation.

Only a tiny arithmetic AST is accepted. The evaluator never calls ``eval``,
``exec``, or ``compile``, and never retains a callable namespace.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, replace

import numpy as np

from .wwt_document import WwtRecord

_BIN_OPS = {
    ast.Add: np.add,
    ast.Sub: np.subtract,
    ast.Mult: np.multiply,
    ast.Div: np.divide,
}
_UNARY_OPS = {
    ast.UAdd: lambda value: value,
    ast.USub: np.negative,
}
_ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Call,
    ast.Name,
    ast.Constant,
    ast.Load,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.UAdd,
    ast.USub,
)
_REF_NAME = re.compile(r"k\d+")


class WwtFormulaError(ValueError):
    def __init__(self, code: str, record_index: int, detail: str = ""):
        self.code = code
        self.record_index = record_index
        self.detail = detail
        super().__init__(f"{code}: record {record_index}: {detail}")


@dataclass(frozen=True)
class FormulaResult:
    record_index: int
    values: np.ndarray
    refs: tuple[int, ...]
    axis_record: int


def _record_ref(node: ast.Name, owner: int) -> int:
    if not _REF_NAME.fullmatch(node.id):
        raise WwtFormulaError("unsupported_formula", owner, node.id)
    return int(node.id[1:])


def _validate_tree(tree: ast.AST, owner: int) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise WwtFormulaError(
                "unsupported_formula", owner, type(node).__name__
            )
        if isinstance(node, ast.Constant) and (
            isinstance(node.value, bool)
            or not isinstance(node.value, (int, float))
        ):
            raise WwtFormulaError(
                "unsupported_formula", owner, type(node.value).__name__
            )
        if isinstance(node, ast.Call):
            if (
                not isinstance(node.func, ast.Name)
                or node.func.id != "abs"
                or len(node.args) != 1
                or node.keywords
            ):
                name = node.func.id if isinstance(node.func, ast.Name) else type(node.func).__name__
                raise WwtFormulaError("unsupported_formula", owner, name)


def _collect_refs(tree: ast.AST, owner: int) -> tuple[int, ...]:
    refs: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id != "abs":
            refs.append(_record_ref(node, owner))
    return tuple(dict.fromkeys(refs))


def _eval_node(node: ast.AST, owner: int, resolve) -> np.ndarray | float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, owner, resolve)
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        return resolve(_record_ref(node, owner))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand, owner, resolve))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left = _eval_node(node.left, owner, resolve)
        right = _eval_node(node.right, owner, resolve)
        return _BIN_OPS[type(node.op)](left, right)
    if isinstance(node, ast.Call):
        return np.abs(_eval_node(node.args[0], owner, resolve))
    raise WwtFormulaError("unsupported_formula", owner, type(node).__name__)


def _as_1d(values: np.ndarray | float) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim == 0:
        return array
    if array.ndim != 1:
        raise ValueError("ndim")
    return array


def _freeze(values: np.ndarray) -> np.ndarray:
    frozen = np.array(values, dtype=np.float64, copy=True)
    frozen.setflags(write=False)
    return frozen


def _parse_formula(formula: str, owner: int) -> ast.Expression:
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as exc:
        raise WwtFormulaError("unsupported_formula", owner, formula) from exc
    _validate_tree(tree, owner)
    return tree


def evaluate_wwt_formulas(
    records: tuple[WwtRecord, ...] | list[WwtRecord],
    *,
    strict: bool = False,
) -> tuple[tuple[WwtRecord, ...], tuple[str, ...]]:
    """Materialize every ``Pars`` record that the whitelist can evaluate.

    Failed formulas keep ``values is None``. ``strict=True`` raises the first
    ``WwtFormulaError`` instead of recording a diagnostic.
    """
    catalog = list(records)
    diagnostics: list[str] = []
    memo: dict[int, np.ndarray] = {}
    visiting: set[int] = set()

    def resolve_values(index: int, owner: int) -> np.ndarray:
        if index in memo:
            return memo[index]
        if index < 0 or index >= len(catalog):
            raise WwtFormulaError(
                "missing_formula_ref", owner, f"k{index}"
            )
        rec = catalog[index]
        if rec.tag == "Pars":
            return materialize_pars(index)
        if rec.values is None:
            raise WwtFormulaError(
                "missing_formula_ref", owner, f"k{index}"
            )
        values = _as_1d(rec.values)
        memo[index] = values
        return values

    def materialize_pars(index: int) -> np.ndarray:
        if index in memo:
            return memo[index]
        if index in visiting:
            raise WwtFormulaError("formula_cycle", index, f"k{index}")
        rec = catalog[index]
        if rec.values is not None:
            values = _as_1d(rec.values)
            memo[index] = values
            return values
        if not rec.formula:
            raise WwtFormulaError("unsupported_formula", index, "")
        visiting.add(index)
        try:
            tree = _parse_formula(rec.formula, index)
            refs = _collect_refs(tree, index)
            leaves: list[WwtRecord] = []
            for ref in refs:
                resolve_values(ref, index)
                leaves.append(catalog[ref])
            array_leaves = [leaf for leaf in leaves if leaf.values is not None]
            axes = {leaf.axis_record for leaf in array_leaves}
            if None in axes or len(axes) != 1:
                raise WwtFormulaError(
                    "formula_axis_mismatch",
                    index,
                    ",".join(str(leaf.axis_record) for leaf in array_leaves),
                )
            length_list = [
                int(np.asarray(leaf.values).shape[0])
                for leaf in array_leaves
                if leaf.values is not None
            ]
            lengths = set(length_list)
            if len(lengths) != 1:
                raise WwtFormulaError(
                    "formula_shape_mismatch",
                    index,
                    ",".join(str(item) for item in length_list),
                )
            expected_len = next(iter(lengths))
            axis = next(iter(axes))

            def resolve(ref: int) -> np.ndarray:
                return resolve_values(ref, index)

            with np.errstate(divide="ignore", invalid="ignore"):
                raw = _eval_node(tree, index, resolve)
            out = np.asarray(raw, dtype=np.float64)
            if out.ndim != 1 or int(out.shape[0]) != expected_len:
                raise WwtFormulaError(
                    "formula_shape_mismatch",
                    index,
                    f"{expected_len},{out.shape}",
                )
            if not np.any(np.isfinite(out)):
                raise WwtFormulaError(
                    "formula_no_finite_values", index, rec.formula
                )
            frozen = _freeze(out)
            memo[index] = frozen
            catalog[index] = replace(
                rec, values=frozen, axis_record=axis
            )
            return frozen
        finally:
            visiting.discard(index)

    for rec in catalog:
        if rec.tag != "Pars" or rec.values is not None:
            continue
        try:
            materialize_pars(rec.index)
        except WwtFormulaError as exc:
            if strict:
                raise
            diagnostics.append(str(exc))

    return tuple(catalog), tuple(diagnostics)


def formula_references(record: WwtRecord) -> tuple[int, ...]:
    if not record.formula:
        return ()
    return _collect_refs(_parse_formula(record.formula, record.index), record.index)


def formula_channel_metadata(record: WwtRecord, refs: tuple[int, ...]) -> dict:
    return {
        "tag": record.tag,
        "unit": record.unit,
        "scale_a": record.scale_a,
        "offset_c": record.offset_c,
        "source_filename": "",
        "record_index": record.index,
        "derived": True,
        "formula": record.formula,
        "formula_refs": list(refs),
    }
