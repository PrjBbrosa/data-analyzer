# tests/ui/test_icons_cloud.py
def test_cloud_download_renders(qapp):
    from mf4_analyzer.ui_kit.icons import Icons
    icon = Icons.cloud_download()
    assert not icon.isNull()
    assert not icon.pixmap(20, 20).isNull()
