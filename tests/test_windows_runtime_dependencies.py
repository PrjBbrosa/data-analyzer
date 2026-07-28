from pathlib import Path

import pytest

from mf4_analyzer.io.runtime_dependencies import (
    dependencies_for_extension,
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


def test_current_windows_build_scripts_satisfy_frozen_import_contract():
    failures = validate_windows_packaging_contract(
        ROOT / "requirements.txt",
        (
            ROOT / "tools" / "build_windows_folder.ps1",
            ROOT / "tools" / "build_windows_folder_lite.ps1",
        ),
    )

    assert failures == ()


def test_every_lazy_io_import_is_declared_in_the_frozen_contract():
    """Adding a lazy importer dependency must force a packaging-contract edit."""
    roots = lazy_import_dependency_roots(ROOT / "mf4_analyzer" / "io")

    assert roots == {"av", "can", "cantools", "h5py", "nptdms", "scipy"}


def test_legacy_xls_and_xlsx_have_distinct_frozen_reader_dependencies():
    xls = dependencies_for_extension(".xls")
    xlsx = dependencies_for_extension("xlsx")

    assert [(item.package, item.requirement_name) for item in xls] == [
        ("xlrd", "xlrd")
    ]
    assert [(item.package, item.requirement_name) for item in xlsx] == [
        ("openpyxl", "openpyxl")
    ]
