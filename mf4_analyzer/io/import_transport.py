"""Bounded, Qt-neutral import IPC: a manifest graph and numeric sidecars.

Only explicitly supported data types cross this boundary. Object identity is
retained for repeated arrays, containers and WWT records (not arbitrary NumPy
view/base relationships). Numeric buffers never pass through JSON or pickle.

``max_bytes`` caps the manifest plus sidecars, and the unique numeric payload
plus DataFrame construction allowance, independently. Detached reads need at
most twice this allowance for numeric buffers; the broker must reserve that
headroom and supervise RSS. Python/JSON object overhead is additionally bounded
by manifest, item and depth limits, not claimed as an OS memory hard limit.
There are no surviving mmap/file handles: callers may delete the private task
directory immediately after a successful read. Source snapshots, cancellation,
directory lifetime and the application's aggregate resource policy belong to
the broker. One writer owns each private directory; it publishes exactly once.
"""
from __future__ import annotations

from dataclasses import fields
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any
import uuid

import numpy as np
import pandas as pd

from .blf_format import LazyZohFrame
from .can_frames import CanFrameBatch

__all__ = ["write_import_result", "read_import_result", "ImportTransportError",
           "ImportTransportLimitError"]

_VERSION = 1
_MAX_MANIFEST = 8 * 1024 * 1024
_MAX_ITEMS = 500_000
_MAX_NODES = 100_000
_MAX_FILES = 10_000
_MAX_DEPTH = 64
_MAX_HEADER = 4096
_CHUNK = 64 * 1024
# Conservative admission allowance for each reconstructed Python CAN tuple,
# float, integer, bytes header and list pointer, in addition to its payload.
_CAN_FRAME_OVERHEAD = 256
_FILE_NAME = re.compile(r"[a-f0-9]{32}-(?:[0-9]+\.npy|bytes\.bin)\Z")
_DATACLASSES = {
    "WwtRecord": "mf4_analyzer.io.wwt_document",
    "WwtDocument": "mf4_analyzer.io.wwt_document",
    "WwtLoadResult": "mf4_analyzer.io.wwt_document",
    "WwtIssue": "mf4_analyzer.io.wwt_document",
    "WwtWindowRectMm": "mf4_analyzer.io.wwt_display",
    "WwtCurveDisplay": "mf4_analyzer.io.wwt_display",
    "WwtDisplayWindow": "mf4_analyzer.io.wwt_display",
    "BlfDbcProbe": "mf4_analyzer.io.blf_format",
    "SourceDescriptor": "mf4_analyzer.io.source_adapters",
}


class ImportTransportError(ValueError):
    """Unsupported value or malformed/incomplete import transport."""


class ImportTransportLimitError(ImportTransportError):
    """The transport exceeds an explicit resource bound (never partial)."""


def _require(condition, message):
    if not condition:
        raise ImportTransportError(message)


def _limit(condition, message):
    if not condition:
        raise ImportTransportLimitError(message)


def _integer(value, *, minimum=0):
    _require(type(value) is int and minimum <= value <= np.iinfo(np.intp).max,
             "invalid integer size/index")
    return value


def _arguments(request_id, max_bytes):
    _require(type(request_id) is str and 0 < len(request_id) <= 256, "invalid request ID")
    _integer(max_bytes, minimum=1)


def _numeric(dtype, shape):
    _require(type(dtype) is str and len(dtype) <= 32, "invalid dtype")
    try:
        parsed = np.dtype(dtype)
    except (TypeError, ValueError) as exc:
        raise ImportTransportError("invalid dtype") from exc
    _require(parsed.kind in "biufcmM" and not parsed.hasobject and parsed.fields is None
             and parsed.subdtype is None and 0 < parsed.itemsize <= 32,
             "unsupported non-numeric/object dtype")
    _require(type(shape) is list and len(shape) <= 32, "invalid array shape")
    # Bound even zero-length dimensions individually before NumPy sees them.
    for dimension in shape:
        _integer(dimension)
    size = math.prod(shape) * parsed.itemsize
    _integer(size)
    return parsed, size


def _class(name):
    _require(type(name) is str and name in _DATACLASSES, "unsupported dataclass")
    return getattr(importlib.import_module(_DATACLASSES[name]), name)


