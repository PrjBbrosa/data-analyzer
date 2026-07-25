"""Non-GUI importer probe used to verify frozen analyzer builds."""
from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from .loader import AUDIO_VIDEO_EXTS, DataLoader


def run(paths: Sequence[Path], output_path: Path) -> int:
    """Load supported importer paths and write their observed channel counts."""
    records: list[dict[str, object]] = []
    try:
        for raw_path in paths:
            path = Path(raw_path)
            suffix = path.suffix.lower()
            if suffix == ".mat":
                groups = DataLoader.load_mat(path)
                channels = sum(len(group["channels"]) for group in groups)
            elif suffix in AUDIO_VIDEO_EXTS:
                _data, channel_names, _units, _fs, _meta = (
                    DataLoader.load_audio_video(path)
                )
                channels = len(channel_names)
            else:
                raise ValueError(f"unsupported importer smoke path: {path}")
            records.append({"path": str(path), "channels": channels})
    except Exception as exc:
        result: dict[str, object] = {"files": records, "error": str(exc)}
        return_code = 1
    else:
        result = {"files": records}
        return_code = 0 if all(record["channels"] > 0 for record in records) else 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return return_code
