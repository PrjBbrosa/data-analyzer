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
    budget.check_channels(count, label=f"MDF array {channel.name}")
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
        budget.check_channels(count, label="MDF expanded channels")
        if payload:
            # Raw record/decompression and transient decoded storage, before get().
            budget.reserve_array((cycles, record_size), "u1", copies=3, label="MDF record buffers")
    if not expanded:
        budget.reserve(count * 2048, label="MDF channel metadata/array expansion")
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
                         label="MDF shared-axis conversion/alignment/frame")


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
