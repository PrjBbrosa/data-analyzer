"""QComboBox 的两个右侧圆角必须活下来。

``QComboBox::drop-down`` 是覆盖在 combo 右缘的**不透明矩形**子控件。它自己
不带圆角时，填充会直接盖掉父框右上/右下两段边框弧——控件左半边是圆角、
右半边被削成直角，正是用户报的「圆角位置线条没了」。

这里有三层守卫：

1. **统一层** ``test_all_combos_share_one_corner_radius``
   ——所有下拉框的框半径必须是同一个值（7px）。半径每多一档，gutter 补偿规则
   就要多一条、漏配的机会就多一个；收敛成一档之后 gutter 只剩一条规则。

2. **契约层** ``test_every_combo_radius_override_has_matching_dropdown_radius``
   ——静态解析 ``style.qss``：每个 combo **实际生效**的 ``::drop-down`` 圆角
   （自己的规则，没有则回退到全局那条）必须 = 框半径 − 1px 边框宽。这条防的是
   「以后新增一个 combo 皮肤、改了 radius 却忘了补 gutter」——那是本 bug 的
   复发路径，光靠像素测试只能覆盖当下已知的几个选择器。

3. **像素层** ``test_right_corner_arc_survives_the_dropdown_fill``
   ——真渲染后比较左右角的边框墨迹。左侧两角没有任何子控件，是「这个控件的弧
   本该长什么样」的天然基准；圆角四角互为镜像，所以右角墨迹显著少于左角，就
   意味着弧被子控件填充吃掉了。修复前实测比值 0.39–0.48，修复后 0.80–0.96。
"""
import re

import pytest
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QComboBox, QDialog, QVBoxLayout, QWidget

from mf4_analyzer.ui_kit import load_stylesheet
from mf4_analyzer.ui_kit.stylesheet import Path as _stylesheet_path_cls  # noqa: F401

import mf4_analyzer.ui_kit.stylesheet as _stylesheet_mod

# 子控件按 padding box 定位（已被 1px 边框内缩一圈），所以它的弧比父框的弧
# 正好小一个边框宽。实测 7px 会在填充与边框之间留一圈羽化缝，6px 才严丝合缝。
BORDER_WIDTH_PX = 1

_QSS_PATH = _stylesheet_mod.Path(_stylesheet_mod.__file__).resolve().parent / "style.qss"

_BLOCK_RE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)


def _blocks():
    text = _COMMENT_RE.sub("", _QSS_PATH.read_text(encoding="utf-8"))
    for selectors, body in _BLOCK_RE.findall(text):
        yield selectors.strip(), body


def _px(body, prop):
    m = re.search(rf"(?<![\w-]){re.escape(prop)}\s*:\s*(\d+)px", body)
    return int(m.group(1)) if m else None


def _combo_selectors(selectors):
    """逐条拆开选择器列表，只留下真正落在 combo **框本身**上的那几条。

    看的是最后一个后代元素：``QDialog#foo QComboBox`` 命中的是框，而
    ``QComboBox QAbstractItemView`` 命中的是弹出列表——后者是另一个 widget，
    没有 ::drop-down 子控件，不该被要求配 gutter 圆角。
    """
    for sel in selectors.split(","):
        sel = " ".join(sel.split())
        if not sel:
            continue
        target = sel.split()[-1]
        if target.startswith("QComboBox"):
            yield sel


#: 全 app 下拉框统一的圆角。7px 不是 6/7/8 取中，而是输入族
#: （QLineEdit / QSpinBox / QDoubleSpinBox 与 QComboBox 共用文件顶部那条规则）
#: 的既有半径——combo 在表单里大量与它们并排，脱队就会边缘对不齐。
COMBO_RADIUS_PX = 7


def _radius_maps():
    frame_radius = {}
    gutter_radius = {}

    for selectors, body in _blocks():
        for sel in _combo_selectors(selectors):
            if "::drop-down" in sel:
                base = sel.replace("::drop-down", "")
                for prop in ("border-top-right-radius", "border-bottom-right-radius"):
                    value = _px(body, prop)
                    if value is not None:
                        gutter_radius.setdefault(base, {})[prop] = value
            elif "::" not in sel and ":" not in sel:
                # 伪状态块（:hover/:focus/:disabled）只改颜色，不参与几何。
                radius = _px(body, "border-radius")
                if radius is not None:
                    frame_radius[sel] = radius

    assert frame_radius, "没解析到任何 QComboBox 的 border-radius，解析器坏了"
    return frame_radius, gutter_radius


def test_all_combos_share_one_corner_radius():
    """下拉框圆角必须全 app 一个值——这条锁的是「统一」本身。

    以前 combo 有三档半径（行内选择器 6px、标准表单 7px、导入对话框 8px）。
    它们各自都配得上所在的控件高度，但下拉框之间不一致，而且每多一档就要多
    一条 gutter 补偿规则、多一个漏配的机会。收敛到 7px 之后，gutter 规则只剩
    一条；这条测试保证以后不会又长出第二档。
    """
    frame_radius, _ = _radius_maps()
    off_spec = {
        sel: radius
        for sel, radius in frame_radius.items()
        if radius != COMBO_RADIUS_PX
    }
    assert not off_spec, (
        "下拉框圆角必须统一为 "
        f"{COMBO_RADIUS_PX}px，但这些规则另立了值：\n  "
        + "\n  ".join(f"{sel} → {radius}px" for sel, radius in sorted(off_spec.items()))
        + "\n（改半径就得同步改 ::drop-down 的补偿值，见 style.qss 顶部注释）"
    )


