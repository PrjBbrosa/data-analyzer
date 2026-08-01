from types import SimpleNamespace

import numpy as np

from mf4_analyzer.ui.time_xaxis import (
    CustomXAxisSpec,
    apply_unit_cohort,
    channel_unit,
    resolve_custom_xaxis,
    selection_payload,
    spec_from_selection,
)


class _Columns(dict):
    @property
    def columns(self):
        return self.keys()


def _source(*, angle, signal, unit="deg", metadata_unit=""):
    metadata = {"angle": {"unit": metadata_unit}} if metadata_unit else {}
    return SimpleNamespace(
        data=_Columns(
            angle=np.asarray(angle),
            signal=np.asarray(signal),
        ),
        channel_metadata=metadata,
        channel_units={"angle": unit},
        short_name="source",
    )


def test_custom_xaxis_spec_round_trips_new_and_legacy_axis_opts():
    per_source = CustomXAxisSpec(
        mode="channel",
        resolver="per_source_name",
        channel="angle",
        label="Steering angle",
    )
    assert per_source.to_axis_opts() == {
        "mode": "channel",
        "resolver": "per_source_name",
        "fid": None,
        "channel": "angle",
        "label": "Steering angle",
    }
    assert CustomXAxisSpec.from_axis_opts(per_source.to_axis_opts()) == per_source

    legacy = CustomXAxisSpec.from_axis_opts(
        {"mode": "channel", "fid": "f1", "channel": "angle", "label": "Angle"}
    )
    assert legacy == CustomXAxisSpec(
        mode="channel",
        resolver="exact_source",
        channel="angle",
        source_fid="f1",
        label="Angle",
    )
    assert CustomXAxisSpec.from_axis_opts(
        {"mode": "channel", "resolver": "future", "channel": "angle"}
    ).mode == "time"


def test_selection_payload_is_a_tagged_triple():
    per_source = CustomXAxisSpec(
        mode="channel", resolver="per_source_name", channel="angle"
    )
    exact = CustomXAxisSpec(
        mode="channel",
        resolver="exact_source",
        source_fid="f1",
        channel="angle",
    )

    assert selection_payload(per_source) == ("per_source_name", None, "angle")
    assert selection_payload(exact) == ("exact_source", "f1", "angle")
    assert spec_from_selection(("per_source_name", None, "angle"), label="Angle") == (
        CustomXAxisSpec(
            mode="channel",
            resolver="per_source_name",
            channel="angle",
            label="Angle",
        )
    )


def test_channel_unit_prefers_metadata_then_channel_units():
    source = _source(
        angle=[1.0], signal=[2.0], unit="rad", metadata_unit="deg"
    )
    assert channel_unit(source, "angle") == "deg"

    source.channel_metadata = {}
    assert channel_unit(source, "angle") == "rad"


def test_per_source_resolver_uses_each_target_sources_own_x():
    files = {
        "f1": _source(angle=[10.0, 20.0], signal=[1.0, 2.0]),
        "f2": _source(
            angle=[100.0, 200.0, 300.0], signal=[3.0, 4.0, 5.0]
        ),
    }
    spec = CustomXAxisSpec(
        mode="channel", resolver="per_source_name", channel="angle"
    )

    first = resolve_custom_xaxis(
        target_fid="f1", target_channel="signal", files=files, spec=spec
    )
    second = resolve_custom_xaxis(
        target_fid="f2", target_channel="signal", files=files, spec=spec
    )

    assert first.ready
    assert second.ready
    np.testing.assert_array_equal(first.x_values, [10.0, 20.0])
    np.testing.assert_array_equal(second.x_values, [100.0, 200.0, 300.0])


def test_exact_source_resolver_never_switches_to_same_name_in_target_source():
    files = {
        "f1": _source(angle=[10.0, 20.0], signal=[1.0, 2.0]),
        "f2": _source(angle=[100.0, 200.0], signal=[3.0, 4.0]),
    }
    spec = CustomXAxisSpec(
        mode="channel",
        resolver="exact_source",
        source_fid="f1",
        channel="angle",
    )

    result = resolve_custom_xaxis(
        target_fid="f2", target_channel="signal", files=files, spec=spec
    )

    assert result.ready
    np.testing.assert_array_equal(result.x_values, [10.0, 20.0])


def test_resolver_reports_missing_unaligned_and_non_finite_x():
    files = {
        "missing": SimpleNamespace(
            data=_Columns(signal=np.asarray([1.0, 2.0])),
            channel_metadata={},
            channel_units={},
            short_name="missing",
        ),
        "unaligned": _source(angle=[1.0], signal=[1.0, 2.0]),
        "nonfinite": _source(angle=[np.nan, np.inf], signal=[1.0, 2.0]),
    }
    spec = CustomXAxisSpec(
        mode="channel", resolver="per_source_name", channel="angle"
    )

    assert resolve_custom_xaxis(
        target_fid="missing", target_channel="signal", files=files, spec=spec
    ).issue.code == "missing_x_channel"
    assert resolve_custom_xaxis(
        target_fid="unaligned", target_channel="signal", files=files, spec=spec
    ).issue.code == "unaligned"
    assert resolve_custom_xaxis(
        target_fid="nonfinite", target_channel="signal", files=files, spec=spec
    ).issue.code == "non_finite_x"


def test_unit_cohort_uses_normalized_largest_group_and_stable_tie_break():
    files = {
        "f1": _source(angle=[1.0], signal=[1.0], unit="m/s²"),
        "f2": _source(angle=[2.0], signal=[2.0], unit="m/s^2"),
        "f3": _source(angle=[3.0], signal=[3.0], unit="g"),
    }
    spec = CustomXAxisSpec(
        mode="channel", resolver="per_source_name", channel="angle"
    )
    resolutions = tuple(
        resolve_custom_xaxis(
            target_fid=fid, target_channel="signal", files=files, spec=spec
        )
        for fid in files
    )

    selected = apply_unit_cohort(resolutions)

    assert [result.ready for result in selected] == [True, True, False]
    assert selected[2].issue.code == "x_unit_incompatible"

    tie = apply_unit_cohort((resolutions[2], resolutions[0]))
    assert tie[0].ready
    assert not tie[1].ready


def test_unit_cohort_treats_empty_unit_as_fact_not_wildcard():
    files = {
        "empty": _source(angle=[1.0], signal=[1.0], unit=""),
        "rpm": _source(angle=[2.0], signal=[2.0], unit="rpm"),
    }
    spec = CustomXAxisSpec(
        mode="channel", resolver="per_source_name", channel="angle"
    )
    selected = apply_unit_cohort(
        tuple(
            resolve_custom_xaxis(
                target_fid=fid, target_channel="signal", files=files, spec=spec
            )
            for fid in files
        )
    )

    assert selected[0].ready
    assert selected[1].issue.code == "x_unit_incompatible"
