"""Chinese tooltip layer for matplotlib NavigationToolbar2QT.

Replaces the english tooltips with concise Chinese text and removes
low-use Back/Forward actions. Preserves the original english key on
each action's ``data()`` slot so downstream code can match by key
(`act.data() == 'save'`) regardless of the visible tooltip.
"""
from PyQt5.QtCore import Qt


# Map normalized english action text -> (chinese tooltip, retain action?)
_ACTION_TOOLTIPS = {
    'home':     ('重置视图', True),
    'back':     ('上一视图', False),
    'forward':  ('下一视图', False),
    'pan':      ('拖动平移（左键拖动）', True),
    'zoom':     ('框选缩放（拖出矩形放大）', True),
    'save':     ('保存图片', True),
    'subplots': ('', False),
    'configure subplots': ('', False),
}


def apply_chinese_toolbar_labels(toolbar):
    """Mutate ``toolbar``: drop Back/Forward/Subplots actions; replace
    tooltip text on remaining actions; preserve the original english key
    in ``act.data()`` so downstream lookups stay stable across matplotlib
    versions and locale changes.
    """
    for act in list(toolbar.actions()):
        key = (act.text() or '').strip().lower()
        if key not in _ACTION_TOOLTIPS:
            continue
        zh_tooltip, retain = _ACTION_TOOLTIPS[key]
        if not retain:
            toolbar.removeAction(act)
            continue
        act.setData(key)
        act.setToolTip(zh_tooltip)
    toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
