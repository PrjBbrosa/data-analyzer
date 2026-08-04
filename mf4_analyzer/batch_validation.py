"""Pure validation helpers shared by batch preflight and execution."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
from typing import Any, Mapping

import numpy as np

from .batch_recipe import TIME_RENDER_DEFAULTS
from .signal.fft import get_analysis_window


@dataclass(frozen=True)
class ValidationIssue:
    field: str
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.field}: {self.message}"


class BatchValidationError(ValueError):
    """Raised when a batch recipe or resolved task is not executable."""

    def __init__(self, issues) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(str(issue) for issue in self.issues))


def _finite_number(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _slice_position_number(value: Any) -> bool:
    # Accepted types have one source of truth in normalization.
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def _positive_number(value: Any) -> bool:
    return _finite_number(value) and float(value) > 0.0


_IMAGE_SIZE_PRESETS = {
    "1080p": (1920, 1080),
    "fullhd": (1920, 1080),
    "1920x1080": (1920, 1080),
    "2k": (2560, 1440),
    "qhd": (2560, 1440),
    "2560x1440": (2560, 1440),
    "4k": (3840, 2160),
    "uhd": (3840, 2160),
    "3840x2160": (3840, 2160),
}


def _output_value(outputs: Any, field: str, default: Any) -> Any:
    if isinstance(outputs, Mapping):
        return outputs.get(field, default)
    return getattr(outputs, field, default)


def resolve_output_image_dimensions(outputs: Any) -> tuple[Any, Any]:
    """Resolve the configured image-size key without importing batch types."""

    key = str(
        _output_value(outputs, "image_size", "1920x1080") or ""
    ).strip().lower().replace(" ", "")
    if key == "custom":
        return (
            _output_value(outputs, "image_width", 1920),
            _output_value(outputs, "image_height", 1080),
        )
    if key not in _IMAGE_SIZE_PRESETS:
        raise ValueError(
            "image_size must be 1920x1080, 2560x1440, "
            "3840x2160, or custom"
        )
    return _IMAGE_SIZE_PRESETS[key]


def _range_issue(params: Mapping[str, Any], *, axis: str) -> ValidationIssue | None:
    if bool(params.get(f"{axis}_auto", True)):
        return None
    if axis == "z" and "z_min" not in params and "z_max" not in params:
        lo_key, hi_key = "z_floor", "z_ceiling"
    else:
        lo_key, hi_key = f"{axis}_min", f"{axis}_max"
    lo, hi = params.get(lo_key), params.get(hi_key)
    if not (_finite_number(lo) and _finite_number(hi) and float(lo) < float(hi)):
        return ValidationIssue(
            f"{axis}_range",
            "invalid_range",
            f"manual {axis.upper()} range requires finite min < max",
        )
    return None


def validate_outputs(outputs: Any) -> tuple[ValidationIssue, ...]:
    """Validate output choices before task expansion or computation."""

    export_data = bool(_output_value(outputs, "export_data", False))
    export_image = bool(_output_value(outputs, "export_image", False))
    data_format = _output_value(outputs, "data_format", "csv")

    issues: list[ValidationIssue] = []
    if not (export_data or export_image):
        issues.append(ValidationIssue(
            "outputs", "no_outputs",
            "at least one of data or image output must be enabled",
        ))
    if export_data:
        normalized_format = str(data_format or "").strip().lower().lstrip(".")
        if normalized_format not in {"csv", "xlsx"}:
            issues.append(ValidationIssue(
                "data_format", "unsupported_format",
                "data_format must be csv or xlsx when data output is enabled",
            ))

    conflict_policy = str(
        _output_value(outputs, "conflict_policy", "auto_number") or ""
    ).strip().lower()
    if conflict_policy not in {"error", "skip", "overwrite", "auto_number"}:
        issues.append(ValidationIssue(
            "conflict_policy", "unsupported_policy",
            "conflict_policy must be error, skip, overwrite, or auto_number",
        ))

    resume_policy = str(
        _output_value(outputs, "resume_policy", "none") or ""
    ).strip().lower()
    if resume_policy not in {"none", "manifest"}:
        issues.append(ValidationIssue(
            "resume_policy", "unsupported_policy",
            "resume_policy must be none or manifest",
        ))

    if export_image:
        # BatchRenderOptions remains the single geometry/encoding boundary.
        # Independent probes preserve field-specific issues while reusing its
        # exact ranges and total-pixel cap.
        from .batch_image_options import BatchRenderOptions

        image_format = str(
            _output_value(outputs, "image_format", "png") or ""
        ).strip().lower().lstrip(".")
        try:
            BatchRenderOptions(
                width_px=320, height_px=320, dpi=144, format=image_format,
            )
        except (TypeError, ValueError) as exc:
            issues.append(ValidationIssue(
                "image_format", "unsupported_format", str(exc),
            ))

        dimensions = None
        try:
            dimensions = resolve_output_image_dimensions(outputs)
        except (TypeError, ValueError) as exc:
            issues.append(ValidationIssue(
                "image_size", "unsupported_size", str(exc),
            ))

        width_valid = height_valid = False
        if dimensions is not None:
            width, height = dimensions
            try:
                BatchRenderOptions(
                    width_px=width, height_px=320, dpi=144, format="png",
                )
                width_valid = True
            except (TypeError, ValueError) as exc:
                issues.append(ValidationIssue(
                    "image_width", "invalid_dimension", str(exc),
                ))
            try:
                BatchRenderOptions(
                    width_px=320, height_px=height, dpi=144, format="png",
                )
                height_valid = True
            except (TypeError, ValueError) as exc:
                issues.append(ValidationIssue(
                    "image_height", "invalid_dimension", str(exc),
                ))
            if width_valid and height_valid:
                try:
                    BatchRenderOptions(
                        width_px=width,
                        height_px=height,
                        dpi=144,
                        format="png",
                    )
                except (TypeError, ValueError) as exc:
                    issues.append(ValidationIssue(
                        "image_pixels", "too_many_pixels", str(exc),
                    ))

        image_dpi = _output_value(outputs, "image_dpi", 144)
        try:
            BatchRenderOptions(
                width_px=320, height_px=320, dpi=image_dpi, format="png",
            )
        except (TypeError, ValueError) as exc:
            issues.append(ValidationIssue(
                "image_dpi", "invalid_dpi", str(exc),
            ))

        image_background = _output_value(
            outputs, "image_background", "white"
        )
        try:
            BatchRenderOptions(
                width_px=320,
                height_px=320,
                dpi=144,
                format="png",
                background=image_background,
            )
        except (TypeError, ValueError) as exc:
            issues.append(ValidationIssue(
                "image_background", "unsupported_background", str(exc),
            ))

        image_line_width = _output_value(
            outputs, "image_line_width", 1.5
        )
        try:
            BatchRenderOptions(
                width_px=320,
                height_px=320,
                dpi=144,
                format="png",
                line_width=image_line_width,
            )
        except (TypeError, ValueError) as exc:
            issues.append(ValidationIssue(
                "image_line_width", "invalid_line_width", str(exc),
            ))
    return tuple(issues)


def validate_recipe(
    method: str,
    params: Mapping[str, Any] | None,
    *,
    rpm_channel: str = "",
    rpm_signal=None,
) -> tuple[ValidationIssue, ...]:
    """Validate facts knowable before a source file is resolved."""

    params = params or {}
    issues: list[ValidationIssue] = []

    time_range = params.get("time_range")
    if time_range is not None:
        valid_shape = (
            isinstance(time_range, (tuple, list, np.ndarray))
            and not isinstance(time_range, (str, bytes))
            and len(time_range) == 2
        )
        if not valid_shape:
            issues.append(ValidationIssue(
                "time_range", "invalid_shape",
                "time_range requires [start, end]",
            ))
        else:
            lo, hi = time_range
            if not (_finite_number(lo) and _finite_number(hi)):
                issues.append(ValidationIssue(
                    "time_range", "non_finite",
                    "time_range start/end must be finite",
                ))
            elif float(lo) >= float(hi):
                issues.append(ValidationIssue(
                    "time_range", "reversed",
                    "time_range requires start < end",
                ))

    if "fs" in params and not _positive_number(params.get("fs")):
        issues.append(ValidationIssue(
            "fs", "invalid_fs", "fs must be finite and > 0",
        ))

    if method in {"fft", "fft_time", "order_time"}:
        window = params.get("window", params.get("win", "hanning"))
        try:
            get_analysis_window(window, 2)
        except (AttributeError, TypeError, ValueError):
            issues.append(ValidationIssue(
                "window", "unsupported_window",
                f"unsupported analysis window: {window!r}",
            ))

    if method == "fft" and "amplitude_definition" in params:
        amplitude_definition = str(
            params.get("amplitude_definition") or ""
        ).strip().lower()
        if amplitude_definition not in {"native", "peak", "rms"}:
            issues.append(ValidationIssue(
                "amplitude_definition", "unsupported_amplitude_definition",
                "amplitude_definition must be native, peak, or rms",
            ))

    if method == "time":
        group_by = str(params.get(
            "render_group_by", TIME_RENDER_DEFAULTS["render_group_by"],
        ) or "").strip().lower()
        if group_by not in {"none", "source", "channel"}:
            issues.append(ValidationIssue(
                "render_group_by", "unsupported_grouping",
                "render_group_by must be none, source, or channel",
            ))
        elif group_by != "none":
            layout = str(params.get(
                "render_layout", TIME_RENDER_DEFAULTS["render_layout"],
            ) or "").strip().lower()
            if layout not in {"overlay", "subplot"}:
                issues.append(ValidationIssue(
                    "render_layout", "unsupported_layout",
                    "render_layout must be overlay or subplot",
                ))

        x_source = str(params.get(
            "x_source", TIME_RENDER_DEFAULTS["x_source"],
        ) or "").strip().lower()
        if x_source not in {"time", "channel"}:
            issues.append(ValidationIssue(
                "x_source", "unsupported_x_source",
                "x_source must be time or channel",
            ))
        elif x_source == "channel":
            if not str(params.get("x_channel") or "").strip():
                issues.append(ValidationIssue(
                    "x_channel", "required",
                    "x_channel is required when x_source is channel",
                ))
        else:
            x_origin = str(params.get(
                "x_origin", TIME_RENDER_DEFAULTS["x_origin"],
            ) or "").strip().lower()
            if x_origin not in {"zero", "absolute"}:
                issues.append(ValidationIssue(
                    "x_origin", "unsupported_x_origin",
                    "x_origin must be zero or absolute",
                ))
        statistics = params.get("chart_statistics")
        if statistics is not None:
            if not isinstance(statistics, Mapping):
                issues.append(ValidationIssue(
                    "chart_statistics", "invalid_statistics",
                    "chart_statistics must be an object",
                ))
            elif bool(statistics.get("enabled", False)):
                mode = str(statistics.get("range_mode", "full") or "").strip().lower()
                if mode not in {"full", "custom"}:
                    issues.append(ValidationIssue(
                        "chart_statistics", "invalid_range_mode",
                        "chart_statistics range_mode must be full or custom",
                    ))
                if mode == "custom":
                    lo, hi = statistics.get("x_min"), statistics.get("x_max")
                    if not (_finite_number(lo) and _finite_number(hi) and float(lo) < float(hi)):
                        issues.append(ValidationIssue(
                            "chart_statistics", "invalid_range",
                            "chart_statistics custom range requires finite min < max",
                        ))
                metrics = statistics.get("metrics", ())
                if not isinstance(metrics, (tuple, list)) or not metrics or any(
                    str(metric).strip().lower() not in {"max", "min", "mean"}
                    for metric in metrics
                ):
                    issues.append(ValidationIssue(
                        "chart_statistics", "invalid_metrics",
                        "chart_statistics requires max, min, or mean metrics",
                    ))

    if method in {"fft_time", "order_time"}:
        slice_params = params.get("slice")
        if slice_params is not None:
            if not isinstance(slice_params, Mapping):
                issues.append(ValidationIssue(
                    "slice", "invalid_slice",
                    "slice must be an object",
                ))
            elif bool(slice_params.get("enabled", False)):
                axis = str(slice_params.get("axis", "time") or "").strip().lower()
                if axis not in {"time", "y"}:
                    issues.append(ValidationIssue(
                        "slice", "invalid_slice_axis",
                        "slice axis must be time or y",
                    ))

                positions = slice_params.get("positions", ())
                valid_positions = (
                    isinstance(positions, (tuple, list))
                    and all(_slice_position_number(item) for item in positions)
                )
                if not valid_positions:
                    issues.append(ValidationIssue(
                        "slice", "invalid_slice_positions",
                        "slice positions must be a list of finite numbers (strings are not accepted)",
                    ))
                else:
                    if axis == "y" and any(float(item) < 0 for item in positions):
                        issues.append(ValidationIssue(
                            "slice", "invalid_slice_positions",
                            "slice positions must not be negative when axis is y",
                        ))
                    if len(positions) > 4:
                        issues.append(ValidationIssue(
                            "slice", "too_many_slice_positions",
                            "slice supports at most 4 positions",
                        ))
                    if len(positions) == 0:
                        issues.append(ValidationIssue(
                            "slice", "slice_positions_required",
                            "slice requires at least one position when enabled",
                        ))

    nfft_mode = str(params.get("nfft_mode", "")).strip().lower()
    nfft = params.get("nfft")
    fixed_nfft = nfft_mode in {"fixed", "manual", "固定"}
    explicit_nfft = nfft not in (None, "", "auto", "自动")
    if fixed_nfft or explicit_nfft:
        valid_nfft = (
            not isinstance(nfft, (bool, np.bool_))
            and isinstance(nfft, (int, np.integer))
            and int(nfft) >= 2
        )
        if not valid_nfft:
            issues.append(ValidationIssue(
                "nfft", "invalid_nfft",
                "fixed nfft must be an integer >= 2",
            ))

    for axis in ("x", "y", "z"):
        issue = _range_issue(params, axis=axis)
        if issue is not None:
            issues.append(issue)

    if method == "order_time":
        if "samples_per_rev" in params:
            samples_per_rev = params.get("samples_per_rev")
            if (
                isinstance(samples_per_rev, (bool, np.bool_))
                or not isinstance(samples_per_rev, (int, np.integer))
                or int(samples_per_rev) < 2
            ):
                issues.append(ValidationIssue(
                    "samples_per_rev", "invalid_samples_per_rev",
                    "samples_per_rev must be an integer >= 2",
                ))

    return tuple(issues)


def validate_task(
    method: str,
    params: Mapping[str, Any] | None,
    *,
    fs: Any,
    sample_count: int,
    time=None,
    rpm_channel: str = "",
    rpm_signal=None,
    rpm_values=None,
) -> tuple[ValidationIssue, ...]:
    """Validate effective per-file facts after the source is loaded."""

    params = params or {}
    issues = list(validate_recipe(
        method, params, rpm_channel=rpm_channel, rpm_signal=rpm_signal,
    ))
    if not _positive_number(fs):
        issues.append(ValidationIssue(
            "fs", "invalid_effective_fs", "effective fs must be finite and > 0",
        ))
        return tuple(issues)

    if int(sample_count) < 2:
        issues.append(ValidationIssue(
            "samples", "too_few_samples", "task requires at least 2 samples",
        ))

    time_range = params.get("time_range")
    if time_range is not None and not any(
        issue.field == "time_range" for issue in issues
    ):
        if time is None:
            issues.append(ValidationIssue(
                "time_range", "missing_time_axis",
                "time_range requires a time axis",
            ))
        else:
            time_arr = np.asarray(time, dtype=float)
            lo, hi = float(time_range[0]), float(time_range[1])
            selected = int(np.count_nonzero(
                np.isfinite(time_arr) & (time_arr >= lo) & (time_arr <= hi)
            ))
            if selected < 2:
                issues.append(ValidationIssue(
                    "time_range", "too_few_samples",
                    "time_range leaves fewer than 2 valid samples",
                ))

    frequency_axis = "x" if method == "fft" else ("y" if method == "fft_time" else None)
    if frequency_axis and not bool(params.get(f"{frequency_axis}_auto", True)):
        maximum = params.get(f"{frequency_axis}_max")
        if _finite_number(maximum) and float(maximum) > 0.5 * float(fs):
            issues.append(ValidationIssue(
                f"{frequency_axis}_range", "above_nyquist",
                f"{frequency_axis}_range maximum exceeds Nyquist "
                f"({0.5 * float(fs):g} Hz)",
            ))

    if method == "order_time":
        effective_rpm = None
        if rpm_values is not None:
            rpm_arr = np.asarray(rpm_values, dtype=float)
            positive_rpm = rpm_arr[np.isfinite(rpm_arr) & (rpm_arr > 0)]
            if positive_rpm.size == 0:
                issues.append(ValidationIssue(
                    "rpm", "invalid_rpm", "RPM must contain a finite positive value",
                ))
            else:
                effective_rpm = float(np.max(positive_rpm))
        if effective_rpm is not None and _positive_number(
            params.get("max_order", 20.0)
        ):
            order_limit = float(fs) * 60.0 / (2.0 * effective_rpm)
            if float(params.get("max_order", 20.0)) > order_limit:
                issues.append(ValidationIssue(
                    "max_order", "above_order_nyquist",
                    f"max_order exceeds effective order Nyquist ({order_limit:g})",
                ))

    return tuple(issues)


def guard_filter_params(
    params: Mapping[str, Any] | None,
    *,
    fs: float,
) -> tuple[dict[str, Any], list[str]]:
    """Return an effective params copy with Nyquist-clamped filter facts."""

    effective = deepcopy(dict(params or {}))
    state = effective.get("filter")
    if not isinstance(state, dict) or not bool(state.get("enabled", False)):
        return effective, []

    from .signal.filters import FilterSpec, nyquist_guard

    guarded, message = nyquist_guard(FilterSpec.from_dict(state.get("spec")), fs)
    state["spec"] = guarded.to_dict()
    return effective, ([message] if message else [])


def raise_for_issues(issues) -> None:
    issues = tuple(issues)
    if issues:
        raise BatchValidationError(issues)


__all__ = [
    "BatchValidationError",
    "ValidationIssue",
    "guard_filter_params",
    "raise_for_issues",
    "resolve_output_image_dimensions",
    "validate_outputs",
    "validate_recipe",
    "validate_task",
]
