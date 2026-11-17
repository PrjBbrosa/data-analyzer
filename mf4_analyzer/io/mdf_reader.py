"""MDF metadata admission and fixed-record safety, shared by probe and load.

This is not a native parser sandbox. The import worker owns process isolation.
Arrays are first inspected without expansion, then reopened with the verified
reader. Existing scalar MDF2/3 files and injected loader factories remain valid.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import sys

from .import_limits import get_import_budget


class MdfSafetyError(ValueError):
    """A declared MDF layout cannot safely produce measurement values."""


def runtime_identity():
    """Actual loaded paths/hashes for source and frozen acceptance reports."""
    import asammdf
    from asammdf.blocks import cutils, v4_blocks

    facts = {"version": asammdf.__version__,
             "native_safety_revision": getattr(cutils, "TRACELAB_MDF_SAFETY", None)}
    for name, module in (("python", v4_blocks), ("native", cutils)):
        path = Path(module.__file__)
        facts[name + "_path"] = str(path)
        facts[name + "_sha256"] = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        )
    return facts


def _require_fixed_arrays():
    import asammdf
    from asammdf.blocks import cutils
    if (asammdf.__version__ != "8.8.32+tracelab.1"
            or getattr(cutils, "TRACELAB_MDF_SAFETY", None) != 1):
        raise ImportError(
            "MDF arrays require the verified asammdf 8.8.32+tracelab.1 wheel; "
            "build/install tools/dependency_patches/asammdf/build_wheel.py. "
            "No array channels were silently omitted."
        )


def _integer(value, label, *, minimum=0):
    value = int(value)
    if not minimum <= value <= sys.maxsize:
        raise MdfSafetyError(f"MDF {label}: invalid size {value}")
    return value


def _array_extent(channel, dependencies, budget):
    from asammdf.blocks import v4_constants as c
    from asammdf.blocks.v4_blocks import ChannelArrayBlock

    arrays = [dep for dep in (dependencies or ()) if isinstance(dep, ChannelArrayBlock)]
    if not arrays:
        return 1, 0, 0, False
    # Nested templates and dynamic axes need a separate proven layout contract.
    if len(arrays) != 1 or channel.data_type == c.DATA_TYPE_BYTEARRAY:
        raise MdfSafetyError(f"MDF unsupported nested/structure array: {channel.name}")
    ca = arrays[0]
    if ca.storage != c.CA_STORAGE_TYPE_CN_TEMPLATE or ca.flags & c.FLAG_CA_DYNAMIC_AXIS:
        raise MdfSafetyError(f"MDF unsupported array storage/dynamic axis: {channel.name}")
    dims = _integer(ca.dims, "array dimensions", minimum=1)
    if dims > 32:
        raise MdfSafetyError("MDF unsupported array rank >32")
    shape = [_integer(ca[f"dim_size_{i}"], "array dimension", minimum=1) for i in range(dims)]
    count = math.prod(shape)
    budget.check_channels(count, label=f"MDF array {channel.name}",
                          phase="mdf_admission", estimate_basis="declared_count")
    base = _integer(ca.byte_offset_base, "array byte stride", minimum=1)
    width = (int(channel.bit_offset) + int(channel.bit_count) + 7) // 8
    if base < width:
        raise MdfSafetyError(f"MDF overlapping array elements: {channel.name}")
    factors = [base * math.prod(shape[:i] if ca.flags & c.FLAG_CA_INVERSE_LAYOUT
                                 else shape[i + 1:]) for i in range(dims)]
    _require_fixed_arrays()
    if ca.get_byte_offset_factors() != factors:
        raise MdfSafetyError(f"MDF incorrect array strides: {channel.name}")
    invalid_base = _integer(ca.invalidation_bit_base, "array invalidation stride")
    invalid_factors = [invalid_base * (factor // base) for factor in factors]
    if ca.get_bit_pos_inval_factors() != invalid_factors:
        raise MdfSafetyError(f"MDF incorrect array invalidation strides: {channel.name}")
    if channel.flags & c.FLAG_INVALIDATION_BIT_VALID:
        last_bit = int(channel.pos_invalidation_bit) + sum((d - 1) * f for d, f in zip(shape, invalid_factors))
    else:
        last_bit = 0
    return count, sum((d - 1) * f for d, f in zip(shape, factors)), last_bit, True


def _validate_channel(group, channel, extra_offset=0, last_invalid_bit=0):
    from asammdf.blocks import v4_constants as c

    # Virtual values are generated from the record number, not fixed bytes.
    if channel.channel_type in (c.CHANNEL_TYPE_VIRTUAL, c.CHANNEL_TYPE_VIRTUAL_MASTER):
        return
    offset = _integer(channel.byte_offset, "channel byte offset")
    bit = _integer(channel.bit_offset, "channel bit offset")
    width = _integer(channel.bit_count, "channel bit count")
    record_size = int(group.channel_group.samples_byte_nr)
    if bit > 7 or offset + extra_offset + (bit + width + 7) // 8 > record_size:
        raise MdfSafetyError(f"MDF channel outside record: {channel.name} (offset={offset}, bits={width}, record={record_size})")
    if channel.channel_type == c.CHANNEL_TYPE_VLSD and (width != 64 or bit):
        raise MdfSafetyError(f"MDF unsupported VLSD pointer: {channel.name}")
    if channel.flags & c.FLAG_INVALIDATION_BIT_VALID:
        pos = _integer(channel.pos_invalidation_bit, "invalidation bit")
        if max(pos, last_invalid_bit) >= group.channel_group.invalidation_bytes_nr * 8:
            raise MdfSafetyError(f"MDF invalidation bit outside record: {channel.name}")


def _validate_blocks(mdf, group):
    """Check metadata coverage; do not decode blocks just to probe their directory."""
    from asammdf.blocks import v4_constants as c

    cg = group.channel_group
    cycles = _integer(cg.cycles_nr, "cycle count")
    size = _integer(cg.samples_byte_nr, "record size")
    invalid = _integer(cg.invalidation_bytes_nr, "invalidation bytes")
    if not group.sorted:
        raise MdfSafetyError("MDF unsupported unsorted record storage")
    required = cycles * (size + (0 if group.uses_ld else invalid))
    covered = 0
    for block in group.data_blocks:
        original = _integer(block.original_size, "block expanded bytes")
        stored = _integer(block.compressed_size, "block stored bytes")
        address = _integer(block.address, "block address")
        if block.location == c.LOCATION_ORIGINAL_FILE and address + stored > mdf._mdf.file_limit:
            raise MdfSafetyError("MDF truncated data block")
        limit = original if block.block_limit is None else _integer(block.block_limit, "block limit")
        if limit > original:
            raise MdfSafetyError("MDF block limit exceeds expanded bytes")
        covered += limit
        inv = block.invalidation_block
        if inv is not None and not inv.all_valid:
            if inv.address + inv.compressed_size > mdf._mdf.file_limit:
                raise MdfSafetyError("MDF truncated invalidation block")
    if covered < required:
        raise MdfSafetyError(f"MDF incomplete record coverage: {covered} < {required}")
    return cycles, size + invalid


def _validate_mdf4(mdf, budget, *, expanded=False, payload=False):
    count = 0
    has_arrays = False
    for group in mdf.groups:
        cycles, record_size = _validate_blocks(mdf, group)
        count += len(group.channels)
        for channel, dependencies in zip(group.channels, group.channel_dependencies, strict=True):
            if expanded:
                _validate_channel(group, channel)
                continue
            elements, offset, last_bit, is_array = _array_extent(channel, dependencies, budget)
            _validate_channel(group, channel, offset, last_bit)
            if is_array:
                has_arrays = True
                count += elements
        budget.check_channels(count, label="MDF expanded channels",
                              phase="mdf_admission", estimate_basis="declared_count")
        if payload:
            # Raw record/decompression and transient decoded storage, before get().
            budget.reserve_array((cycles, record_size), "u1", copies=3, label="MDF record buffers",
                                 phase="mdf_admission", estimate_basis="cumulative_admission")
    if not expanded:
        budget.reserve(count * 2048, label="MDF channel metadata/array expansion",
                       phase="mdf_admission", estimate_basis="cumulative_admission")
    return has_arrays


def _reserve_shared_output(mdf, budget):
    """Bound float conversion, aligned columns and DataFrame copies before get."""
    from asammdf.blocks import v4_constants as c

    counts = []
    for group in mdf.groups:
        for channel, dependencies in zip(group.channels, group.channel_dependencies, strict=True):
            if (channel.data_type in range(6) and not dependencies
                    and not (channel.channel_type in (c.CHANNEL_TYPE_MASTER, c.CHANNEL_TYPE_VIRTUAL_MASTER)
                             and channel.sync_type == c.SYNC_TYPE_TIME)):
                counts.append(int(group.channel_group.cycles_nr))
    maximum = max(counts, default=0)
    usable = sum(n > 1 if maximum > 1 else n > 0 for n in counts)
    budget.reserve_array((maximum, usable + 1), "f8", copies=3,
                         label="MDF shared-axis conversion/alignment/frame",
                         phase="mdf_shared_axis", estimate_basis="cumulative_admission")


def open_mdf(path, factory, *, metadata_only=False):
    """Open with shared admission, retaining loader.MDF as the injection seam."""
    if not getattr(factory, "__module__", "").startswith("asammdf."):
        return factory(path)
    budget = get_import_budget()
    mdf = factory(path, add_array_components=False, process_bus_logging=False)
    try:
        if str(mdf.version).startswith("4"):
            arrays = _validate_mdf4(mdf, budget, payload=not metadata_only)
            if arrays:
                mdf.close()
                mdf = factory(path, add_array_components=True, process_bus_logging=False)
                _validate_mdf4(mdf, budget, expanded=True)
            if not metadata_only:
                _reserve_shared_output(mdf, budget)
        return mdf
    except BaseException:
        mdf.close()
        raise


def open_native_mdf(path, factory):
    """Open for native sampling. Does not reserve the shared-axis table."""
    if not getattr(factory, "__module__", "").startswith("asammdf."):
        return factory(path)
    budget = get_import_budget()
    mdf = factory(path, add_array_components=False, process_bus_logging=False)
    try:
        if str(mdf.version).startswith("4"):
            arrays = _validate_mdf4(mdf, budget, payload=True)
            if arrays:
                mdf.close()
                mdf = factory(path, add_array_components=True, process_bus_logging=False)
                _validate_mdf4(mdf, budget, expanded=True)
        _reserve_native_output(mdf, budget)
        return mdf
    except BaseException:
        mdf.close()
        raise


def _raw_itemsize(channel):
    """Byte width of one raw sample. Unknown layouts return None, never zero."""
    data_type = getattr(channel, "data_type", None)
    bit_count = getattr(channel, "bit_count", None)
    if data_type is None or bit_count is None:
        return None
    data_type = int(data_type)
    bits = int(bit_count)
    if bits <= 0 or bits > 64:
        return None
    if data_type in (4, 5):
        if bits <= 32:
            return 4
        return 8
    if data_type in (0, 1, 2, 3):
        nbytes = (bits + 7) // 8
        if nbytes <= 1:
            return 1
        if nbytes <= 2:
            return 2
        if nbytes <= 4:
            return 4
        return 8
    return None


def _is_array_parent(dependency):
    if not dependency:
        return False
    from asammdf.blocks.v4_blocks import ChannelArrayBlock

    return any(isinstance(item, ChannelArrayBlock) for item in dependency)


def _conversion_plan(channel):
    """Return identity, library, enum, or unknown. Unknown is not a zero-byte plan."""
    from asammdf.blocks import v4_constants as c

    conversion = getattr(channel, "conversion", None)
    if conversion is None:
        return "identity"
    kind = getattr(conversion, "conversion_type", None)
    if kind is None:
        return "unknown"
    kind = int(kind)
    if kind in (c.CONVERSION_TYPE_TABX, c.CONVERSION_TYPE_RTABX, c.CONVERSION_TYPE_TTAB,
                c.CONVERSION_TYPE_BITFIELD, c.CONVERSION_TYPE_TRANS):
        return "enum"
    if kind == c.CONVERSION_TYPE_NON:
        return "identity"
    if kind == c.CONVERSION_TYPE_LIN:
        a = getattr(conversion, "a", None)
        b = getattr(conversion, "b", None)
        if a is None or b is None:
            return "unknown"
        if float(a) == 1.0 and float(b) == 0.0:
            return "identity"
        return "library"
    if kind in (c.CONVERSION_TYPE_RAT, c.CONVERSION_TYPE_ALG, c.CONVERSION_TYPE_TABI,
                c.CONVERSION_TYPE_TAB, c.CONVERSION_TYPE_RTAB):
        return "library"
    return "unknown"


def _invalidation_bytes(channel, cycles):
    flags = getattr(channel, "flags", None)
    if flags is None:
        return None
    if int(flags) & 2:
        return int(cycles)
    return 0


def _reserve_native_output(mdf, budget):
    """Charge native arrays before they are allocated.

    Record buffers stay on the existing copies=3 admission. This function adds
    time, raw, extra physical, validity, and one write copy of those arrays.
    A component whose size cannot be proven raises MdfSafetyError instead of
    being booked as zero. The shared-axis formula is not used here.
    """
    time_bytes = 0
    raw_bytes = 0
    physical_bytes = 0
    validity_bytes = 0
    handoff_bytes = 0
    version = str(getattr(mdf, "version", ""))
    for group_index, group in enumerate(mdf.groups):
        cycles = _integer(group.channel_group.cycles_nr, "cycle count")
        master_index = _master_index(mdf, group_index, group)
        master = group.channels[master_index]
        master_size = _raw_itemsize(master)
        if master_size is None:
            raise MdfSafetyError(f"MDF native time size is unknown: {getattr(master, 'name', master_index)}")
        described = _axis_description(master, version)
        if described[0] == "time":
            # Converted timestamps are float64 when the clock itself is scaled.
            if _conversion_plan(master) == "library" or master_size < 8:
                master_size = 8
        time_bytes += cycles * master_size
        dependencies = getattr(group, "channel_dependencies", None) or ()
        if len(dependencies) not in (0, len(group.channels)):
            raise MdfSafetyError("MDF native channel dependencies do not match the group")
        for channel_index, channel in enumerate(group.channels):
            if channel_index == master_index:
                continue
            dependency = dependencies[channel_index] if dependencies else None
            if _is_array_parent(dependency):
                # The parent record is already inside the record-buffer admission.
                # Elements are copied out; the parent ndarray is not kept.
                continue
            if dependency:
                raise MdfSafetyError(
                    f"MDF native unsupported channel dependency: {getattr(channel, 'name', channel_index)}"
                )
            plan = _conversion_plan(channel)
            if plan == "unknown":
                raise MdfSafetyError(
                    f"MDF native conversion size is unknown: {getattr(channel, 'name', channel_index)}"
                )
            itemsize = _raw_itemsize(channel)
            if itemsize is None:
                if plan == "enum" or int(getattr(channel, "data_type", -1)) >= 6:
                    continue
                raise MdfSafetyError(
                    f"MDF native raw size is unknown: {getattr(channel, 'name', channel_index)}"
                )
            if int(getattr(channel, "data_type", -1)) >= 6 and plan != "enum":
                continue
            raw_bytes += cycles * itemsize
            if plan == "library":
                physical_bytes += cycles * 8
            invalid = _invalidation_bytes(channel, cycles)
            if invalid is None:
                raise MdfSafetyError(
                    f"MDF native validity size is unknown: {getattr(channel, 'name', channel_index)}"
                )
            validity_bytes += invalid
    payload = time_bytes + raw_bytes + physical_bytes + validity_bytes
    # Parent/child handoff peak for expanded elements is the record fragment
    # (already reserved at copies=3) plus the element copies above. An extra
    # parent buffer is not allocated. Unknown sizes never arrive here as zero
    # substitutes; they raised above.
    del handoff_bytes
    if time_bytes:
        budget.reserve(time_bytes, label="MDF native time", phase="mdf_native",
                       estimate_basis="declared_layout")
    if raw_bytes:
        budget.reserve(raw_bytes, label="MDF native raw", phase="mdf_native",
                       estimate_basis="declared_layout")
    if physical_bytes:
        budget.reserve(physical_bytes, label="MDF native physical", phase="mdf_native",
                       estimate_basis="conversion_output")
    if validity_bytes:
        budget.reserve(validity_bytes, label="MDF native validity", phase="mdf_native",
                       estimate_basis="declared_layout")
    if payload:
        budget.reserve(payload, label="MDF native write temp", phase="mdf_native",
                       estimate_basis="transport_copy")


def _master_index(mdf, group_index, group):
    from asammdf.blocks import v4_constants as c

    db = getattr(mdf, "masters_db", None)
    if isinstance(db, dict) and group_index in db and db[group_index] is not None:
        return int(db[group_index])
    version = str(getattr(mdf, "version", ""))
    found = []
    for index, channel in enumerate(group.channels):
        kind = int(getattr(channel, "channel_type", -1))
        if version.startswith("2") or version.startswith("3"):
            if kind == 1:
                found.append(index)
        elif kind in (c.CHANNEL_TYPE_MASTER, c.CHANNEL_TYPE_VIRTUAL_MASTER):
            found.append(index)
    if len(found) == 1:
        return found[0]
    raise MdfSafetyError("MDF native master is missing or ambiguous")


def _axis_description(channel, version):
    version = str(version or "")
    unit = str(getattr(channel, "unit", "") or "")
    if version.startswith("2") or version.startswith("3"):
        if int(getattr(channel, "channel_type", -1)) == 1:
            return "time", unit
        raise MdfSafetyError("MDF native master is not a time channel")
    sync = getattr(channel, "sync_type", None)
    if sync is None:
        raise MdfSafetyError("MDF native master sync is missing")
    kind = {1: "time", 2: "angle", 3: "distance", 4: "index"}.get(int(sync))
    if kind is None:
        raise MdfSafetyError(f"MDF native master sync {sync} is unsupported")
    return kind, unit


def _clock_source(channel, group_index, master_index):
    name = str(getattr(channel, "name", "") or "master")
    source = getattr(channel, "source", None)
    path = str(getattr(source, "path", "") or "")
    return f"g{group_index}:c{master_index}:{name}:{path}"


def _array_identity(name):
    if "[" not in str(name):
        return (), ()
    base, rest = str(name).split("[", 1)
    body = "[" + rest
    coords = []
    while body.startswith("["):
        end = body.find("]")
        if end < 1:
            return (), ()
        piece = body[1:end]
        if not piece.isdigit():
            return (), ()
        coords.append(int(piece))
        body = body[end + 1:]
    if body or not base:
        return (), ()
    return (base,), tuple(coords)


def _plain_array(values):
    """Owning numeric array with no dtype metadata and no borrowed base."""
    import numpy as np

    array = np.asarray(values)
    clean = np.empty(array.shape, dtype=np.dtype(array.dtype.str))
    if array.size:
        clean[...] = array
    clean.setflags(write=False)
    return clean


def _group_fragment(mdf, group):
    core = getattr(mdf, "_mdf", mdf)
    loader = getattr(core, "_load_data", None)
    if loader is None:
        return None
    fragments = list(loader(group))
    if len(fragments) <= 1:
        return fragments[0] if fragments else None
    from asammdf.blocks.utils import Fragment

    data = bytearray()
    invalid = bytearray()
    has_invalid = False
    count = 0
    for fragment in fragments:
        payload = fragment.data
        data.extend(payload)
        record_count = int(getattr(fragment, "record_count", 0) or 0)
        if record_count > 0:
            count += record_count
        invalidation = getattr(fragment, "invalidation_data", None)
        if invalidation:
            has_invalid = True
            invalid.extend(invalidation)
    if count <= 0:
        count = int(group.channel_group.cycles_nr)
    return Fragment(bytes(data), 0, count, bytes(invalid) if has_invalid else None)


def _read_fragment_argument(mdf, fragment):
    if fragment is None:
        return None
    if str(getattr(mdf, "version", "")).startswith("4"):
        return fragment
    payload = getattr(fragment, "data", None)
    if payload is None:
        return None
    return (bytes(payload), 0, None)


def load_native_mdf(path, factory, source_id):
    """Read supported channels into one native FileData. Never calls load_mf4."""
    mdf = open_native_mdf(path, factory)
    try:
        return _native_file(mdf, path, source_id)
    finally:
        mdf.close()


def _native_file(mdf, path, source_id):
    import numpy as np

    from .file_data import FileData
    from .native_signal_store import AxisSpec, ChannelSpec, NativeSignalStore

    axes = []
    channels = []
    unsupported = []
    version = str(getattr(mdf, "version", ""))
    for group_index, group in enumerate(mdf.groups):
        fragment = _group_fragment(mdf, group)
        data = _read_fragment_argument(mdf, fragment)
        master_index = _master_index(mdf, group_index, group)
        master = group.channels[master_index]
        kind, unit = _axis_description(master, version)
        master_signal = mdf.get(
            group=group_index, index=master_index, raw=True,
            ignore_invalidation_bits=True, data=data,
        )
        # Time axes keep the master's converted timestamps. Raw clock counts
        # stay raw only for angle, distance, and index, which are not seconds.
        axis_source = master_signal.timestamps if kind == "time" else master_signal.samples
        axis_values = _plain_array(axis_source)
        if axis_values.ndim != 1:
            raise MdfSafetyError(f"MDF native master {master.name!r} is not one-dimensional")
        axis_id = f"g{group_index}:c{master_index}"
        axes.append(AxisSpec(
            axis_id,
            _clock_source(master, group_index, master_index),
            kind,
            unit,
            axis_values,
        ))
        dependencies = getattr(group, "channel_dependencies", None) or ()
        for channel_index, channel in enumerate(group.channels):
            if channel_index == master_index:
                continue
            name = str(getattr(channel, "name", "") or "").strip()
            dependency = dependencies[channel_index] if dependencies else None
            if not name:
                unsupported.append({
                    "name": "",
                    "group": group_index,
                    "index": channel_index,
                    "support_status": "unsupported",
                    "reason": "channel name is empty",
                })
                continue
            if _is_array_parent(dependency):
                unsupported.append({
                    "name": name,
                    "group": group_index,
                    "index": channel_index,
                    "support_status": "unsupported",
                    "reason": "array parent is a coordinate catalog, not a second measurement copy",
                })
                continue
            if dependency:
                raise MdfSafetyError(f"MDF native unsupported channel dependency: {name}")
            plan = _conversion_plan(channel)
            if plan == "unknown":
                raise MdfSafetyError(f"MDF native conversion size is unknown: {name}")
            if int(getattr(channel, "data_type", -1)) >= 6 and plan != "enum":
                unsupported.append({
                    "name": name,
                    "group": group_index,
                    "index": channel_index,
                    "support_status": "unsupported",
                    "reason": "non-numeric channel is not published as a measurement",
                })
                continue
            signal = mdf.get(
                group=group_index, index=channel_index, raw=True,
                ignore_invalidation_bits=True, data=data,
            )
            raw = _plain_array(signal.samples)
            if raw.ndim != 1 or raw.dtype.kind not in "biuf":
                unsupported.append({
                    "name": name,
                    "group": group_index,
                    "index": channel_index,
                    "support_status": "unsupported",
                    "reason": "channel samples are not a one-dimensional numeric array",
                })
                continue
            timestamps = np.asarray(signal.timestamps)
            if timestamps.shape != axis_values.shape or not np.array_equal(timestamps, axis_values):
                raise MdfSafetyError(
                    f"MDF native channel {name!r} timestamps do not match its master; "
                    "values were not interpolated or truncated"
                )
            if raw.shape[0] != axis_values.shape[0]:
                raise MdfSafetyError(
                    f"MDF native channel {name!r} length {raw.shape[0]} does not match "
                    f"its master length {axis_values.shape[0]}"
                )
            physical = None
            conversion = "identity"
            support = "numeric"
            if plan == "enum":
                conversion = "enum"
                support = "enum"
            elif plan == "library":
                converted = np.asarray(channel.conversion.convert(raw))
                if converted.shape != raw.shape or getattr(converted.dtype, "kind", "") not in "biuf":
                    unsupported.append({
                        "name": name,
                        "group": group_index,
                        "index": channel_index,
                        "support_status": "unsupported",
                        "reason": "library conversion did not return a same-length numeric array",
                    })
                    continue
                physical = _plain_array(converted)
                if physical.dtype == raw.dtype and np.array_equal(physical, raw):
                    physical = None
                    conversion = "identity"
                else:
                    conversion = "library"
            bits = signal.invalidation_bits
            validity = None if bits is None else _plain_array(np.asarray(bits, dtype=np.bool_))
            if validity is not None and validity.shape != raw.shape:
                raise MdfSafetyError(f"MDF native validity length does not match {name!r}")
            parent, coordinates = _array_identity(name)
            unit_text = str(getattr(signal, "unit", "") or "") or str(getattr(channel, "unit", "") or "")
            if not unit_text and channel.conversion is not None:
                unit_text = str(getattr(channel.conversion, "unit", "") or "")
            channels.append(ChannelSpec(
                group=group_index,
                index=channel_index,
                original_name=name,
                axis_id=axis_id,
                raw=raw,
                unit=unit_text,
                physical=physical,
                validity=validity,
                conversion=conversion,
                support_status=support,
                parent=parent,
                coordinates=coordinates,
            ))
    if not channels and not unsupported:
        raise MdfSafetyError("MDF native file has no channels")
    store = NativeSignalStore.build(source_id, axes, channels)
    budget = get_import_budget()
    store.report_lifecycle(budget)
    metadata = {
        "source_kind": "mdf",
        "layout": "native",
        "unsupported_channels": unsupported,
    }
    return FileData.from_native_store(
        path, store, source_metadata=metadata,
        channel_metadata=store.channel_metadata(),
    )
