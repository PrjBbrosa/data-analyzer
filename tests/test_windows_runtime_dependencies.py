from pathlib import Path

import pytest

from mf4_analyzer.io.runtime_dependencies import (
    COMPONENT_MATLAB,
    COMPONENT_MEDIA,
    MODULAR_EXCLUDED_MODULES,
    component_ownership,
    dependencies_for_component,
    dependencies_for_extension,
    frozen_dependencies_for_profile,
    lazy_import_dependency_roots,
    pyinstaller_collection_args,
    validate_windows_packaging_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def test_mat_import_dependencies_are_frozen_as_a_complete_closure():
    dependencies = dependencies_for_extension(".mat")

    assert [dependency.package for dependency in dependencies] == ["scipy", "h5py"]
    assert pyinstaller_collection_args() == (
        "--collect-all", "asammdf",
        "--collect-all", "openpyxl",
        "--collect-all", "xlrd",
        "--collect-all", "can",
        "--collect-all", "cantools",
        "--collect-all", "nptdms",
        "--collect-all", "av",
        "--collect-all", "scipy",
        "--collect-all", "h5py",
    )


def test_lite_collection_keeps_importer_support_without_whole_scipy():
    args = pyinstaller_collection_args("lite")

    assert args == (
        "--collect-all", "asammdf",
        "--collect-all", "openpyxl",
        "--collect-all", "xlrd",
        "--collect-all", "can",
        "--collect-all", "cantools",
        "--collect-all", "nptdms",
        "--collect-all", "av",
        "--hidden-import", "scipy.io",
        "--hidden-import", "scipy.io.matlab",
        "--collect-all", "h5py",
        "--exclude-module", "scipy.optimize",
        "--exclude-module", "scipy.special",
        "--exclude-module", "scipy.linalg",
        "--exclude-module", "scipy.spatial",
        "--exclude-module", "scipy.interpolate",
        "--exclude-module", "scipy.stats",
        "--exclude-module", "scipy.signal",
        "--exclude-module", "scipy.fft",
        "--exclude-module", "scipy.integrate",
        "--exclude-module", "scipy.ndimage",
    )


def test_collection_rejects_unknown_flavor():
    with pytest.raises(ValueError, match="unknown frozen-build flavor"):
        pyinstaller_collection_args("portable")


def test_collection_rejects_unknown_profile():
    with pytest.raises(ValueError, match="unknown dependency profile"):
        pyinstaller_collection_args("full", "split")


def test_flavor_and_profile_are_independent():
    bundled_full = pyinstaller_collection_args("full", "bundled")
    bundled_lite = pyinstaller_collection_args("lite", "bundled")
    modular_full = pyinstaller_collection_args("full", "modular")
    modular_lite = pyinstaller_collection_args("lite", "modular")

    assert bundled_full == pyinstaller_collection_args()
    assert bundled_lite == pyinstaller_collection_args("lite")
    assert ("--collect-all", "av") not in _pairs(modular_full)
    assert ("--collect-all", "scipy") not in _pairs(modular_full)
    assert ("--collect-all", "h5py") not in _pairs(modular_full)
    assert ("--collect-all", "av") not in _pairs(modular_lite)
    assert ("--hidden-import", "scipy.io") not in _pairs(modular_lite)
    assert modular_full == modular_lite == (
        "--collect-all", "asammdf",
        "--collect-all", "openpyxl",
        "--collect-all", "xlrd",
        "--collect-all", "can",
        "--collect-all", "cantools",
        "--collect-all", "nptdms",
        "--exclude-module", "av",
        "--exclude-module", "scipy",
        "--exclude-module", "h5py",
        "--exclude-module", "hdf5storage",
    )
    assert ("--exclude-module", "av") not in _pairs(bundled_full)
    assert ("--exclude-module", "h5py") not in _pairs(bundled_full)
    assert ("--collect-all", "av") in _pairs(bundled_full)
    assert ("--collect-all", "scipy") in _pairs(bundled_full)
    assert ("--collect-all", "h5py") in _pairs(bundled_full)


def test_modular_profile_excludes_optional_importers_from_analysis():
    """Dropping collect-all is not enough; PYZ still sees function-level imports."""
    args = pyinstaller_collection_args("lite", "modular")
    excluded = tuple(
        value
        for argument, value in zip(args, args[1:])
        if argument == "--exclude-module"
    )
    assert excluded == MODULAR_EXCLUDED_MODULES
    assert "av" in excluded
    assert "hdf5storage" in excluded
    # Splash modules are base GUI feedback, not optional importer trees.
    for splash in (
        "mf4_analyzer.startup_feedback",
        "mf4_analyzer.startup_splash_child",
        "mf4_analyzer.ui.startup_splash",
        "startup_feedback",
        "startup_splash_child",
        "startup_splash",
    ):
        assert splash not in excluded


def _pairs(args: tuple[str, ...]) -> set[tuple[str, str]]:
    return set(zip(args, args[1:]))


def test_component_ownership_keeps_every_lazy_declaration():
    ownership = component_ownership()
    assert ownership["av"] == COMPONENT_MEDIA
    assert ownership["scipy"] == COMPONENT_MATLAB
    assert ownership["h5py"] == COMPONENT_MATLAB
    assert ownership["asammdf"] == "base"
    assert [item.package for item in dependencies_for_component("media")] == ["av"]
    assert [item.package for item in dependencies_for_component("matlab")] == [
        "scipy",
        "h5py",
    ]
    modular_names = {item.package for item in frozen_dependencies_for_profile("modular")}
    assert "av" not in modular_names
    assert "scipy" not in modular_names
    assert "h5py" not in modular_names
    bundled_names = {item.package for item in frozen_dependencies_for_profile("bundled")}
    assert {"av", "scipy", "h5py"}.issubset(bundled_names)


def test_head_hdf_stays_base_and_is_not_h5py():
    assert dependencies_for_extension(".hdf") == ()
    assert "h5py" not in {item.package for item in dependencies_for_extension(".hdf")}


def test_current_windows_build_scripts_satisfy_frozen_import_contract():
    failures = validate_windows_packaging_contract(
        ROOT / "requirements.txt",
        (
            ROOT / "tools" / "build_windows_folder.ps1",
            ROOT / "tools" / "build_windows_folder_lite.ps1",
            ROOT / "tools" / "build_windows_folder_lite_modular.ps1",
        ),
    )

    assert failures == ()


@pytest.mark.parametrize("profile", ["bundled", "modular"])
@pytest.mark.parametrize("excluded", ["av", "scipy.io", "h5py", "asammdf", "can"])
def test_packaging_exclusions_respect_delivery_profile(tmp_path, profile, excluded):
    script = tmp_path / "builder.ps1"
    script.write_text(
        'param([string]$Flavor = "lite", [string]$DependencyProfile = "' + profile + '")\n'
        '$RuntimeDependencyTool = "windows_runtime_dependencies.py"\n'
        '$args = "--pyinstaller-args-json --flavor $Flavor --profile $DependencyProfile"\n'
        f'$args += @("--exclude-module", "{excluded}")\n', encoding="utf-8",
    )
    failures = validate_windows_packaging_contract(ROOT / "requirements.txt", [script])
    if profile == "modular" and excluded in {"av", "scipy.io", "h5py"}:
        assert failures == ()
    else:
        assert any("excludes required runtime dependency" in item for item in failures)


@pytest.mark.parametrize("options", [
    "--flavor $Undeclared --profile modular",
    "--flavor portable --profile modular",
    "--flavor lite --profile $Undeclared",
    "--flavor lite --profile split",
])
def test_packaging_rejects_unresolved_or_unknown_delivery_settings(tmp_path, options):
    script = tmp_path / "builder.ps1"
    script.write_text(
        'windows_runtime_dependencies.py\n' + f'"--pyinstaller-args-json {options}"\n',
        encoding="utf-8",
    )
    assert validate_windows_packaging_contract(ROOT / "requirements.txt", [script])


def test_matplotlib_is_not_a_frozen_product_runtime_dependency():
    """Qt owns every product render path; Matplotlib is development-only."""
    args = pyinstaller_collection_args()
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "matplotlib" not in args
    assert not any(
        line.split("#", 1)[0].strip().lower().startswith("matplotlib")
        for line in requirements.splitlines()
    )


def test_every_lazy_io_import_is_declared_in_the_frozen_contract():
    """Adding a lazy importer dependency must force a packaging-contract edit."""
    roots = lazy_import_dependency_roots(ROOT / "mf4_analyzer" / "io")
    ownership = component_ownership()

    assert roots == {
        "asammdf",
        "av",
        "can",
        "cantools",
        "h5py",
        "nptdms",
        "openpyxl",
        "pandas",
        "scipy",
        "xlrd",
    }
    assert roots <= set(ownership)
    assert {ownership[root] for root in roots} <= {"base", "media", "matlab"}
    assert ownership["av"] == "media"
    assert ownership["scipy"] == "matlab"
    assert ownership["h5py"] == "matlab"
    assert ownership["pandas"] == "base"


def test_pandas_is_declared_as_standard_hook_not_collect_all():
    """Lazy pandas must stay on the contract without expanding --collect-all."""
    from mf4_analyzer.io.runtime_dependencies import (
        COLLECTION_STANDARD_HOOK,
        FROZEN_IMPORT_DEPENDENCIES,
    )

    pandas_deps = [
        item for item in FROZEN_IMPORT_DEPENDENCIES if item.package == "pandas"
    ]
    assert len(pandas_deps) == 1
    assert pandas_deps[0].collection == COLLECTION_STANDARD_HOOK
    assert ("--collect-all", "pandas") not in _pairs(pyinstaller_collection_args())
    assert ("--collect-all", "pandas") not in _pairs(
        pyinstaller_collection_args("lite", "modular")
    )


def test_legacy_xls_and_xlsx_have_distinct_frozen_reader_dependencies():
    xls = dependencies_for_extension(".xls")
    xlsx = dependencies_for_extension("xlsx")

    assert [(item.package, item.requirement_name) for item in xls] == [
        ("xlrd", "xlrd")
    ]
    assert [(item.package, item.requirement_name) for item in xlsx] == [
        ("openpyxl", "openpyxl")
    ]
