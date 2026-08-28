"""叠加共轴组的固定色板。

由通道树（组徽标）与 overlay 绘图（共享轴画笔）共用，使某组在树里的徽标色与
图上的共享轴色一致。
"""

_AXIS_GROUP_COLORS = (
    "#f97316",  # orange
    "#0ea5e9",  # sky
    "#a855f7",  # violet
    "#10b981",  # emerald
    "#ef4444",  # red
    "#eab308",  # amber
)


def axis_group_color(group_id):
    """返回 ``group_id``（1 基）对应的组色，循环使用。非正数回退首色。"""
    try:
        index = int(group_id)
    except (TypeError, ValueError):
        digest = 0
        for char in str(group_id):
            digest = (digest * 33 + ord(char)) & 0xFFFFFFFF
        index = (digest % len(_AXIS_GROUP_COLORS)) + 1
    if not group_id or index < 1:
        return _AXIS_GROUP_COLORS[0]
    return _AXIS_GROUP_COLORS[(index - 1) % len(_AXIS_GROUP_COLORS)]