def test_every_combo_radius_override_has_matching_dropdown_radius():
    """每个 combo **实际生效**的 gutter 圆角都要等于它的框半径 − 边框宽。

    半径统一之后，全局那条 ``QComboBox::drop-down`` 就覆盖了所有 combo，
    所以这里查的是「自己的 gutter 规则，没有就回退到全局」。谁要是另立了
    框半径却没同时给自己补一条 gutter 规则，这条就会红。
    """
    frame_radius, gutter_radius = _radius_maps()

    base = gutter_radius.get("QComboBox")
    assert base, (
        "全局 `QComboBox::drop-down` 必须显式给出右侧两个圆角——"
        "它是所有下拉框唯一的 gutter 规则"
    )

    problems = []
    for sel, radius in sorted(frame_radius.items()):
        expected = radius - BORDER_WIDTH_PX
        # 后代选择器（QDialog#x QComboBox）也能被全局 QComboBox::drop-down 命中。
        got = gutter_radius.get(sel, base)
        for prop in ("border-top-right-radius", "border-bottom-right-radius"):
            if got.get(prop) != expected:
                problems.append(
                    f"{sel} 的框是 {radius}px，实际生效的 {prop} 却是 "
                    f"{got.get(prop)}px，应为 {expected}px"
                    f"（父 {radius}px − {BORDER_WIDTH_PX}px 边框）"
                )

    assert not problems, "style.qss 圆角契约不符：\n  " + "\n  ".join(problems)


def _corner_ink_ratio(qapp, widget, host, radius_px):
    """右侧两角的边框墨迹量 ÷ 左侧两角。1.0 = 弧完好，明显偏小 = 被盖掉。"""
    qapp.processEvents()
    pixmap = host.grab()
    image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
    dpr = pixmap.devicePixelRatio()

    origin = widget.mapTo(host, widget.rect().topLeft())
    gx, gy = int(origin.x() * dpr), int(origin.y() * dpr)
    gw, gh = int(widget.width() * dpr), int(widget.height() * dpr)
    box = int(radius_px * dpr)

    def rgb(x, y):
        c = image.pixelColor(x, y)
        return c.red(), c.green(), c.blue()

    def luma(c):
        return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]

    background = luma(rgb(max(gx - 3, 0), max(gy - 3, 0)))

    def ink(x0, y0):
        return sum(
            1
            for dy in range(box)
            for dx in range(box)
            if background - luma(rgb(x0 + dx, y0 + dy)) > 6
        )

    left = ink(gx, gy) + ink(gx, gy + gh - box)
    right = ink(gx + gw - box, gy) + ink(gx + gw - box, gy + gh - box)
    assert left > 0, "左侧角落没有任何边框墨迹，说明没渲染出边框，测量无意义"
    return right / left


#: 弧完好判定的下限。修复前实测 0.39–0.48，修复后 0.80–0.96 —— 上限出现在
#: 真机 dpr=2，下限出现在 offscreen dpr=1 的 28px 矮控件上（一个角只有十几个
#: 墨迹像素，一两个抗锯齿像素就能拉低比值）。0.70 卡在两组之间，两侧都有余量。
ARC_INTACT_RATIO = 0.70


@pytest.mark.parametrize(
    "object_name, editable",
    [
        (None, False),
        (None, True),
        ("channelConfigCombo", True),
        ("measurementEventSelect", False),
        ("batchEventSelect", False),
    ],
)
def test_right_corner_arc_survives_the_dropdown_fill(qapp, object_name, editable):
    radius = COMBO_RADIUS_PX
    previous = qapp.styleSheet()
    load_stylesheet(qapp)
    host = QWidget()
    try:
        host.setAutoFillBackground(True)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(20, 20, 20, 20)
        combo = QComboBox()
        combo.addItems(["选配置…"])
        combo.setEditable(editable)
        combo.setMinimumWidth(260)
        if object_name:
            combo.setObjectName(object_name)
        layout.addWidget(combo)
        host.resize(320, 80)
        host.show()

        ratio = _corner_ink_ratio(qapp, combo, host, radius)
        assert ratio > ARC_INTACT_RATIO, (
            f"QComboBox(objectName={object_name!r}) 右侧圆角弧的边框墨迹只有左侧的 "
            f"{ratio:.2f}，说明 ::drop-down 的方角填充盖住了圆角。"
            f"给它补 border-top-right-radius / border-bottom-right-radius "
            f"= {radius - BORDER_WIDTH_PX}px。"
        )
    finally:
        host.close()
        qapp.setStyleSheet(previous)


def test_import_dialog_combo_joins_the_shared_radius(qapp):
    previous = qapp.styleSheet()
    load_stylesheet(qapp)
    dialog = QDialog()
    try:
        dialog.setObjectName("channelConfigHtmlImportDialog")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        combo = QComboBox(dialog)
        combo.addItems(["选择配置"])
        combo.setMinimumWidth(260)
        layout.addWidget(combo)
        dialog.resize(320, 90)
        dialog.show()

        ratio = _corner_ink_ratio(qapp, combo, dialog, COMBO_RADIUS_PX)
        assert ratio > ARC_INTACT_RATIO, (
            f"导入对话框 combo 的右侧圆角墨迹只有左侧的 {ratio:.2f}；"
            f"它虽然沿用邻居的 34px 高度，圆角仍须是 combo 家族的 "
            f"{COMBO_RADIUS_PX}px、gutter {COMBO_RADIUS_PX - BORDER_WIDTH_PX}px。"
        )
    finally:
        dialog.close()
        qapp.setStyleSheet(previous)
