# tests/ui/test_update_indicator.py
def test_update_button_opens_release_url(qapp, monkeypatch):
    from PyQt5.QtGui import QDesktopServices
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer import app_meta

    captured = {}
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        lambda url: captured.__setitem__("url", url.toString()) or True)

    mw = MainWindow()
    assert mw._update_btn.toolTip() == f"检查更新\n{app_meta.APP_CREDIT}"
    assert mw._update_btn.text() == app_meta.APP_VERSION
    mw._update_btn.click()
    assert captured["url"] == app_meta.RELEASE_URL