def _open_regular(path):
    # A private task directory is a prerequisite; reject symlinks/reparse
    # escapes and nonregular files rather than blocking on a FIFO/device.
    info = path.lstat()
    _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
             "transport path is not a private regular file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        _require(stat.S_ISREG(opened.st_mode) and opened.st_nlink == 1
                 and (info.st_dev, info.st_ino) == (opened.st_dev, opened.st_ino),
                 "transport file changed while opening")
        return os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise


def _digest(stream):
    checksum = hashlib.sha256()
    while chunk := stream.read(_CHUNK):
        checksum.update(chunk)
    return checksum.hexdigest()


def _raw_can_frames(value):
    return bool(value) and all(
        type(row) is tuple and len(row) == 3 and type(row[0]) is float
        and type(row[1]) is int and 0 <= row[1] <= (1 << 64) - 1
        and type(row[2]) is bytes for row in value
    )


class _Writer:
    def __init__(self, directory, max_bytes):
        self.directory = directory
        self.max_bytes = max_bytes
        self.prefix = uuid.uuid4().hex
        self.nodes = []
        self.files = []
        self.seen = {}
        self.keepalive = []
        self.active = set()
        self.created = []
        self.items = 0
        self.disk_bytes = 0
        self.numeric_bytes = 0
        self.blob = None

    def charge(self, *, disk=0, numeric=0):
        self.disk_bytes += disk
        self.numeric_bytes += numeric
        _limit(max(self.disk_bytes, self.numeric_bytes) <= self.max_bytes,
               "import transport byte budget exceeded")

    def new_file(self, suffix):
        _limit(len(self.files) < _MAX_FILES, "too many transport files")
        path = self.directory / f"{self.prefix}-{suffix}"
        with path.open("xb"):
            pass
        self.created.append(path)
        return path

    def encode(self, value, depth=0):
        self.items += 1
        _limit(depth <= _MAX_DEPTH and self.items <= _MAX_ITEMS, "metadata depth/item limit exceeded")
        if value is None or type(value) in (bool, int, str):
            if type(value) is str:
                _limit(len(value) <= min(_MAX_MANIFEST, self.max_bytes), "metadata string too large")
            if type(value) is int:
                _limit(value.bit_length() <= 256, "metadata integer too large")
            return value
        if type(value) is float:
            return value if math.isfinite(value) else {"float": repr(value)}
        if isinstance(value, Path):
            return {"path": self.encode(str(value), depth + 1)}
        identity = id(value)
        _require(identity not in self.active, "cyclic import data is unsupported")
        if identity in self.seen:
            return {"ref": self.seen[identity]}
        _limit(len(self.nodes) < _MAX_NODES, "too many transport nodes")
        ref = len(self.nodes)
        self.seen[identity] = ref
        self.keepalive.append(value)  # temporary DataFrame column views must not reuse IDs
        self.nodes.append(None)
        self.active.add(identity)
        node = self.node(value, depth)
        self.nodes[ref] = node
        self.active.remove(identity)
        return {"ref": ref}

    def node(self, value, depth):
        encode = lambda item: self.encode(item, depth + 1)
        if type(value) is CanFrameBatch:
            _require(type(value.warnings) is tuple and all(type(w) is str for w in value.warnings),
                     "invalid CAN read warnings")
            return {"kind": "can_batch", "frames": encode(list(value)), "warnings": encode(value.warnings)}
        if type(value) in (list, tuple):
            if _raw_can_frames(value):
                count = len(value)
                payload_size = sum(len(row[2]) for row in value)
                # Admit before allocating column buffers or joining bytes.
                estimate = count * (_CAN_FRAME_OVERHEAD + 24) + 8 + payload_size
                _limit(self.numeric_bytes + estimate <= self.max_bytes,
                       "raw CAN frame budget exceeded")
                self.charge(numeric=count * _CAN_FRAME_OVERHEAD)
                offsets = np.empty(count + 1, dtype=np.uint64)
                offsets[0] = 0
                for i, row in enumerate(value):
                    offsets[i + 1] = int(offsets[i]) + len(row[2])
                return {"kind": "can_frames", "container": type(value).__name__, "count": count,
                        "times": encode(np.fromiter((r[0] for r in value), dtype=np.float64, count=count)),
                        "ids": encode(np.fromiter((r[1] for r in value), dtype=np.uint64, count=count)),
                        "offsets": encode(offsets), "payload": encode(b"".join(r[2] for r in value))}
            return {"kind": type(value).__name__, "items": [encode(x) for x in value]}
        if type(value) is dict:
            return {"kind": "dict", "items": [[encode(k), encode(v)] for k, v in value.items()]}
        if type(value) is bytes:
            self.charge(disk=len(value), numeric=len(value))
            if self.blob is None:
                path = self.new_file("bytes.bin")
                self.blob = {"path": path.name, "kind": "bytes", "size": 0}
                self.files.append(self.blob)
            offset = self.blob["size"]
            with (self.directory / self.blob["path"]).open("ab") as stream:
                stream.write(value)
            self.blob["size"] += len(value)
            return {"kind": "bytes", "file": self.files.index(self.blob),
                    "offset": offset, "size": len(value)}
        if type(value) is np.ndarray or isinstance(value, np.generic):
            array = np.asarray(value)
            _, nbytes = _numeric(array.dtype.str, list(array.shape))
            self.charge(numeric=nbytes)
            # A v1 .npy header is small and written before the payload. Check
            # exact output size before np.save writes any numeric bytes.
            import io

            header = io.BytesIO()
            np.lib.format.write_array_header_1_0(header, {
                "descr": array.dtype.str,
                "fortran_order": bool(array.flags.f_contiguous and not array.flags.c_contiguous),
                "shape": array.shape,
            })
            self.charge(disk=header.tell() + nbytes)
            path = self.new_file(f"{len(self.files)}.npy")
            with path.open("wb") as stream:
                np.save(stream, array, allow_pickle=False)
            spec = {"path": path.name, "kind": "array", "size": path.stat().st_size,
                    "dtype": array.dtype.str, "shape": list(array.shape), "nbytes": nbytes}
            _require(spec["size"] == header.tell() + nbytes, "unexpected NumPy header size")
            self.files.append(spec)
            return {"kind": "scalar" if isinstance(value, np.generic) else "array",
                    "file": len(self.files) - 1, "writeable": bool(array.flags.writeable)}
        if type(value) is pd.DataFrame:
            # iloc/items construct Series and pandas may deepcopy attrs for
            # each column, including a WWT record store's entire sample arrays.
            # This pandas iterator exposes column buffers without finalization.
            arrays = list(value._iter_column_arrays())
            _require(all(type(a) is np.ndarray for a in arrays), "unsupported pandas extension dtype")
            self.charge(numeric=sum(a.nbytes for a in arrays))
            return {"kind": "frame", "columns": encode(value.columns), "index": encode(value.index),
                    "arrays": [encode(a) for a in arrays], "attrs": encode(value.attrs)}
        if type(value) is pd.RangeIndex:
            return {"kind": "range", "start": value.start, "stop": value.stop,
                    "step": value.step, "name": encode(value.name)}
        if type(value) in (pd.Index, pd.MultiIndex):
            numeric = not isinstance(value, pd.MultiIndex) and value.dtype.kind in "biufcmM"
            return {"kind": "multiindex" if isinstance(value, pd.MultiIndex) else "index",
                    "values": encode(value.to_numpy(copy=False) if numeric else value.tolist()),
                    "names": encode(list(value.names))}
        if type(value) is LazyZohFrame:
            # The public get_column/to_pandas APIs intentionally materialize.
            # Snapshot only this concrete owner's sparse state, including any
            # pre-existing derived columns/cache, without calling those APIs.
            return {"kind": "lazy_zoh", "time": encode(value._ref_t),
                    "series": encode(value._series), "columns": encode(value._column_names),
                    "cache": encode(value._cache), "count": value._zoh_materializations}
        name = type(value).__name__
        if name in _DATACLASSES and type(value) is _class(name):
            return {"kind": "dataclass", "class": name,
                    "fields": {f.name: encode(getattr(value, f.name)) for f in fields(value)}}
        raise ImportTransportError(f"unsupported transport type: {type(value).__module__}.{name}")

    def publish(self, value, request_id):
        root = self.encode(value)
        for spec in self.files:
            with _open_regular(self.directory / spec["path"]) as stream:
                spec["sha256"] = _digest(stream)
        manifest = {"version": _VERSION, "request_id": request_id,
                    "root": root, "nodes": self.nodes, "files": self.files}
        temporary = self.directory / f"{self.prefix}-manifest.tmp"
        size = 0
        with temporary.open("xb") as stream:
            self.created.append(temporary)
            for chunk in json.JSONEncoder(ensure_ascii=True, allow_nan=False,
                                          separators=(",", ":")).iterencode(manifest):
                data = chunk.encode("utf-8")
                size += len(data)
                _limit(size <= _MAX_MANIFEST, "manifest too large")
                self.charge(disk=len(data))
                stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        target = self.directory / "manifest.json"
        _require(not target.exists() and not target.is_symlink(), "manifest already published")
        os.replace(temporary, target)
        return target


