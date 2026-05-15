"""Font setup helpers (Chinese rendering for matplotlib/PyQt)."""
import platform


def _log(message: str):
    try:
        print(message)
    except UnicodeEncodeError:
        print(message.encode("ascii", errors="replace").decode("ascii"))


# ========== 中文字体配置 ==========
def setup_chinese_font():
    """配置matplotlib中文字体"""
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    # 根据操作系统选择字体
    system = platform.system()

    # 候选字体列表（按优先级）
    if system == 'Windows':
        font_candidates = ['Microsoft YaHei', 'SimHei', 'SimSun', 'KaiTi', 'FangSong']
    elif system == 'Darwin':  # macOS
        font_candidates = ['PingFang SC', 'Heiti SC', 'STHeiti', 'Hiragino Sans GB']
    else:  # Linux
        font_candidates = ['WenQuanYi Micro Hei', 'WenQuanYi Zen Hei', 'Noto Sans CJK SC', 'Droid Sans Fallback',
                           'SimHei']

    # 获取系统可用字体
    available_fonts = set(f.name for f in font_manager.fontManager.ttflist)

    # 选择第一个可用的字体
    selected_font = None
    for font in font_candidates:
        if font in available_fonts:
            selected_font = font
            break

    if selected_font:
        plt.rcParams['font.sans-serif'] = [selected_font] + plt.rcParams['font.sans-serif']
        _log(f"[Font] Using Chinese font: {selected_font}")
    else:
        # 如果没有找到中文字体，尝试使用系统默认
        plt.rcParams['font.sans-serif'] = ['DejaVu Sans'] + font_candidates
        _log("[Font] Warning: no Chinese font found; text may render incorrectly")

    # 解决负号显示问题
    plt.rcParams['axes.unicode_minus'] = False


__all__ = ['setup_chinese_font']
