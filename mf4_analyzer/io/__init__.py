"""I/O subpackage: file loading and per-file data containers."""
from .loader import DataLoader
from .file_data import FileData

__all__ = ['DataLoader', 'FileData']
