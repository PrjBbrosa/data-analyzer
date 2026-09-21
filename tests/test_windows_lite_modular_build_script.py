from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LITE = ROOT / "tools" / "build_windows_folder_lite.ps1"
MODULAR = ROOT / "tools" / "build_windows_folder_lite_modular.ps1"
MODULAR_BAT = ROOT / "tools" / "build_windows_folder_lite_modular.bat"


def test_original_lite_packager_stays_bundled():
    text = LITE.read_text(encoding="utf-8")
    assert "--profile modular" not in text
    assert "--pyinstaller-args-json --flavor lite" in text
    assert "--pyinstaller-args-json --flavor lite --profile modular" not in text
    assert 'Join-Path $RepoRoot ".state\\build-evidence\\lite\\$BuildRunId"' in text
    assert "TraceLabAnalyzer${Version}-modular" not in text


def test_modular_packager_is_a_separate_lite_copy():
    text = MODULAR.read_text(encoding="utf-8")
    bat = MODULAR_BAT.read_text(encoding="utf-8")

    assert MODULAR.exists()
    assert "--pyinstaller-args-json --flavor lite --profile modular" in text
    assert "[string[]](ConvertFrom-Json -InputObject $RuntimeDependencyArgsJson)" in text
    assert 'Join-Path $RepoRoot "build\\pyinstaller-lite-modular"' in text
    assert 'Join-Path $RepoRoot "build\\spec-lite-modular"' in text
    assert 'Join-Path $RepoRoot ".state\\build-evidence\\lite-modular\\$BuildRunId"' in text
    assert "TraceLabAnalyzer${Version}-modular" in text
    assert "libscipy_openblas*.dll" not in text
    assert "Modular base leaked optional importer trees" in text
    assert "Skipping lite importer smoke" in text
    assert 'Invoke-IndependentPostCheck -Name "importer"' not in text
    assert "build_windows_folder_lite_modular.ps1" in bat
    assert "build_windows_folder_lite.ps1" not in bat.replace(
        "build_windows_folder_lite_modular.ps1", ""
    )
