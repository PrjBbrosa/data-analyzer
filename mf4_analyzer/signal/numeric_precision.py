"""Exact integer admission for float64 computation, without object copies."""
import numpy as np


def integers_exact_in_float64(values):
    """Check integer significant bits in bounded chunks, including int64.min.

    Float64 carries 53 significant binary bits. Above 2**53 only multiples
    of the current power-of-two spacing are representable. No float roundtrip
    (which can overflow at uint64.max) is used to decide admission.
    """
    array = np.asarray(values)
    if array.dtype.kind not in 'iu' or array.dtype.itemsize < 8:
        return True
    for start in range(0, array.size, 8192):
        chunk = array[start:start + 8192]
        magnitude = chunk.astype(np.uint64)
        if array.dtype.kind == 'i':
            negative = chunk < 0
            magnitude[negative] = ~magnitude[negative] + np.uint64(1)
        for shift in range(1, 12):
            if np.any((magnitude >= np.uint64(1 << (52 + shift))) &
                      ((magnitude & np.uint64((1 << shift) - 1)) != 0)):
                return False
    return True