def write_import_result(value: Any, directory, *, request_id: str, max_bytes: int) -> Path:
    """Publish once in a broker-owned private directory; return manifest path.

    Failure removes only files created by this call. I/O failures propagate as
    OSError so the worker can distinguish disk/permission errors from bad data.
    """
    _arguments(request_id, max_bytes)
    directory = Path(directory)
    _require(not directory.is_symlink(), "transport directory must not be a symlink")
    directory.mkdir(parents=True, exist_ok=True)
    _require(not (directory / "manifest.json").exists()
             and not (directory / "manifest.json").is_symlink(), "manifest already published")
    writer = _Writer(directory, max_bytes)
    try:
        return writer.publish(value, request_id)
    finally:
        if not (directory / "manifest.json").exists():
            for path in writer.created:
                path.unlink(missing_ok=True)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


class _Reader:
    def __init__(self, directory, manifest, max_bytes, manifest_size):
        self.directory = directory
        self.nodes = manifest["nodes"]
        self.files = manifest["files"]
        _require(type(self.nodes) is list and type(self.files) is list, "invalid graph tables")
        _limit(len(self.nodes) <= _MAX_NODES and len(self.files) <= _MAX_FILES, "graph table limit exceeded")
        self.max_bytes = max_bytes
        self.numeric_bytes = 0
        self.items = 0
        self.cache = {}
        self.arrays = {}
        self.active = set()
        self.paths = []
        disk_bytes = manifest_size
        seen = set()
        for spec in self.files:
            _require(type(spec) is dict, "invalid file descriptor")
            name = spec["path"]
            _require(type(name) is str and _FILE_NAME.fullmatch(name) is not None
                     and name not in seen, "invalid/duplicate payload path")
            seen.add(name)
            path = directory / name
            _require(path.resolve().parent == directory.resolve(), "payload path escapes task directory")
            size = _integer(spec["size"])
            disk_bytes += size
            _limit(disk_bytes <= max_bytes, "import transport disk budget exceeded")
            if spec["kind"] == "array":
                dtype, nbytes = _numeric(spec["dtype"], spec["shape"])
                _require(_integer(spec["nbytes"]) == nbytes, "array byte count mismatch")
                self.charge(nbytes)
            else:
                _require(spec["kind"] == "bytes", "invalid file kind")
            with _open_regular(path) as stream:
                _require(os.fstat(stream.fileno()).st_size == size, "payload file size mismatch")
                if spec["kind"] == "array":
                    version = np.lib.format.read_magic(stream)
                    _require(version == (1, 0), "unsupported NumPy file version")
                    shape, _fortran, header_dtype = np.lib.format.read_array_header_1_0(
                        stream, max_header_size=_MAX_HEADER)
                    _require(list(shape) == spec["shape"] and header_dtype == dtype
                             and size == stream.tell() + nbytes, "NumPy header disagrees with manifest")
                stream.seek(0)
                _require(_digest(stream) == spec["sha256"], "payload checksum mismatch")
            self.paths.append(path)

    def charge(self, size):
        self.numeric_bytes += size
        _limit(self.numeric_bytes <= self.max_bytes, "import transport numeric budget exceeded")

    def decode(self, value, depth=0):
        self.items += 1
        _limit(depth <= _MAX_DEPTH and self.items <= _MAX_ITEMS, "metadata depth/item limit exceeded")
        if value is None or type(value) in (str, bool, int, float):
            if type(value) is float:
                _require(math.isfinite(value), "nonfinite JSON number")
            if type(value) is int:
                _limit(value.bit_length() <= 256, "metadata integer too large")
            return value
        _require(type(value) is dict and len(value) == 1, "invalid value node")
        if "float" in value:
            _require(value["float"] in ("nan", "inf", "-inf"), "invalid nonfinite float")
            return float(value["float"])
        if "path" in value:
            _require(type(value["path"]) is str, "invalid metadata path")
            return Path(value["path"])
        _require("ref" in value, "unknown value tag")
        ref = _integer(value["ref"])
        _require(ref < len(self.nodes) and ref not in self.active, "invalid/cyclic graph reference")
        if ref in self.cache:
            return self.cache[ref]
        self.active.add(ref)
        result = self.node(self.nodes[ref], depth)
        self.cache[ref] = result
        self.active.remove(ref)
        return result

    def file(self, node, kind):
        ref = _integer(node["file"])
        _require(ref < len(self.files) and self.files[ref]["kind"] == kind, "invalid payload reference")
        return ref, self.files[ref], self.paths[ref]

    def node(self, node, depth):
        _require(type(node) is dict, "invalid graph node")
        decode = lambda item: self.decode(item, depth + 1)
        kind = node["kind"]
        if kind == "can_batch":
            frames, warnings = decode(node["frames"]), decode(node["warnings"])
            _require(type(frames) is list and type(warnings) is tuple
                     and all(type(w) is str for w in warnings), "invalid CAN frame batch")
            return CanFrameBatch(frames, warnings=warnings)
        if kind == "can_frames":
            count = _integer(node["count"])
            self.charge(count * _CAN_FRAME_OVERHEAD)
            _require(node["container"] in ("list", "tuple"), "invalid CAN frame container")
            times, ids, offsets = (decode(node[k]) for k in ("times", "ids", "offsets"))
            payload = decode(node["payload"])
            _require(type(payload) is bytes, "invalid CAN byte payload")
            for array, dtype, size in ((times, np.float64, count), (ids, np.uint64, count),
                                       (offsets, np.uint64, count + 1)):
                _require(type(array) is np.ndarray and array.dtype == dtype and array.shape == (size,),
                         "invalid packed CAN array")
            _require(offsets[0] == 0 and offsets[-1] == len(payload), "invalid CAN payload offsets")
            _require(all(offsets[i] <= offsets[i + 1] for i in range(count)),
                     "nonmonotonic CAN payload offsets")
            rows = [(float(times[i]), int(ids[i]), payload[int(offsets[i]):int(offsets[i + 1])])
                    for i in range(count)]
            return tuple(rows) if node["container"] == "tuple" else rows
        if kind in ("tuple", "list", "dict"):
            items = node["items"]
            _require(type(items) is list, "invalid container")
            if kind == "dict":
                result = {}
                for pair in items:
                    _require(type(pair) is list and len(pair) == 2, "invalid mapping pair")
                    key, value = map(decode, pair)
                    _require(key not in result, "duplicate mapping key")
                    result[key] = value
                return result
            values = [decode(item) for item in items]
            return tuple(values) if kind == "tuple" else values
        if kind in ("array", "scalar"):
            ref, spec, path = self.file(node, "array")
            _require(type(node["writeable"]) is bool, "invalid array mutability")
            if ref not in self.arrays:
                with _open_regular(path) as stream:
                    array = np.load(stream, allow_pickle=False, max_header_size=_MAX_HEADER)
                _require(list(array.shape) == spec["shape"] and array.dtype.str == spec["dtype"],
                         "array changed after validation")
                array.setflags(write=node["writeable"])
                self.arrays[ref] = array
            array = self.arrays[ref]
            _require(array.flags.writeable == node["writeable"], "conflicting array mutability")
            if kind == "scalar":
                _require(array.ndim == 0, "invalid NumPy scalar")
                return array[()]
            return array
        if kind == "bytes":
            _, spec, path = self.file(node, "bytes")
            size, offset = _integer(node["size"]), _integer(node["offset"])
            _require(offset + size <= spec["size"], "bytes outside payload")
            self.charge(size)
            with _open_regular(path) as stream:
                stream.seek(offset)
                value = stream.read(size)
            _require(len(value) == size, "truncated bytes payload")
            return value
        if kind == "dataclass":
            cls = _class(node["class"])
            values = node["fields"]
            _require(type(values) is dict and set(values) == {f.name for f in fields(cls)},
                     "dataclass field mismatch")
            return cls(**{name: decode(value) for name, value in values.items()})
        if kind == "range":
            start, stop, step = node["start"], node["stop"], node["step"]
            _require(all(type(x) is int and abs(x) <= np.iinfo(np.intp).max
                         for x in (start, stop, step)) and step != 0, "invalid RangeIndex")
            _limit(len(range(start, stop, step)) <= self.max_bytes, "RangeIndex length exceeds budget")
            return pd.RangeIndex(start, stop, step, name=decode(node["name"]))
        if kind in ("index", "multiindex"):
            values, names = decode(node["values"]), decode(node["names"])
            if kind == "multiindex":
                return pd.MultiIndex.from_tuples(values, names=names)
            _require(type(names) is list and len(names) == 1, "invalid index names")
            return pd.Index(values, name=names[0], tupleize_cols=False)
        if kind == "frame":
            columns, index = decode(node["columns"]), decode(node["index"])
            _require(isinstance(columns, pd.Index) and isinstance(index, pd.Index)
                     and type(node["arrays"]) is list and len(columns) == len(node["arrays"]),
                     "invalid frame axes")
            arrays = [decode(a) for a in node["arrays"]]
            _require(all(type(a) is np.ndarray and a.ndim == 1 and len(a) == len(index)
                         for a in arrays), "frame column length/type mismatch")
            self.charge(sum(a.nbytes for a in arrays))
            frame = pd.DataFrame(dict(enumerate(arrays)), index=index, copy=False)
            frame.columns = columns
            attrs = decode(node["attrs"])
            _require(type(attrs) is dict, "invalid frame attrs")
            # pandas' attrs setter deep-copies: retain explicit graph references.
            frame.attrs.update(attrs)
            return frame
        if kind == "lazy_zoh":
            time = decode(node["time"])
            series, columns, cache = decode(node["series"]), decode(node["columns"]), decode(node["cache"])
            _require(type(series) is dict and type(cache) is dict and type(columns) is list
                     and all(type(c) is str for c in columns), "invalid lazy CAN state")
            _require(type(time) is np.ndarray and time.ndim == 1 and time.dtype == np.float64,
                     "invalid lazy CAN reference time")
            for name, pair in series.items():
                _require(type(name) is str and type(pair) is tuple and len(pair) == 2,
                         "invalid CAN event pair")
                t, v = pair
                _require(all(type(a) is np.ndarray and a.ndim == 1 and a.dtype == np.float64
                             for a in pair) and len(t) == len(v), "invalid CAN event arrays")
            _require(all(type(a) is np.ndarray and a.ndim == 1 and a.dtype == np.float64
                         and len(a) == len(time) for a in cache.values()), "invalid CAN dense cache")
            _require(all(name == "Time" or name in series or name in cache for name in columns),
                     "missing CAN column data")
            _require("Time" not in cache or cache["Time"] is time, "CAN Time identity mismatch")
            frame = LazyZohFrame(time, series, columns)
            frame._cache = cache
            frame._zoh_materializations = _integer(node["count"])
            return frame
        raise ImportTransportError(f"unsupported node kind: {kind!r}")


