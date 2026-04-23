from mf4_analyzer.ui.file_navigator import FileNavigator


def test_file_navigator_constructs(qapp):
    nav = FileNavigator()
    assert nav.channel_list is not None


def test_file_navigator_signals_exist(qapp):
    nav = FileNavigator()
    assert hasattr(nav, 'file_activated')
    assert hasattr(nav, 'file_close_requested')
    assert hasattr(nav, 'close_all_requested')
    assert hasattr(nav, 'channels_changed')
