"""Manager-owned trust configuration; never obtain a trust root from a bundle."""
from __future__ import annotations

import json
from pathlib import Path
import sys

from mf4_analyzer.extensions.contract import ExtensionError, ReasonCode
from mf4_analyzer.extensions.locking import extensions_root


def default_config_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "repository.json"


def create_repository(app_root, *, manager_version, cancel_event, config_path=None,
                      offline_bundle=None):
    # TUF is imported only in the independent manager's composition boundary.
    from .download import assert_https_trusted_url
    from .repository import RepositoryClient
    from mf4_analyzer.extensions.revocations import revocation_store_path

    path = Path(config_path) if config_path is not None else default_config_path()
    if not path.is_file():
        raise ExtensionError(ReasonCode.CORE_INCONSISTENT,
                             "管理器缺少官方仓库配置，请获取完整的官方安装器。")
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if payload.get("schema") != 1:
        raise ExtensionError(ReasonCode.PROTOCOL_UNSUPPORTED, "unsupported repository configuration")
    from mf4_analyzer.extensions.state import resolve_inside
    bootstrap = resolve_inside(path.parent, payload["bootstrap_root"]).read_bytes()
    cache = extensions_root(app_root) / "cache"
    common = dict(metadata_cache_dir=cache / ("tuf-offline" if offline_bundle else "tuf"),
                  bootstrap_root=bootstrap, manager_version=manager_version,
                  revocation_store=revocation_store_path(app_root))
    if offline_bundle is not None:
        repository = RepositoryClient.from_offline_bundle(Path(offline_bundle), **common)
        repository.cancel_event = cancel_event
        return repository
    origins = tuple(payload["trusted_origins"])
    for key in ("metadata_base_url", "target_base_url"):
        assert_https_trusted_url(payload[key], trusted_origins=origins)
    return RepositoryClient(**common, metadata_base_url=payload["metadata_base_url"],
                            target_base_url=payload["target_base_url"],
                            trusted_origins=origins, cancel_event=cancel_event)
