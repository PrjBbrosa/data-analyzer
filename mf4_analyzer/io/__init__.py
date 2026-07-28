"""I/O subpackage: file loading and per-file data containers."""
from .loader import DataLoader, HAS_ASAMMDF
from .file_data import FileData
from .source_adapters import (
    AdapterAvailability,
    DEFAULT_SOURCE_ADAPTER_REGISTRY,
    LoadedSource,
    SourceAdapter,
    SourceAdapterRegistry,
    SourceDescriptor,
)

__all__ = [
    'AdapterAvailability', 'DEFAULT_SOURCE_ADAPTER_REGISTRY', 'DataLoader',
    'FileData', 'HAS_ASAMMDF', 'LoadedSource', 'SourceAdapter',
    'SourceAdapterRegistry', 'SourceDescriptor',
]