def read_import_result(directory, *, request_id: str, max_bytes: int) -> Any:
    """Validate identity, all payload headers/checksums and budgets, then detach.

    Raises ImportTransportLimitError for resource rejection, otherwise
    ImportTransportError for missing/corrupt/unsupported result data.
    """
    _arguments(request_id, max_bytes)
    directory = Path(directory)
    _require(not directory.is_symlink(), "transport directory must not be a symlink")
    try:
        with _open_regular(directory / "manifest.json") as stream:
            size = os.fstat(stream.fileno()).st_size
            _limit(size <= min(_MAX_MANIFEST, max_bytes), "manifest exceeds byte budget")
            raw = stream.read(min(_MAX_MANIFEST, max_bytes) + 1)
        _require(len(raw) == size, "manifest changed during read")
        manifest = json.loads(raw, object_pairs_hook=_unique_object)
        _require(type(manifest) is dict and type(manifest["version"]) is int
                 and manifest["version"] == _VERSION, "unsupported manifest version")
        _require(manifest["request_id"] == request_id, "request ID mismatch")
        reader = _Reader(directory, manifest, max_bytes, len(raw))
        return reader.decode(manifest["root"])
    except ImportTransportError:
        raise
    except (OSError, ValueError, TypeError, KeyError, IndexError, OverflowError, RecursionError) as exc:
        raise ImportTransportError(f"invalid import transport: {exc}") from exc
