#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MF4/CSV/Excel Data Analysis Tool v5.0 - Multi-file Support
Author: Claude for Hang | Date: 2026-02
"""
import sys, time as _time
import numpy as np
import pandas as pd
from pathlib import Path
from collections import OrderedDict
import platform

from PyQt5.QtWidgets import *
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QColor, QBrush

import matplotlib

matplotlib.use('Qt5Agg')


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
        print(f"[Font] 使用中文字体: {selected_font}")
    else:
        # 如果没有找到中文字体，尝试使用系统默认
        plt.rcParams['font.sans-serif'] = ['DejaVu Sans'] + font_candidates
        print("[Font] 警告: 未找到中文字体，可能显示乱码")

    # 解决负号显示问题
    plt.rcParams['axes.unicode_minus'] = False


# 初始化字体
setup_chinese_font()
# ================================

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
from matplotlib.widgets import SpanSelector
from matplotlib.ticker import MaxNLocator

try:
    from asammdf import MDF

    HAS_ASAMMDF = True
except ImportError:
    HAS_ASAMMDF = False

try:
    import openpyxl

    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

FILE_PALETTES = [
    ['#1f77b4', '#4a9fd4', '#7ec7f2', '#b0e0ff'],
    ['#ff7f0e', '#ffaa4d', '#ffc87c', '#ffe5b4'],
    ['#2ca02c', '#5cd35c', '#8de68d', '#bef9be'],
    ['#d62728', '#e85a5a', '#f08c8c', '#f8bebe'],
    ['#9467bd', '#b591d1', '#d5b9e5', '#f0e0f9'],
]


class DataLoader:
    @staticmethod
    def load_mf4(fp):
        if not HAS_ASAMMDF: raise ImportError("asammdf not installed")
        mdf = MDF(fp)

        # 收集所有通道及其位置信息
        channel_locations = {}  # {channel_name: [(group, index), ...]}
        for name, occurrences in mdf.channels_db.items():
            if not name.startswith('$') and name.strip():
                channel_locations[name] = list(occurrences)

        if not channel_locations:
            mdf.close()
            raise ValueError("No channels")

        max_len, ref_ts, sigs, units = 0, None, {}, {}

        for ch_name, locations in channel_locations.items():
            # 取第一个occurrence
            group_idx, ch_idx = locations[0]
            try:
                sig = mdf.get(ch_name, group=group_idx, index=ch_idx)
                if sig.samples is not None and len(sig.samples) > 0 and np.issubdtype(sig.samples.dtype, np.number):
                    s = sig.samples.flatten() if len(sig.samples.shape) > 1 else sig.samples
                    sigs[ch_name] = {'s': np.array(s, float), 't': np.array(sig.timestamps, float)}
                    units[ch_name] = str(getattr(sig, 'unit', '') or '')
                    if len(sig.timestamps) > max_len:
                        max_len = len(sig.timestamps)
                        ref_ts = np.array(sig.timestamps, float)
            except Exception as e:
                # 如果带group/index失败，尝试不带参数（兼容旧版本）
                try:
                    sig = mdf.get(ch_name)
                    if sig.samples is not None and len(sig.samples) > 0 and np.issubdtype(sig.samples.dtype, np.number):
                        s = sig.samples.flatten() if len(sig.samples.shape) > 1 else sig.samples
                        sigs[ch_name] = {'s': np.array(s, float), 't': np.array(sig.timestamps, float)}
                        units[ch_name] = str(getattr(sig, 'unit', '') or '')
                        if len(sig.timestamps) > max_len:
                            max_len = len(sig.timestamps)
                            ref_ts = np.array(sig.timestamps, float)
                except:
                    pass

        mdf.close()
        if ref_ts is None: raise ValueError("No valid numeric data")

        data = {'Time': ref_ts}
        for ch, d in sigs.items():
            try:
                if len(d['s']) == max_len:
                    data[ch] = d['s']
                elif len(d['t']) > 1 and np.all(np.diff(d['t']) > 0):
                    data[ch] = np.interp(ref_ts, d['t'], d['s'])
            except:
                pass

        return pd.DataFrame(data), list(data.keys()), units

    @staticmethod
    def load_csv(fp):
        df = None
        for enc in ['utf-8', 'gbk', 'latin1']:
            for sep in [',', ';', '\t']:
                try:
                    df = pd.read_csv(fp, encoding=enc, sep=sep)
                    if len(df.columns) > 1: break
                except:
                    continue
            if df is not None and len(df.columns) > 1: break
        if df is None: raise ValueError("Cannot parse CSV")
        for col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna(axis=1, how='all').interpolate().dropna()
        return df, list(df.columns), {}

    @staticmethod
    def load_excel(fp):
        kw = {'engine': 'openpyxl'} if HAS_OPENPYXL else {}
        df = pd.read_excel(fp, **kw)
        for col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna(how='all').interpolate().ffill().bfill().reset_index(drop=True)
        return df, list(df.columns), {}


class FileData:
    def __init__(self, fp, df, chs, units, idx=0):
        self.filepath = Path(fp)
        self.filename = self.filepath.name
        self.short_name = self.filepath.stem[:18]
        self.data = df
        self.channels = chs
        self.channel_units = units
        self.file_index = idx
        self.time_array = None
        self.fs = 1000.0
        self._time_source = 'auto'  # 'auto', 'column', 'generated'

        # 尝试从列名识别时间列
        for ch in chs:
            if ch.lower() in ('time', 't', 'zeit', 'timestamp', 'time_s', 'time(s)', 't(s)'):
                self.time_array = df[ch].values.astype(float)
                if len(self.time_array) > 1:
                    dt = np.median(np.diff(self.time_array))
                    if dt > 0:
                        self.fs = 1.0 / dt
                        self._time_source = 'column'
                break

        # 如果没有时间列，根据采样率生成
        if self.time_array is None:
            self.time_array = np.arange(len(df), dtype=float) / self.fs
            self._time_source = 'generated'

    def rebuild_time_axis(self, fs):
        """根据新的采样率重建时间轴"""
        self.fs = fs
        n = len(self.data)
        self.time_array = np.arange(n, dtype=float) / fs
        self._time_source = 'manual'

    def get_signal_channels(self):
        return [c for c in self.channels if
                c.lower() not in ('time', 't', 'zeit', 'timestamp', 'time_s', 'time(s)', 't(s)')]

    def get_prefixed_channel(self, ch):
        return f"[{self.short_name}] {ch}"

    def get_color_palette(self):
        return FILE_PALETTES[self.file_index % len(FILE_PALETTES)]


class FFTAnalyzer:
    @staticmethod
    def get_window(name, n):
        wins = {
            'hanning': np.hanning, 'hamming': np.hamming, 'blackman': np.blackman,
            'bartlett': np.bartlett, 'kaiser': lambda n: np.kaiser(n, 14),
            'flattop': lambda n: np.ones(n) * 0.21557895 - 0.41663158 * np.cos(
                2 * np.pi * np.arange(n) / (n - 1)) + 0.277263158 * np.cos(
                4 * np.pi * np.arange(n) / (n - 1)) - 0.083578947 * np.cos(
                6 * np.pi * np.arange(n) / (n - 1)) + 0.006947368 * np.cos(8 * np.pi * np.arange(n) / (n - 1))
        }
        return wins.get(name, np.hanning)(n)

    @staticmethod
    def compute_fft(sig, fs, win='hanning', nfft=None):
        n = len(sig)
        if nfft is None or nfft <= 0:
            nfft = n
        w = FFTAnalyzer.get_window(win, n)
        sig = sig - np.mean(sig)
        # 零填充到nfft
        if nfft > n:
            sig_padded = np.zeros(nfft)
            sig_padded[:n] = sig * w
        else:
            sig_padded = sig * w
            nfft = n
        fft_r = np.fft.fft(sig_padded)
        nh = nfft // 2
        freq = np.fft.fftfreq(nfft, 1 / fs)[:nh]
        amp = 2 * np.abs(fft_r[:nh]) / n / np.mean(w)
        return freq, amp

    @staticmethod
    def compute_psd(sig, fs, win='hanning', nfft=None):
        f, a = FFTAnalyzer.compute_fft(sig, fs, win, nfft)
        return f, a ** 2

    @staticmethod
    def compute_averaged_fft(sig, fs, win='hanning', nfft=1024, overlap=0.5):
        """计算平均FFT (Welch方法)"""
        n = len(sig)
        hop = int(nfft * (1 - overlap))
        if hop <= 0: hop = nfft // 2
        n_segments = max((n - nfft) // hop + 1, 1)

        w = FFTAnalyzer.get_window(win, nfft)
        w_sum = np.sum(w)

        freq = np.fft.fftfreq(nfft, 1 / fs)[:nfft // 2]
        psd_sum = np.zeros(nfft // 2)

        for i in range(n_segments):
            start = i * hop
            end = start + nfft
            if end > n: break
            seg = sig[start:end] - np.mean(sig[start:end])
            fft_r = np.fft.fft(seg * w)
            psd_sum += np.abs(fft_r[:nfft // 2]) ** 2

        psd = psd_sum / n_segments / (w_sum ** 2) * 2
        amp = np.sqrt(psd)
        return freq, amp, psd


class OrderAnalyzer:
    @staticmethod
    def compute_order_spectrum_time_based(sig, rpm, t, fs, max_ord=20, order_res=0.1, time_res=0.05, nfft=1024,
                                          progress_callback=None):
        """时间-阶次谱，优化版本"""
        orders = np.arange(order_res, max_ord + order_res, order_res)
        seg_sz = nfft
        hop = max(int(fs * time_res), 1)
        n_segments = max((len(sig) - seg_sz) // hop, 1)

        # 预计算窗函数
        window = np.hanning(seg_sz)

        tb, om = [], []
        for idx, i in enumerate(range(0, len(sig) - seg_sz, hop)):
            if progress_callback and idx % 20 == 0:
                progress_callback(idx, n_segments)

            seg = sig[i:i + seg_sz]
            seg_rpm = np.mean(rpm[i:i + seg_sz])
            tb.append(t[i + seg_sz // 2] if t is not None else i / fs)

            # FFT
            seg_win = (seg - np.mean(seg)) * window
            fft_r = np.fft.fft(seg_win, n=nfft)
            freq = np.fft.fftfreq(nfft, 1 / fs)[:nfft // 2]
            amp = 2 * np.abs(fft_r[:nfft // 2]) / seg_sz

            # 提取各阶次能量
            oa = np.zeros(len(orders))
            freq_per_order = abs(seg_rpm) / 60.0
            if freq_per_order > 0:
                for j, o in enumerate(orders):
                    of = o * freq_per_order
                    if 0 < of < fs / 2:
                        bw = max(order_res * freq_per_order * 0.5, freq[1] - freq[0] if len(freq) > 1 else 1)
                        m = (freq >= of - bw) & (freq <= of + bw)
                        if np.any(m):
                            oa[j] = np.sqrt(np.sum(amp[m] ** 2))
            om.append(oa)

        if progress_callback:
            progress_callback(n_segments, n_segments)

        return np.array(tb), orders, np.array(om)

    @staticmethod
    def compute_order_spectrum(sig, rpm, fs, max_ord=20, rpm_res=10, order_res=0.25, nfft=1024, progress_callback=None):
        """转速-阶次谱，优化版本"""
        rpm_bins = np.arange(np.min(rpm), np.max(rpm) + rpm_res, rpm_res)
        orders = np.arange(order_res, max_ord + order_res, order_res)
        om = np.zeros((len(rpm_bins), len(orders)))
        cm = np.zeros_like(om)

        seg_sz = nfft
        hop = seg_sz // 4  # 75%重叠
        window = np.hanning(seg_sz)
        n_segments = max((len(sig) - seg_sz) // hop, 1)

        for idx, i in enumerate(range(0, len(sig) - seg_sz, hop)):
            if progress_callback and idx % 20 == 0:
                progress_callback(idx, n_segments)

            seg = sig[i:i + seg_sz]
            sr = np.mean(rpm[i:i + seg_sz])
            ri = np.argmin(np.abs(rpm_bins - sr))
            if ri >= len(rpm_bins): continue

            # FFT
            seg_win = (seg - np.mean(seg)) * window
            fft_r = np.fft.fft(seg_win, n=nfft)
            freq = np.fft.fftfreq(nfft, 1 / fs)[:nfft // 2]
            amp = 2 * np.abs(fft_r[:nfft // 2]) / seg_sz

            freq_per_order = abs(sr) / 60.0
            if freq_per_order > 0:
                for j, o in enumerate(orders):
                    of = o * freq_per_order
                    bw = order_res * freq_per_order * 0.5
                    m = (freq >= of - bw) & (freq <= of + bw)
                    if np.any(m):
                        om[ri, j] += np.sqrt(np.mean(amp[m] ** 2))
                        cm[ri, j] += 1

        if progress_callback:
            progress_callback(n_segments, n_segments)

        cm[cm == 0] = 1
        return orders, rpm_bins, om / cm

    @staticmethod
    def extract_order_track(sig, rpm, fs, target, nfft=1024):
        """单阶次跟踪"""
        seg_sz = nfft
        hop = seg_sz // 4
        window = np.hanning(seg_sz)
        rt, oa = [], []

        for i in range(0, len(sig) - seg_sz, hop):
            seg = sig[i:i + seg_sz]
            sr = np.mean(rpm[i:i + seg_sz])

            seg_win = (seg - np.mean(seg)) * window
            fft_r = np.fft.fft(seg_win, n=nfft)
            freq = np.fft.fftfreq(nfft, 1 / fs)[:nfft // 2]
            amp = 2 * np.abs(fft_r[:nfft // 2]) / seg_sz

            of = target * abs(sr) / 60.0
            bw = 0.25 * abs(sr) / 60.0
            m = (freq >= of - bw) & (freq <= of + bw)
            rt.append(sr)
            oa.append(np.sqrt(np.mean(amp[m] ** 2)) if np.any(m) else 0)

        return np.array(rt), np.array(oa)


class ChannelMath:
    @staticmethod
    def derivative(t, sig): return np.gradient(sig, t)

    @staticmethod
    def integral(t, sig):
        r = np.zeros_like(sig);
        r[1:] = np.cumsum(0.5 * (sig[1:] + sig[:-1]) * np.diff(t));
        return r

    @staticmethod
    def scale(sig, f): return sig * f

    @staticmethod
    def offset(sig, v): return sig + v

    @staticmethod
    def moving_avg(sig, ws=50): return np.convolve(sig, np.ones(ws) / ws, mode='same')


class ChannelEditorDialog(QDialog):
    def __init__(self, parent, fd):
        super().__init__(parent)
        self.setWindowTitle(f"通道编辑 - {fd.filename}")
        self.setMinimumSize(500, 420)
        self.fd = fd
        self.new_channels = {};
        self.removed_channels = set()
        layout = QVBoxLayout(self)
        chs = fd.get_signal_channels()

        # 单通道运算
        g = QGroupBox("单通道运算");
        gl = QGridLayout(g)
        gl.addWidget(QLabel("源:"), 0, 0)
        self.combo_src = QComboBox();
        self.combo_src.addItems(chs);
        gl.addWidget(self.combo_src, 0, 1)
        gl.addWidget(QLabel("运算:"), 1, 0)
        self.combo_op = QComboBox();
        self.combo_op.addItems(["d/dt", "∫dt", "× 系数", "+ 偏移", "滑动平均", "|x| 绝对值"]);
        gl.addWidget(self.combo_op, 1, 1)
        gl.addWidget(QLabel("参数:"), 2, 0)
        self.spin_p = QDoubleSpinBox();
        self.spin_p.setRange(-1e12, 1e12);
        self.spin_p.setValue(1);
        gl.addWidget(self.spin_p, 2, 1)
        btn = QPushButton("✚ 创建");
        btn.clicked.connect(self._create_single);
        gl.addWidget(btn, 3, 0, 1, 2)
        layout.addWidget(g)

        # 双通道运算
        g2 = QGroupBox("双通道运算 (A ⊕ B)");
        gl2 = QGridLayout(g2)
        gl2.addWidget(QLabel("通道A:"), 0, 0)
        self.combo_a = QComboBox();
        self.combo_a.addItems(chs);
        gl2.addWidget(self.combo_a, 0, 1)
        gl2.addWidget(QLabel("运算:"), 1, 0)
        self.combo_op2 = QComboBox();
        self.combo_op2.addItems(["A + B", "A - B", "A × B", "A ÷ B", "max(A,B)", "min(A,B)"]);
        gl2.addWidget(self.combo_op2, 1, 1)
        gl2.addWidget(QLabel("通道B:"), 2, 0)
        self.combo_b = QComboBox();
        self.combo_b.addItems(chs);
        gl2.addWidget(self.combo_b, 2, 1)
        gl2.addWidget(QLabel("新名称:"), 3, 0)
        self.edit_name2 = QLineEdit();
        self.edit_name2.setPlaceholderText("留空自动生成");
        gl2.addWidget(self.edit_name2, 3, 1)
        btn2 = QPushButton("✚ 创建");
        btn2.clicked.connect(self._create_dual);
        gl2.addWidget(btn2, 4, 0, 1, 2)
        layout.addWidget(g2)

        # 删除通道
        g3 = QGroupBox("删除");
        g3l = QVBoxLayout(g3)
        self.list_rm = QListWidget();
        self.list_rm.setSelectionMode(QListWidget.ExtendedSelection);
        self.list_rm.setMaximumHeight(70)
        for ch in chs: self.list_rm.addItem(ch)
        g3l.addWidget(self.list_rm)
        btn_rm = QPushButton("🗑 删除");
        btn_rm.clicked.connect(self._remove);
        g3l.addWidget(btn_rm)
        layout.addWidget(g3)

        self.lbl = QLabel(f"新增: 0");
        layout.addWidget(self.lbl)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept);
        bb.rejected.connect(self.reject);
        layout.addWidget(bb)

    def _create_single(self):
        src = self.combo_src.currentText()
        if src not in self.fd.data.columns: return
        sig = self.fd.data[src].values.astype(float)
        t = self.fd.time_array;
        op = self.combo_op.currentIndex();
        p = self.spin_p.value()
        prefixes = ["d_dt_", "int_", "scaled_", "offset_", "mavg_", "abs_"]
        try:
            if op == 0:
                r = ChannelMath.derivative(t, sig)
            elif op == 1:
                r = ChannelMath.integral(t, sig)
            elif op == 2:
                r = ChannelMath.scale(sig, p)
            elif op == 3:
                r = ChannelMath.offset(sig, p)
            elif op == 4:
                r = ChannelMath.moving_avg(sig, max(int(p), 3))
            elif op == 5:
                r = np.abs(sig)
            else:
                return
            name = f"{prefixes[op]}{src}"
            while name in self.fd.data.columns or name in self.new_channels: name += "_1"
            self.new_channels[name] = (r, self.fd.channel_units.get(src, ''))
            self.lbl.setText(f"新增: {len(self.new_channels)} ({name})")
            self.combo_src.addItem(name);
            self.combo_a.addItem(name);
            self.combo_b.addItem(name)
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def _create_dual(self):
        ch_a = self.combo_a.currentText()
        ch_b = self.combo_b.currentText()
        if ch_a not in self.fd.data.columns and ch_a not in self.new_channels: return
        if ch_b not in self.fd.data.columns and ch_b not in self.new_channels: return

        # 获取数据
        if ch_a in self.new_channels:
            sig_a = self.new_channels[ch_a][0]
        else:
            sig_a = self.fd.data[ch_a].values.astype(float)
        if ch_b in self.new_channels:
            sig_b = self.new_channels[ch_b][0]
        else:
            sig_b = self.fd.data[ch_b].values.astype(float)

        if len(sig_a) != len(sig_b):
            QMessageBox.warning(self, "错误", f"通道长度不匹配: {len(sig_a)} vs {len(sig_b)}")
            return

        op = self.combo_op2.currentIndex()
        op_symbols = ["add", "sub", "mul", "div", "max", "min"]
        try:
            if op == 0:
                r = sig_a + sig_b
            elif op == 1:
                r = sig_a - sig_b
            elif op == 2:
                r = sig_a * sig_b
            elif op == 3:
                with np.errstate(divide='ignore', invalid='ignore'):
                    r = np.where(sig_b != 0, sig_a / sig_b, 0)
            elif op == 4:
                r = np.maximum(sig_a, sig_b)
            elif op == 5:
                r = np.minimum(sig_a, sig_b)
            else:
                return

            # 生成名称
            name = self.edit_name2.text().strip()
            if not name:
                name = f"{op_symbols[op]}_{ch_a[:8]}_{ch_b[:8]}"
            while name in self.fd.data.columns or name in self.new_channels: name += "_1"

            # 合并单位
            unit_a = self.fd.channel_units.get(ch_a, '')
            unit_b = self.fd.channel_units.get(ch_b, '')
            unit = unit_a if unit_a == unit_b else f"{unit_a}/{unit_b}" if op == 3 else ""

            self.new_channels[name] = (r, unit)
            self.lbl.setText(f"新增: {len(self.new_channels)} ({name})")
            self.combo_src.addItem(name);
            self.combo_a.addItem(name);
            self.combo_b.addItem(name)
            self.edit_name2.clear()
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def _remove(self):
        sel = [i.text() for i in self.list_rm.selectedItems()]
        if sel and QMessageBox.question(self, "确认", f"删除 {len(sel)} 通道?",
                                        QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.removed_channels.update(sel)
            for i in self.list_rm.selectedItems(): self.list_rm.takeItem(self.list_rm.row(i))


class ExportDialog(QDialog):
    def __init__(self, parent, chs):
        super().__init__(parent)
        self.setWindowTitle("导出Excel");
        self.setMinimumSize(280, 300)
        layout = QVBoxLayout(self)
        self.list_ch = QListWidget()
        for ch in chs:
            item = QListWidgetItem(ch);
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable);
            item.setCheckState(Qt.Checked)
            self.list_ch.addItem(item)
        layout.addWidget(self.list_ch)
        self.chk_time = QCheckBox("包含时间列");
        self.chk_time.setChecked(True);
        layout.addWidget(self.chk_time)
        self.chk_range = QCheckBox("仅导出选定范围");
        layout.addWidget(self.chk_range)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept);
        bb.rejected.connect(self.reject);
        layout.addWidget(bb)

    def get_selected(self):
        return [self.list_ch.item(i).text() for i in range(self.list_ch.count()) if
                self.list_ch.item(i).checkState() == Qt.Checked]


class TimeDomainCanvas(FigureCanvas):
    MAX_PTS = 8000
    cursor_info = pyqtSignal(str)
    dual_cursor_info = pyqtSignal(str)

    def __init__(self, parent=None):
        self.fig = Figure(figsize=(10, 6), dpi=100)
        super().__init__(self.fig)
        self.setParent(parent)
        self.axes_list = [];
        self.lines = {};
        self.channel_data = {}
        self.span_selector = None
        self._cursor_visible = False;
        self._bg = None;
        self._cursor_artists = [];
        self._last_t = 0;
        self._refresh = True
        self._dual = False;
        self._ax = None;
        self._bx = None;
        self._placing = 'A'
        self._a_artists = [];
        self._b_artists = []
        self.mpl_connect('motion_notify_event', self._on_move)
        self.mpl_connect('scroll_event', self._on_scroll)
        self.mpl_connect('draw_event', lambda e: setattr(self, '_refresh', True))
        self.mpl_connect('button_press_event', self._on_click)
        self.setFocusPolicy(Qt.StrongFocus)

    def clear(self):
        self.fig.clear();
        self.axes_list = [];
        self.lines = {};
        self.channel_data = {}
        self._cursor_artists = [];
        self._a_artists = [];
        self._b_artists = [];
        self._bg = None;
        self._refresh = True
        self._ax = None;
        self._bx = None

    def plot_channels(self, ch_list, mode='overlay', xlabel='Time (s)'):
        self.clear()
        vis = [(n, t, s, c, u) for n, v, t, s, c, u in ch_list if v]
        if not vis: self.draw(); return
        if mode == 'subplot' and len(vis) > 1:
            n = len(vis);
            first = None
            for i, (name, t, sig, color, unit) in enumerate(vis):
                ax = self.fig.add_subplot(n, 1, i + 1, sharex=first) if i > 0 else self.fig.add_subplot(n, 1, 1)
                if i == 0: first = ax
                self.axes_list.append(ax)
                td, sd = self._ds(t, sig)
                ax.plot(td, sd, color=color, lw=0.8)
                self.channel_data[name] = (t, sig, color, unit)
                ax.set_ylabel(name[:22], fontsize=8, color=color)
                ax.tick_params(axis='y', colors=color, labelsize=7)
                ax.spines['left'].set_color(color);
                ax.spines['left'].set_linewidth(2)
                ax.grid(True, alpha=0.25, ls='--')
                if i < n - 1:
                    ax.tick_params(axis='x', labelbottom=False)
                else:
                    ax.set_xlabel(xlabel, fontsize=9)
            self.fig.subplots_adjust(hspace=0.05, left=0.12, right=0.96, top=0.97, bottom=0.07)
        else:
            ax = self.fig.add_subplot(1, 1, 1);
            self.axes_list.append(ax)
            for name, t, sig, color, unit in vis:
                td, sd = self._ds(t, sig)
                ax.plot(td, sd, color=color, lw=0.8, label=name[:18], alpha=0.85)
                self.channel_data[name] = (t, sig, color, unit)
            ax.legend(loc='upper right', fontsize=7, ncol=min(3, len(vis)))
            ax.set_xlabel(xlabel, fontsize=9);
            ax.grid(True, alpha=0.25, ls='--')
            self.fig.tight_layout(pad=0.5)
        for ax in self.axes_list:
            ax.xaxis.set_major_locator(MaxNLocator(nbins=10, min_n_ticks=3))
            ax.yaxis.set_major_locator(MaxNLocator(nbins=6, min_n_ticks=3))
        self.draw();
        self._refresh = True

    def _ds(self, t, sig):
        n = len(sig)
        if n <= self.MAX_PTS: return t, sig
        bs = n // (self.MAX_PTS // 2)
        if bs < 2: return t, sig
        idx = []
        for s in range(0, n, bs):
            e = min(s + bs, n);
            c = sig[s:e]
            idx.extend([s + np.argmin(c), s + np.argmax(c)])
        idx = np.unique(np.clip(idx, 0, n - 1))
        return t[idx], sig[idx]

    def set_tick_density(self, x, y):
        for ax in self.axes_list:
            ax.xaxis.set_major_locator(MaxNLocator(nbins=x, min_n_ticks=3))
            ax.yaxis.set_major_locator(MaxNLocator(nbins=y, min_n_ticks=3))
        self._refresh = True;
        self.draw_idle()

    def enable_span_selector(self, cb):
        if self.axes_list:
            self.span_selector = SpanSelector(self.axes_list[-1], cb, 'horizontal', useblit=True, interactive=True,
                                              props=dict(alpha=0.2, facecolor='yellow'))

    def set_cursor_visible(self, v):
        self._cursor_visible = v
        if not v:
            for a in self._cursor_artists + self._a_artists + self._b_artists: a.set_visible(False)
            self.draw_idle()

    def set_dual_cursor_mode(self, en):
        self._dual = en
        if not en:
            self._ax = self._bx = None;
            self._placing = 'A'
            for a in self._a_artists + self._b_artists: a.set_visible(False)
            self._a_artists.clear();
            self._b_artists.clear()
            self._refresh = True;
            self.draw_idle()

    def _ensure_artists(self):
        if self._cursor_artists: return
        for ax in self.axes_list:
            self._cursor_artists.append(
                ax.axvline(x=0, color='red', lw=0.7, ls='--', alpha=0.7, animated=True, visible=False))
        self._refresh = True

    def _ensure_dual(self):
        if not self._a_artists:
            for ax in self.axes_list: self._a_artists.append(
                ax.axvline(x=0, color='#00BFFF', lw=1.5, alpha=0.9, animated=True, visible=False))
        if not self._b_artists:
            for ax in self.axes_list: self._b_artists.append(
                ax.axvline(x=0, color='#FF6347', lw=1.5, alpha=0.9, animated=True, visible=False))
        self._refresh = True

    def _refresh_bg(self):
        for a in self._cursor_artists + self._a_artists + self._b_artists: a.set_visible(False)
        self.fig.canvas.draw()
        self._bg = self.fig.canvas.copy_from_bbox(self.fig.bbox)
        self._refresh = False

    def _on_click(self, e):
        if not self._dual or not self._cursor_visible or e.inaxes is None or e.xdata is None or e.button != 1: return
        if self._placing == 'A':
            self._ax = e.xdata; self._placing = 'B'
        else:
            self._bx = e.xdata; self._placing = 'A'
        self._update_dual()

    def _on_move(self, e):
        if not self._cursor_visible or e.inaxes is None or e.xdata is None: return
        now = _time.monotonic() * 1000
        if now - self._last_t < 33: return
        self._last_t = now
        if self._dual:
            self._update_dual(hover=e.xdata)
        else:
            self._update_single(e.xdata)

    def _update_single(self, x):
        self._ensure_artists()
        if self._refresh or not self._bg: self._refresh_bg()
        self.fig.canvas.restore_region(self._bg)
        for i, vl in enumerate(self._cursor_artists):
            if i < len(self.axes_list): vl.set_xdata([x, x]); vl.set_visible(True); self.axes_list[i].draw_artist(vl)
        info = [f"t={x:.4f}s"]
        for ch, (tf, sf, _, _) in self.channel_data.items():
            if len(tf): idx = min(np.searchsorted(tf, x), len(sf) - 1); info.append(f"{ch[:18]}={sf[idx]:.4g}")
        self.fig.canvas.blit(self.fig.bbox)
        self.cursor_info.emit("  │  ".join(info))

    def _update_dual(self, hover=None):
        self._ensure_dual()
        if self._refresh or not self._bg: self._refresh_bg()
        self.fig.canvas.restore_region(self._bg)
        info, dual = [], []
        if self._ax is not None:
            for i, vl in enumerate(self._a_artists):
                if i < len(self.axes_list): vl.set_xdata([self._ax] * 2); vl.set_visible(True); self.axes_list[
                    i].draw_artist(vl)
            info.append(f"A={self._ax:.4f}s")
        if self._bx is not None:
            for i, vl in enumerate(self._b_artists):
                if i < len(self.axes_list): vl.set_xdata([self._bx] * 2); vl.set_visible(True); self.axes_list[
                    i].draw_artist(vl)
            info.append(f"B={self._bx:.4f}s")
        if self._ax is not None and self._bx is not None:
            dx = self._bx - self._ax;
            info.append(f"ΔT={dx:.4f}s")
            if abs(dx) > 1e-12: info.append(f"1/ΔT={1 / abs(dx):.2f}Hz")
            xlo, xhi = min(self._ax, self._bx), max(self._ax, self._bx)
            for ch, (tf, sf, _, _) in self.channel_data.items():
                if len(tf): m = (tf >= xlo) & (tf <= xhi); seg = sf[m]
                if len(seg): dual.append(f"{ch[:20]}:Min={np.min(seg):.4g} Max={np.max(seg):.4g}  Avg={np.mean(seg):.4g} RMS={np.sqrt(np.mean(seg ** 2)):.4g}")
        if hover is not None:
            self._ensure_artists()
            for i, vl in enumerate(self._cursor_artists):
                if i < len(self.axes_list): vl.set_xdata([hover] * 2); vl.set_visible(True); self.axes_list[
                    i].draw_artist(vl)
        self.fig.canvas.blit(self.fig.bbox)
        self.cursor_info.emit("  │  ".join(info) if info else "Click A")
        self.dual_cursor_info.emit("\n".join(dual) if dual else "")

    def _on_scroll(self, e):
        if e.inaxes is None: return
        ax = e.inaxes;
        step = e.step;
        key = e.key or '';
        f = 0.85 if step > 0 else 1 / 0.85
        if 'control' in key:
            lo, hi = ax.get_xlim(); c = e.xdata or (lo + hi) / 2; ax.set_xlim(c - (c - lo) * f, c + (hi - c) * f)
        elif 'shift' in key:
            lo, hi = ax.get_ylim(); c = e.ydata or (lo + hi) / 2; ax.set_ylim(c - (c - lo) * f, c + (hi - c) * f)
        else:
            lo, hi = ax.get_ylim(); d = (hi - lo) * 0.1 * step; ax.set_ylim(lo + d, hi + d)
        self._refresh = True;
        self.draw_idle()

    def get_statistics(self, time_range=None):
        stats = {}
        for ch, (t, sig, _, unit) in self.channel_data.items():
            s = sig[(t >= time_range[0]) & (t <= time_range[1])] if time_range else sig
            if len(s): stats[ch] = {'min': np.min(s), 'max': np.max(s), 'mean': np.mean(s),
                                    'rms': np.sqrt(np.mean(s ** 2)), 'std': np.std(s), 'p2p': np.ptp(s), 'unit': unit}
        return stats


class AxisEditDialog(QDialog):
    """双击坐标轴弹出的编辑对话框"""
    def __init__(self, parent, ax, axis='x'):
        super().__init__(parent)
        self.ax = ax
        self.axis = axis
        self.setWindowTitle(f"{'X' if axis == 'x' else 'Y'}轴设置")
        self.setMinimumWidth(280)
        layout = QFormLayout(self)

        if axis == 'x':
            lo, hi = ax.get_xlim()
            label = ax.get_xlabel()
        else:
            lo, hi = ax.get_ylim()
            label = ax.get_ylabel()

        self.spin_min = QDoubleSpinBox()
        self.spin_min.setRange(-1e15, 1e15)
        self.spin_min.setDecimals(4)
        self.spin_min.setValue(lo)
        layout.addRow("最小值:", self.spin_min)

        self.spin_max = QDoubleSpinBox()
        self.spin_max.setRange(-1e15, 1e15)
        self.spin_max.setDecimals(4)
        self.spin_max.setValue(hi)
        layout.addRow("最大值:", self.spin_max)

        self.edit_label = QLineEdit(label)
        layout.addRow("标签:", self.edit_label)

        self.chk_auto = QCheckBox("自动范围")
        layout.addRow(self.chk_auto)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addRow(bb)

    def get_values(self):
        return self.spin_min.value(), self.spin_max.value(), self.edit_label.text(), self.chk_auto.isChecked()


class PlotCanvas(FigureCanvas):
    def __init__(self, parent=None):
        self.fig = Figure(figsize=(20, 12), dpi=100);
        super().__init__(self.fig);
        self.setParent(parent)
        self.mpl_connect('scroll_event', self._on_scroll)
        self.mpl_connect('button_press_event', self._on_click)
        self.setFocusPolicy(Qt.StrongFocus)
        self._remarks = []  # [(ax_index, x, y, annotation_artist, dot_artist)]
        self._line_data = {}  # {ax_index: (xdata, ydata)} for snapping
        self._remark_enabled = False
        self._last_scroll_t = 0  # 滚轮节流
        self._scroll_timer = QTimer()
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.timeout.connect(lambda: self.draw_idle())

    def clear(self):
        self._remarks = []
        self._line_data = {}
        self.fig.clear()

    def set_remark_enabled(self, enabled):
        self._remark_enabled = enabled

    def store_line_data(self, ax_index, xdata, ydata):
        """存储曲线数据用于remark吸附"""
        self._line_data[ax_index] = (np.array(xdata), np.array(ydata))

    def _snap_to_curve(self, ax_index, x_click):
        """将点击位置吸附到最近的曲线数据点"""
        if ax_index not in self._line_data:
            return None, None
        xd, yd = self._line_data[ax_index]
        if len(xd) == 0:
            return None, None
        idx = np.argmin(np.abs(xd - x_click))
        return float(xd[idx]), float(yd[idx])

    def _add_remark(self, ax, ax_index, x, y):
        """在指定位置添加remark标注"""
        # 格式化标签
        if abs(x) >= 1000:
            x_str = f"{x:.1f}"
        elif abs(x) >= 1:
            x_str = f"{x:.2f}"
        else:
            x_str = f"{x:.4f}"
        if abs(y) >= 1000:
            y_str = f"{y:.1f}"
        elif abs(y) >= 0.01:
            y_str = f"{y:.4f}"
        else:
            y_str = f"{y:.2e}"

        ann = ax.annotate(
            f"({x_str}, {y_str})",
            xy=(x, y), xytext=(15, 15),
            textcoords='offset points',
            fontsize=8, color='#222',
            bbox=dict(boxstyle='round,pad=0.3', facecolor='#ffffcc', edgecolor='#999', alpha=0.9),
            arrowprops=dict(arrowstyle='->', color='#666', lw=1),
            zorder=100
        )
        # 标记点
        dot, = ax.plot(x, y, 'o', color='red', markersize=5, zorder=101)
        self._remarks.append((ax_index, x, y, ann, dot))
        self.draw_idle()

    def _remove_remark_at(self, ax_index, x_click, y_click):
        """删除最近的remark"""
        if not self._remarks:
            return
        ax = self.fig.axes[ax_index] if ax_index < len(self.fig.axes) else None
        if ax is None:
            return
        # 查找最近的remark (按像素距离)
        best_idx, best_dist = -1, float('inf')
        for i, (ai, rx, ry, ann, dot) in enumerate(self._remarks):
            if ai != ax_index:
                continue
            # 转换为显示坐标计算距离
            try:
                disp = ax.transData.transform((rx, ry))
                click_disp = ax.transData.transform((x_click, y_click))
                dist = np.sqrt((disp[0] - click_disp[0])**2 + (disp[1] - click_disp[1])**2)
                if dist < best_dist:
                    best_dist = dist
                    best_idx = i
            except:
                pass
        if best_idx >= 0 and best_dist < 50:  # 50像素内
            _, _, _, ann, dot = self._remarks.pop(best_idx)
            ann.remove()
            dot.remove()
            self.draw_idle()

    def _find_axis_for_dblclick(self, e):
        """根据双击像素位置判断应编辑哪个axes的哪个轴。
        检测范围包括axes外部的刻度标签区域（更符合用户直觉）。
        返回 (ax, 'x'|'y') 或 (None, None)。
        """
        px, py = e.x, e.y
        MARGIN = 45  # 像素：axes外部可点击的边距（覆盖刻度数字区域）
        best = (None, None)
        best_dist = float('inf')
        for ax in self.fig.axes:
            bbox = ax.get_window_extent()
            # --- X轴区域：axes下方 MARGIN 像素范围内，水平方向在axes范围内 ---
            if bbox.x0 - 10 <= px <= bbox.x1 + 10:
                if bbox.y0 - MARGIN <= py <= bbox.y0 + 20:
                    dist = abs(py - bbox.y0)
                    if dist < best_dist:
                        best = (ax, 'x')
                        best_dist = dist
            # --- Y轴区域：axes左侧 MARGIN 像素范围内，垂直方向在axes范围内 ---
            if bbox.y0 - 10 <= py <= bbox.y1 + 10:
                if bbox.x0 - MARGIN <= px <= bbox.x0 + 20:
                    dist = abs(px - bbox.x0)
                    if dist < best_dist:
                        best = (ax, 'y')
                        best_dist = dist
                # --- 右侧Y轴（colorbar等）：axes右侧 MARGIN 像素范围内 ---
                if bbox.x1 - 20 <= px <= bbox.x1 + MARGIN:
                    dist = abs(px - bbox.x1)
                    if dist < best_dist:
                        best = (ax, 'y')
                        best_dist = dist
        return best

    def _on_click(self, e):
        # 双击编辑坐标轴 — 优先处理，不要求点击在axes内部
        if e.button == 1 and e.dblclick:
            ax, axis = self._find_axis_for_dblclick(e)
            if ax is not None:
                self._edit_axis(ax, axis)
                return

        if e.inaxes is None or e.xdata is None:
            return
        # 找到点击的是哪个axes
        ax_index = -1
        for i, ax in enumerate(self.fig.axes):
            if e.inaxes == ax:
                ax_index = i
                break
        if ax_index < 0:
            return

        if e.button == 3:  # 右键删除remark
            self._remove_remark_at(ax_index, e.xdata, e.ydata)
            return

        if e.button == 1 and not e.dblclick and self._remark_enabled:
            # 左键单击添加remark (吸附到曲线)
            x, y = self._snap_to_curve(ax_index, e.xdata)
            if x is not None:
                self._add_remark(e.inaxes, ax_index, x, y)

    def _edit_axis(self, ax, axis):
        """弹出坐标轴编辑对话框"""
        dlg = AxisEditDialog(self.parent(), ax, axis)
        if dlg.exec_() == QDialog.Accepted:
            vmin, vmax, label, auto = dlg.get_values()
            if axis == 'x':
                if auto:
                    ax.autoscale(axis='x')
                else:
                    ax.set_xlim(vmin, vmax)
                if label:
                    ax.set_xlabel(label)
            else:
                if auto:
                    ax.autoscale(axis='y')
                else:
                    ax.set_ylim(vmin, vmax)
                if label:
                    ax.set_ylabel(label)
            self.draw_idle()

    def set_tick_density(self, x, y):
        for ax in self.fig.axes:
            ax.xaxis.set_major_locator(MaxNLocator(nbins=x, min_n_ticks=3))
            ax.yaxis.set_major_locator(MaxNLocator(nbins=y, min_n_ticks=3))
        self.draw_idle()

    def _on_scroll(self, e):
        if e.inaxes is None: return
        ax = e.inaxes;
        step = e.step;
        key = e.key or '';
        f = 0.85 if step > 0 else 1 / 0.85
        if 'control' in key:
            lo, hi = ax.get_xlim(); c = e.xdata or (lo + hi) / 2; ax.set_xlim(c - (c - lo) * f, c + (hi - c) * f)
        elif 'shift' in key:
            lo, hi = ax.get_ylim(); c = e.ydata or (lo + hi) / 2; ax.set_ylim(c - (c - lo) * f, c + (hi - c) * f)
        else:
            lo, hi = ax.get_ylim(); d = (hi - lo) * 0.1 * step; ax.set_ylim(lo + d, hi + d)
        # 节流：快速滚动时延迟重绘，避免pcolormesh等重量级图形卡顿
        now = _time.monotonic() * 1000
        if now - self._last_scroll_t < 50:
            # 滚动太快，延迟重绘
            self._scroll_timer.start(60)
        else:
            self.draw_idle()
        self._last_scroll_t = now


class StatisticsPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken);
        self.setMaximumHeight(110)
        layout = QVBoxLayout(self);
        layout.setContentsMargins(4, 2, 4, 2)
        self.tree = QTreeWidget();
        self.tree.setHeaderLabels(['Channel', 'Min', 'Max', 'Mean', 'RMS', 'Std', 'P-P'])
        self.tree.setAlternatingRowColors(True);
        self.tree.setRootIsDecorated(False);
        self.tree.setStyleSheet("font-size:15px;")
        h = self.tree.header();
        h.setStretchLastSection(False);
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, 7): h.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        layout.addWidget(self.tree)

    def update_stats(self, stats):
        self.tree.clear()
        for ch, s in stats.items():
            self.tree.addTopLevelItem(QTreeWidgetItem(
                [ch[:26], f"{s['min']:.3g}", f"{s['max']:.3g}", f"{s['mean']:.3g}", f"{s['rms']:.3g}",
                 f"{s['std']:.3g}", f"{s['p2p']:.3g}"]))


class MultiFileChannelWidget(QWidget):
    channels_changed = pyqtSignal()
    MAX_CHANNELS_WARNING = 8  # 超过此数量时警告

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self);
        layout.setContentsMargins(0, 0, 0, 0);
        layout.setSpacing(2)
        self.search = QLineEdit();
        self.search.setPlaceholderText("🔍 Filter...");
        self.search.textChanged.connect(self._filter);
        layout.addWidget(self.search)
        bl = QHBoxLayout()
        for lbl, fn in [("All", self._all), ("None", self._none), ("Inv", self._inv)]:
            b = QPushButton(lbl);
            b.setMaximumWidth(40);
            b.clicked.connect(fn);
            bl.addWidget(b)
        bl.addStretch();
        layout.addLayout(bl)
        self.tree = QTreeWidget();
        self.tree.setHeaderLabels(['Channel', 'Pts']);
        self.tree.setColumnWidth(0, 165)
        self.tree.setAlternatingRowColors(True)
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree)
        self._file_items = {};
        self._colors = {};
        self._files = {};
        self._updating = False

    def add_file(self, fid, fd):
        self._files[fid] = fd
        fi = QTreeWidgetItem([f"📁 {fd.short_name}", f"{len(fd.data)}"])
        # 不使用AutoTristate，手动控制文件级勾选
        fi.setFlags(fi.flags() | Qt.ItemIsUserCheckable)
        fi.setCheckState(0, Qt.Unchecked)
        fi.setData(0, Qt.UserRole, ('file', fid));
        fi.setExpanded(True)
        font = fi.font(0);
        font.setBold(True);
        fi.setFont(0, font)
        palette = fd.get_color_palette()
        for i, ch in enumerate(fd.get_signal_channels()):
            color = palette[i % len(palette)];
            self._colors[(fid, ch)] = color
            ci = QTreeWidgetItem([ch, str(len(fd.data))])
            ci.setFlags(ci.flags() | Qt.ItemIsUserCheckable);
            ci.setCheckState(0, Qt.Unchecked)
            ci.setData(0, Qt.UserRole, ('channel', fid, ch));
            ci.setForeground(0, QBrush(QColor(color)))
            fi.addChild(ci)
        self.tree.addTopLevelItem(fi);
        self._file_items[fid] = fi

    def _on_item_changed(self, item, col):
        if self._updating: return
        data = item.data(0, Qt.UserRole)
        if data and data[0] == 'file':
            # 文件级复选框被点击
            fid = data[1]
            checked = item.checkState(0) == Qt.Checked
            if checked:
                # 统计该文件下有多少通道
                n_channels = item.childCount()
                if n_channels > self.MAX_CHANNELS_WARNING:
                    reply = QMessageBox.question(
                        self.tree, "确认",
                        f"该文件有 {n_channels} 个通道，全部勾选可能导致卡顿。\n确定要全选吗？",
                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                    )
                    if reply != QMessageBox.Yes:
                        self._updating = True
                        item.setCheckState(0, Qt.Unchecked)
                        self._updating = False
                        return
                # 勾选所有子通道
                self._updating = True
                for i in range(item.childCount()):
                    item.child(i).setCheckState(0, Qt.Checked)
                self._updating = False
            else:
                # 取消所有子通道
                self._updating = True
                for i in range(item.childCount()):
                    item.child(i).setCheckState(0, Qt.Unchecked)
                self._updating = False
        self.channels_changed.emit()

    def remove_file(self, fid):
        if fid in self._file_items:
            i = self._file_items.pop(fid);
            idx = self.tree.indexOfTopLevelItem(i)
            if idx >= 0: self.tree.takeTopLevelItem(idx)
        for k in [k for k in self._colors if k[0] == fid]: del self._colors[k]
        if fid in self._files: del self._files[fid]
        self.channels_changed.emit()

    def get_checked_channels(self):
        r = []
        for fid, fi in self._file_items.items():
            for i in range(fi.childCount()):
                ci = fi.child(i)
                if ci.checkState(0) == Qt.Checked:
                    d = ci.data(0, Qt.UserRole)
                    if d and d[0] == 'channel': r.append((d[1], d[2], self._colors.get((d[1], d[2]), '#1f77b4')))
        return r

    def get_file_data(self, fid):
        return self._files.get(fid)

    def check_first_channel(self, fid):
        if fid in self._file_items:
            fi = self._file_items[fid]
            if fi.childCount() > 0: self._updating = True; fi.child(0).setCheckState(0,
                                                                                     Qt.Checked); self._updating = False; self.channels_changed.emit()

    def _filter(self, txt):
        t = txt.lower()
        for fid, fi in self._file_items.items():
            v = 0
            for i in range(fi.childCount()):
                ci = fi.child(i);
                m = t in ci.text(0).lower();
                ci.setHidden(not m);
                v += m
            fi.setHidden(v == 0 and len(t) > 0)

    def _all(self):
        # 统计总共要勾选多少通道
        total = sum(fi.childCount() for fi in self._file_items.values())
        if total > self.MAX_CHANNELS_WARNING:
            reply = QMessageBox.question(
                self.tree, "确认",
                f"共有 {total} 个通道，全部勾选可能导致卡顿。\n确定要全选吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        self._updating = True
        for fi in self._file_items.values():
            for i in range(fi.childCount()):
                if not fi.child(i).isHidden(): fi.child(i).setCheckState(0, Qt.Checked)
        self._updating = False;
        self.channels_changed.emit()

    def _none(self):
        self._updating = True
        for fi in self._file_items.values():
            fi.setCheckState(0, Qt.Unchecked)
            for i in range(fi.childCount()): fi.child(i).setCheckState(0, Qt.Unchecked)
        self._updating = False;
        self.channels_changed.emit()

    def _inv(self):
        self._updating = True
        for fi in self._file_items.values():
            for i in range(fi.childCount()):
                ci = fi.child(i)
                if not ci.isHidden(): ci.setCheckState(0,
                                                       Qt.Unchecked if ci.checkState(0) == Qt.Checked else Qt.Checked)
        self._updating = False;
        self.channels_changed.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MF4/CSV/Excel 数据分析工具 v5.0 - 多文件支持")
        self.setGeometry(100, 100, 1450, 850);
        self.setMinimumSize(900, 600)
        self.files = OrderedDict();
        self._fc = 0;
        self._active = None
        self._init_ui();
        self._connect()

    def _init_ui(self):
        cw = QWidget();
        self.setCentralWidget(cw)
        ml = QHBoxLayout(cw);
        ml.setContentsMargins(5, 5, 5, 5)
        sp = QSplitter(Qt.Horizontal)
        sp.addWidget(self._left());
        sp.addWidget(self._right());
        sp.setSizes([320, 1080])
        ml.addWidget(sp)
        self.statusBar = QStatusBar();
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("Ready - 支持同时打开多个文件进行对比分析")

    def _left(self):
        scroll = QScrollArea();
        scroll.setWidgetResizable(True);
        scroll.setMinimumWidth(290);
        scroll.setMaximumWidth(400)
        p = QWidget();
        lay = QVBoxLayout(p);
        lay.setSpacing(5)

        g = QGroupBox("📂 文件管理");
        gl = QVBoxLayout(g)
        br = QHBoxLayout()
        self.btn_load = QPushButton("➕ 添加");
        self.btn_load.setStyleSheet("font-weight:bold;background:#2196F3;color:white;");
        br.addWidget(self.btn_load)
        self.btn_close = QPushButton("✖ 关闭");
        self.btn_close.setStyleSheet("background:#f44336;color:white;");
        br.addWidget(self.btn_close)
        self.btn_close_all = QPushButton("全部");
        self.btn_close_all.setMaximumWidth(50);
        br.addWidget(self.btn_close_all)
        gl.addLayout(br)
        self.file_tabs = QTabWidget();
        self.file_tabs.setTabsClosable(True);
        self.file_tabs.setMaximumHeight(80);
        gl.addWidget(self.file_tabs)
        self.lbl_info = QLabel("未加载文件");
        self.lbl_info.setStyleSheet("color:#666;font-size:9px;");
        gl.addWidget(self.lbl_info)
        lay.addWidget(g)

        g = QGroupBox("通道选择");
        gl = QVBoxLayout(g)
        self.channel_list = MultiFileChannelWidget()
        self.channel_list.setMinimumHeight(280)  # 确保能显示6-10个通道
        gl.addWidget(self.channel_list)
        ml2 = QHBoxLayout();
        ml2.addWidget(QLabel("模式:"))
        self.combo_mode = QComboBox();
        self.combo_mode.addItems(['Subplot', 'Overlay']);
        ml2.addWidget(self.combo_mode);
        gl.addLayout(ml2)
        self.btn_plot = QPushButton("📈 绘图");
        self.btn_plot.setStyleSheet("font-weight:bold;");
        gl.addWidget(self.btn_plot)
        ch = QHBoxLayout()
        self.chk_cursor = QCheckBox("游标");
        ch.addWidget(self.chk_cursor)
        self.chk_dual = QCheckBox("双游标");
        ch.addWidget(self.chk_dual)
        self.btn_reset = QPushButton("重置");
        self.btn_reset.setMaximumWidth(45);
        ch.addWidget(self.btn_reset);
        ch.addStretch();
        gl.addLayout(ch)
        bh = QHBoxLayout()
        self.btn_edit = QPushButton("🔧 编辑");
        self.btn_edit.setStyleSheet("background:#FF9800;color:white;");
        bh.addWidget(self.btn_edit)
        self.btn_export = QPushButton("📥 导出");
        self.btn_export.setStyleSheet("background:#4CAF50;color:white;");
        bh.addWidget(self.btn_export)
        gl.addLayout(bh);
        lay.addWidget(g)


        # 横坐标设置
        g = QGroupBox("横坐标");
        gl3 = QVBoxLayout(g)
        h1 = QHBoxLayout()
        h1.addWidget(QLabel("来源:"))
        self.combo_xaxis = QComboBox();
        self.combo_xaxis.addItems(['自动(时间)', '指定通道']);
        h1.addWidget(self.combo_xaxis)
        gl3.addLayout(h1)
        h2 = QHBoxLayout()
        h2.addWidget(QLabel("通道:"))
        self.combo_xaxis_ch = QComboBox();
        self.combo_xaxis_ch.setEnabled(False);
        h2.addWidget(self.combo_xaxis_ch)
        gl3.addLayout(h2)
        h3 = QHBoxLayout()
        h3.addWidget(QLabel("标签:"))
        self.edit_xlabel = QLineEdit();
        self.edit_xlabel.setPlaceholderText("Time (s)");
        self.edit_xlabel.setMaximumWidth(100);
        h3.addWidget(self.edit_xlabel)
        gl3.addLayout(h3)
        self.btn_apply_xaxis = QPushButton("应用");
        self.btn_apply_xaxis.setMaximumWidth(60);
        gl3.addWidget(self.btn_apply_xaxis)
        lay.addWidget(g)


        g = QGroupBox("范围");
        gl2 = QVBoxLayout(g)
        self.chk_range = QCheckBox("使用选定范围");
        gl2.addWidget(self.chk_range)
        h1 = QHBoxLayout();
        h1.addWidget(QLabel("开始:"))
        self.spin_start = QDoubleSpinBox();
        self.spin_start.setDecimals(3);
        self.spin_start.setSuffix(" s");
        h1.addWidget(self.spin_start);
        gl2.addLayout(h1)
        h2 = QHBoxLayout();
        h2.addWidget(QLabel("结束:"))
        self.spin_end = QDoubleSpinBox();
        self.spin_end.setDecimals(3);
        self.spin_end.setSuffix(" s");
        h2.addWidget(self.spin_end);
        gl2.addLayout(h2)
        lay.addWidget(g)

        g = QGroupBox("刻度");
        fl = QFormLayout(g)
        self.spin_xt = QSpinBox();
        self.spin_xt.setRange(3, 30);
        self.spin_xt.setValue(10);
        fl.addRow("X:", self.spin_xt)
        self.spin_yt = QSpinBox();
        self.spin_yt.setRange(3, 20);
        self.spin_yt.setValue(6);
        fl.addRow("Y:", self.spin_yt)
        lay.addWidget(g)


        g = QGroupBox("分析信号");
        fl = QFormLayout(g)
        self.combo_sig = QComboBox();
        fl.addRow("信号:", self.combo_sig)
        self.combo_rpm = QComboBox();
        fl.addRow("转速:", self.combo_rpm)
        self.spin_fs = QDoubleSpinBox();
        self.spin_fs.setRange(1, 1e6);
        self.spin_fs.setValue(1000);
        self.spin_fs.setSuffix(" Hz");
        fl.addRow("Fs:", self.spin_fs)
        # 时间轴重建按钮
        self.btn_rebuild_time = QPushButton("🔄 重建时间轴");
        self.btn_rebuild_time.setToolTip("根据Fs重新生成当前文件的时间轴")
        fl.addRow(self.btn_rebuild_time)
        h = QHBoxLayout();
        h.addWidget(QLabel("RPM系数:"))
        self.spin_rf = QDoubleSpinBox();
        self.spin_rf.setRange(0.0001, 10000);
        self.spin_rf.setValue(1);
        self.spin_rf.setDecimals(4);
        h.addWidget(self.spin_rf);
        fl.addRow(h)
        lay.addWidget(g)

        lay.addStretch();
        scroll.setWidget(p);
        return scroll

    def _right(self):
        p = QWidget();
        lay = QVBoxLayout(p);
        lay.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()

        tt = QWidget();
        tl = QVBoxLayout(tt);
        tl.setContentsMargins(2, 2, 2, 2)
        self.canvas_time = TimeDomainCanvas(self);
        self.toolbar_time = NavigationToolbar(self.canvas_time, self)
        self.lbl_cursor = QLabel("");
        self.lbl_cursor.setStyleSheet("background:#1e1e1e;color:#0f0;padding:2px;font-family:monospace;font-size:15px;")
        self.lbl_dual = QLabel("");
        self.lbl_dual.setStyleSheet(
            "background:#0d1117;color:#58a6ff;padding:2px;font-family:monospace;font-size:15px;");
        self.lbl_dual.setWordWrap(True);
        self.lbl_dual.setVisible(False)
        tl.addWidget(self.toolbar_time);
        tl.addWidget(self.lbl_cursor);
        tl.addWidget(self.lbl_dual);
        tl.addWidget(self.canvas_time, stretch=1)
        self.stats = StatisticsPanel();
        tl.addWidget(self.stats)
        self.tabs.addTab(tt, "📈 时域")

        ft = QWidget();
        fl = QVBoxLayout(ft);
        fl.setContentsMargins(2, 2, 2, 2)
        fc = QHBoxLayout()
        fc.addWidget(QLabel("窗函数:"))
        self.combo_win = QComboBox();
        self.combo_win.addItems(['hanning', 'hamming', 'blackman', 'bartlett', 'kaiser', 'flattop']);
        fc.addWidget(self.combo_win)
        fc.addWidget(QLabel("FFT点数:"))
        self.combo_nfft = QComboBox();
        self.combo_nfft.addItems(['自动', '512', '1024', '2048', '4096', '8192', '16384']);
        fc.addWidget(self.combo_nfft)
        fc.addWidget(QLabel("重叠:"))
        self.spin_overlap = QSpinBox();
        self.spin_overlap.setRange(0, 90);
        self.spin_overlap.setValue(50);
        self.spin_overlap.setSuffix("%");
        fc.addWidget(self.spin_overlap)
        self.btn_fft = QPushButton("▶ FFT");
        self.btn_fft.setStyleSheet("font-weight:bold;");
        fc.addWidget(self.btn_fft)
        self.chk_fft_remark = QCheckBox("标注")
        self.chk_fft_remark.setToolTip("左键点击曲线添加标注，右键删除标注")
        fc.addWidget(self.chk_fft_remark)
        self.chk_fft_autoscale = QCheckBox("自适应")
        self.chk_fft_autoscale.setToolTip("自动匹配有效频率范围")
        self.chk_fft_autoscale.setChecked(True)
        fc.addWidget(self.chk_fft_autoscale)
        fc.addStretch();
        fl.addLayout(fc)
        self.canvas_fft = PlotCanvas(self);
        self.toolbar_fft = NavigationToolbar(self.canvas_fft, self)
        fl.addWidget(self.toolbar_fft);
        fl.addWidget(self.canvas_fft, stretch=1)
        self.tabs.addTab(ft, "📊 FFT")

        ot = QWidget();
        ol = QVBoxLayout(ot);
        ol.setContentsMargins(2, 2, 2, 2)
        # 第一行参数
        oc1 = QHBoxLayout()
        oc1.addWidget(QLabel("最大阶次:"))
        self.spin_mo = QSpinBox();
        self.spin_mo.setRange(1, 100);
        self.spin_mo.setValue(20);
        oc1.addWidget(self.spin_mo)
        oc1.addWidget(QLabel("阶次分辨率:"))
        self.spin_order_res = QDoubleSpinBox();
        self.spin_order_res.setRange(0.01, 1.0);
        self.spin_order_res.setValue(0.1);
        self.spin_order_res.setSingleStep(0.05);
        oc1.addWidget(self.spin_order_res)
        oc1.addWidget(QLabel("目标阶次:"))
        self.spin_to = QDoubleSpinBox();
        self.spin_to.setRange(0.5, 100);
        self.spin_to.setValue(1);
        oc1.addWidget(self.spin_to)
        oc1.addStretch();
        ol.addLayout(oc1)
        # 第二行参数
        oc2 = QHBoxLayout()
        oc2.addWidget(QLabel("FFT点数:"))
        self.combo_order_nfft = QComboBox();
        self.combo_order_nfft.addItems(['512', '1024', '2048', '4096', '8192']);
        self.combo_order_nfft.setCurrentText('1024');
        oc2.addWidget(self.combo_order_nfft)
        oc2.addWidget(QLabel("时间分辨率:"))
        self.spin_time_res = QDoubleSpinBox();
        self.spin_time_res.setRange(0.01, 1.0);
        self.spin_time_res.setValue(0.05);
        self.spin_time_res.setSingleStep(0.01);
        self.spin_time_res.setSuffix("s");
        oc2.addWidget(self.spin_time_res)
        oc2.addWidget(QLabel("RPM分辨率:"))
        self.spin_rpm_res = QSpinBox();
        self.spin_rpm_res.setRange(1, 100);
        self.spin_rpm_res.setValue(10);
        self.spin_rpm_res.setSuffix(" rpm");
        oc2.addWidget(self.spin_rpm_res)
        oc2.addStretch();
        ol.addLayout(oc2)
        # 按钮行
        ob = QHBoxLayout()
        self.btn_ot = QPushButton("▶ 时间-阶次");
        self.btn_ot.setStyleSheet("font-weight:bold;");
        ob.addWidget(self.btn_ot)
        self.btn_or = QPushButton("▶ 转速-阶次");
        ob.addWidget(self.btn_or)
        self.btn_ok = QPushButton("▶ 阶次跟踪");
        ob.addWidget(self.btn_ok)
        self.lbl_order_progress = QLabel("");
        self.lbl_order_progress.setStyleSheet("color:#888;");
        ob.addWidget(self.lbl_order_progress)
        ob.addStretch();
        ol.addLayout(ob)
        self.canvas_order = PlotCanvas(self);
        self.toolbar_order = NavigationToolbar(self.canvas_order, self)
        ol.addWidget(self.toolbar_order);
        ol.addWidget(self.canvas_order, stretch=1)
        self.tabs.addTab(ot, "🔄 阶次")

        lay.addWidget(self.tabs);
        return p

    def _connect(self):
        self.btn_load.clicked.connect(self.load_files)
        self.btn_close.clicked.connect(self.close_active)
        self.btn_close_all.clicked.connect(self.close_all)
        self.file_tabs.currentChanged.connect(self._tab_changed)
        self.file_tabs.tabCloseRequested.connect(self._tab_close)
        self.btn_plot.clicked.connect(self.plot_time)
        self.btn_fft.clicked.connect(self.do_fft)
        self.btn_ot.clicked.connect(self.do_order_time)
        self.btn_or.clicked.connect(self.do_order_rpm)
        self.btn_ok.clicked.connect(self.do_order_track)
        self.channel_list.channels_changed.connect(self._ch_changed)
        self.chk_cursor.stateChanged.connect(lambda st: self.canvas_time.set_cursor_visible(st == Qt.Checked))
        self.canvas_time.cursor_info.connect(self.lbl_cursor.setText)
        self.canvas_time.dual_cursor_info.connect(self.lbl_dual.setText)
        self.spin_xt.valueChanged.connect(self._update_all_tick_density)
        self.spin_yt.valueChanged.connect(self._update_all_tick_density)
        self.chk_dual.stateChanged.connect(self._dual_changed)
        self.btn_edit.clicked.connect(self.open_editor)
        self.btn_export.clicked.connect(self.export_excel)
        self.btn_reset.clicked.connect(self._reset_cursors)
        self.btn_rebuild_time.clicked.connect(self.rebuild_time_axis)
        self.chk_fft_remark.stateChanged.connect(
            lambda st: self.canvas_fft.set_remark_enabled(st == Qt.Checked))
        # 横坐标设置
        self.combo_xaxis.currentIndexChanged.connect(self._on_xaxis_mode_changed)
        self.btn_apply_xaxis.clicked.connect(self._apply_xaxis)
        self._custom_xlabel = None  # 自定义X轴标签
        self._custom_xaxis_fid = None  # 自定义X轴来源文件
        self._custom_xaxis_ch = None  # 自定义X轴来源通道

    def _on_xaxis_mode_changed(self, idx):
        """横坐标模式切换"""
        use_channel = (idx == 1)
        self.combo_xaxis_ch.setEnabled(use_channel)
        if use_channel:
            # 填充可用通道
            self.combo_xaxis_ch.clear()
            for fid, fd in self.files.items():
                px = f"[{fd.short_name}] "
                for ch in fd.channels:
                    self.combo_xaxis_ch.addItem(px + ch, (fid, ch))

    def _apply_xaxis(self):
        """应用横坐标设置"""
        mode = self.combo_xaxis.currentIndex()
        if mode == 0:
            # 自动(时间)
            self._custom_xlabel = self.edit_xlabel.text().strip() or None
            self._custom_xaxis_fid = None
            self._custom_xaxis_ch = None
        else:
            # 指定通道
            idx = self.combo_xaxis_ch.currentIndex()
            if idx < 0:
                QMessageBox.warning(self, "提示", "请选择横坐标通道")
                return
            data = self.combo_xaxis_ch.itemData(idx)
            if data:
                self._custom_xaxis_fid, self._custom_xaxis_ch = data
            self._custom_xlabel = self.edit_xlabel.text().strip() or self._custom_xaxis_ch

        # 重新绘图
        self.plot_time()
        self.statusBar.showMessage(f"横坐标已更新: {self._custom_xlabel or 'Time (s)'}")

    def _update_all_tick_density(self):
        """更新所有图表的刻度密度"""
        xt, yt = self.spin_xt.value(), self.spin_yt.value()
        self.canvas_time.set_tick_density(xt, yt)
        # FFT图
        for ax in self.canvas_fft.fig.axes:
            ax.xaxis.set_major_locator(MaxNLocator(nbins=xt, min_n_ticks=3))
            ax.yaxis.set_major_locator(MaxNLocator(nbins=yt, min_n_ticks=3))
        self.canvas_fft.draw_idle()
        # Order图
        for ax in self.canvas_order.fig.axes:
            ax.xaxis.set_major_locator(MaxNLocator(nbins=xt, min_n_ticks=3))
            ax.yaxis.set_major_locator(MaxNLocator(nbins=yt, min_n_ticks=3))
        self.canvas_order.draw_idle()

    def rebuild_time_axis(self):
        """根据当前Fs重建活动文件的时间轴"""
        if not self._active or self._active not in self.files:
            QMessageBox.warning(self, "提示", "请先选择一个文件")
            return

        fd = self.files[self._active]
        fs = self.spin_fs.value()
        old_max = fd.time_array[-1] if len(fd.time_array) > 0 else 0

        fd.rebuild_time_axis(fs)
        new_max = fd.time_array[-1] if len(fd.time_array) > 0 else 0

        # 更新范围控件
        self.spin_start.setRange(0, new_max)
        self.spin_end.setRange(0, new_max)
        self.spin_end.setValue(new_max)

        # 重新绘图
        self.plot_time()

        self.statusBar.showMessage(f"时间轴已重建: {fd.short_name} | Fs={fs}Hz | 时长: {old_max:.1f}s → {new_max:.3f}s")

    def _dual_changed(self, st):
        en = (st == Qt.Checked);
        self.canvas_time.set_dual_cursor_mode(en);
        self.lbl_dual.setVisible(en)
        if en and not self.chk_cursor.isChecked(): self.chk_cursor.setChecked(True)

    def _reset_cursors(self):
        self.canvas_time._ax = self.canvas_time._bx = None;
        self.canvas_time._placing = 'A'
        self.canvas_time._refresh = True;
        self.canvas_time.draw_idle()
        self.lbl_dual.setText("");
        self.lbl_cursor.setText("游标已重置")

    def load_files(self):
        fps, _ = QFileDialog.getOpenFileNames(self, "选择文件", "", "All (*.mf4 *.csv *.xlsx *.xls)")
        for fp in fps: self._load_one(fp)

    def _load_one(self, fp):
        try:
            self.statusBar.showMessage(f"加载: {fp}");
            QApplication.processEvents()
            p = Path(fp);
            ext = p.suffix.lower()
            if ext == '.mf4':
                if not HAS_ASAMMDF: QMessageBox.critical(self, "错误", "asammdf 未安装"); return
                data, chs, units = DataLoader.load_mf4(fp)
            elif ext in ('.xlsx', '.xls'):
                data, chs, units = DataLoader.load_excel(fp)
            else:
                data, chs, units = DataLoader.load_csv(fp)
            fid = f"f{self._fc}";
            self._fc += 1
            fd = FileData(fp, data, chs, units, len(self.files));
            self.files[fid] = fd
            self._add_tab(fid, fd);
            self.channel_list.add_file(fid, fd);
            self._update_combos()
            if fd.time_array is not None and len(fd.time_array):
                self.spin_start.setRange(0, max(self.spin_end.maximum(), fd.time_array[-1]))
                self.spin_end.setRange(0, max(self.spin_end.maximum(), fd.time_array[-1]))
                if len(self.files) == 1: self.spin_end.setValue(fd.time_array[-1])
            self.channel_list.check_first_channel(fid)
            QTimer.singleShot(100, self.plot_time)
            self._update_info()
            self.statusBar.showMessage(f"✅ 已加载: {p.name} ({len(data)} 行) | 共 {len(self.files)} 文件")
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def _add_tab(self, fid, fd):
        tw = QWidget();
        tw.setProperty("file_id", fid)  # 存储file_id到widget属性
        lay = QVBoxLayout(tw);
        lay.setContentsMargins(3, 3, 3, 3)
        lbl = QLabel(f"📄 {fd.filename}\n{len(fd.data)} 行\nFs: {fd.fs:.1f} Hz");
        lbl.setStyleSheet("font-size:9px;color:#555;");
        lay.addWidget(lbl);
        lay.addStretch()
        idx = self.file_tabs.addTab(tw, fd.short_name[:10]);
        self.file_tabs.setTabToolTip(idx, str(fd.filepath))
        self.file_tabs.setCurrentIndex(idx);
        self._active = fid

    def _get_tab_fid(self, idx):
        """获取指定tab的file_id"""
        if idx < 0: return None
        w = self.file_tabs.widget(idx)
        return w.property("file_id") if w else None

    def _tab_changed(self, idx):
        fid = self._get_tab_fid(idx)
        if fid:
            self._active = fid;
            self._update_info()
            if fid in self.files: self.spin_fs.setValue(self.files[fid].fs)

    def _tab_close(self, idx):
        fid = self._get_tab_fid(idx)
        if fid: self._close(fid)

    def close_active(self):
        if self._active: self._close(self._active)

    def _close(self, fid):
        if fid not in self.files: return
        del self.files[fid];
        self.channel_list.remove_file(fid)
        for i in range(self.file_tabs.count()):
            if self._get_tab_fid(i) == fid: self.file_tabs.removeTab(i); break
        self._active = list(self.files.keys())[0] if self.files else None
        self._update_info();
        self._update_combos();
        self.plot_time()
        self.statusBar.showMessage(f"已关闭 | 剩余 {len(self.files)} 文件")

    def close_all(self):
        if not self.files: return
        if QMessageBox.question(self, "确认", f"关闭全部 {len(self.files)} 文件?",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes: return
        for fid in list(self.files.keys()): self._close(fid)
        self.canvas_time.clear();
        self.canvas_time.draw();
        self.stats.update_stats({})

    def _update_info(self):
        if not self.files: self.lbl_info.setText("未加载文件"); return
        self.lbl_info.setText("\n".join(
            [f"{'▶' if fid == self._active else '  '} {fd.short_name}: {len(fd.data)}" for fid, fd in
             self.files.items()]))

    def _update_combos(self):
        self.combo_sig.clear();
        self.combo_rpm.clear();
        self.combo_rpm.addItem("None", None)
        for fid, fd in self.files.items():
            px = f"[{fd.short_name}] "
            for ch in fd.get_signal_channels():
                self.combo_sig.addItem(px + ch, (fid, ch));
                self.combo_rpm.addItem(px + ch, (fid, ch))

    def _ch_changed(self):
        if self.files and self.tabs.currentIndex() == 0: self.plot_time()

    def _on_span(self, xmin, xmax):
        self.spin_start.setValue(xmin);
        self.spin_end.setValue(xmax);
        self.chk_range.setChecked(True)
        st = self.canvas_time.get_statistics(time_range=(xmin, xmax))
        if st: self.stats.update_stats(st)

    def plot_time(self):
        if not self.files: self.canvas_time.clear(); self.canvas_time.draw(); self.stats.update_stats({}); return
        checked = self.channel_list.get_checked_channels()
        if not checked: self.canvas_time.clear(); self.canvas_time.draw(); self.stats.update_stats({}); return

        # 获取自定义横坐标数据
        custom_x = None
        if self._custom_xaxis_fid and self._custom_xaxis_ch:
            if self._custom_xaxis_fid in self.files:
                xfd = self.files[self._custom_xaxis_fid]
                if self._custom_xaxis_ch in xfd.data.columns:
                    custom_x = xfd.data[self._custom_xaxis_ch].values.copy()

        data = [];
        st = {}
        for fid, ch, color in checked:
            fd = self.channel_list.get_file_data(fid)
            if fd is None or ch not in fd.data.columns: continue

            # 使用自定义横坐标或默认时间轴
            if custom_x is not None and len(custom_x) == len(fd.data):
                t = custom_x.copy()
            else:
                t = fd.time_array.copy()

            sig = fd.data[ch].values.copy()
            unit = fd.channel_units.get(ch, '');
            name = fd.get_prefixed_channel(ch)
            if self.chk_range.isChecked(): m = (t >= self.spin_start.value()) & (t <= self.spin_end.value()); t, sig = \
            t[m], sig[m]
            if len(sig) == 0: continue
            data.append((name, True, t, sig, color, unit))
            st[name] = {'min': np.min(sig), 'max': np.max(sig), 'mean': np.mean(sig), 'rms': np.sqrt(np.mean(sig ** 2)),
                        'std': np.std(sig), 'p2p': np.ptp(sig), 'unit': unit}
        if not data: self.canvas_time.clear(); self.canvas_time.draw(); self.stats.update_stats({}); return

        mode = 'subplot' if self.combo_mode.currentIndex() == 0 else 'overlay'
        xlabel = self._custom_xlabel or 'Time (s)'
        self.canvas_time.plot_channels(data, mode, xlabel=xlabel)
        self.canvas_time.set_tick_density(self.spin_xt.value(), self.spin_yt.value())
        self.canvas_time.enable_span_selector(self._on_span);
        self.stats.update_stats(st);
        self.tabs.setCurrentIndex(0)
        self.statusBar.showMessage(f"绘制: {len(checked)} 通道, {len(set(fid for fid, _, _ in checked))} 文件")

    def open_editor(self):
        if not self.files or not self._active or self._active not in self.files: QMessageBox.warning(self, "提示",
                                                                                                     "请先加载文件"); return
        fd = self.files[self._active];
        dlg = ChannelEditorDialog(self, fd)
        if dlg.exec_() == QDialog.Accepted:
            for name, (arr, unit) in dlg.new_channels.items(): fd.data[name] = arr; fd.channels.append(name);
            fd.channel_units[name] = unit
            for name in dlg.removed_channels:
                if name in fd.data.columns: fd.data = fd.data.drop(columns=[name])
                if name in fd.channels: fd.channels.remove(name)
                fd.channel_units.pop(name, None)
            self.channel_list.remove_file(self._active);
            self.channel_list.add_file(self._active, fd);
            self._update_combos()
            self.statusBar.showMessage(f"编辑: +{len(dlg.new_channels)} -{len(dlg.removed_channels)}");
            self.plot_time()

    def export_excel(self):
        if not self.files or not self._active: QMessageBox.warning(self, "提示", "请先加载文件"); return
        fd = self.files[self._active];
        chs = fd.get_signal_channels()
        if not chs: return
        dlg = ExportDialog(self, chs)
        if dlg.exec_() == QDialog.Accepted:
            sel = dlg.get_selected()
            if not sel: return
            fp, _ = QFileDialog.getSaveFileName(self, "保存", "", "Excel (*.xlsx)")
            if not fp: return
            try:
                df = pd.DataFrame()
                if dlg.chk_time.isChecked() and fd.time_array is not None: df['Time'] = fd.time_array
                for ch in sel:
                    if ch in fd.data.columns: df[ch] = fd.data[ch].values
                if dlg.chk_range.isChecked() and fd.time_array is not None:
                    m = (fd.time_array >= self.spin_start.value()) & (fd.time_array <= self.spin_end.value());
                    df = df.loc[m].reset_index(drop=True)
                df.to_excel(fp, index=False, engine='openpyxl')
                QMessageBox.information(self, "成功", f"导出: {len(df)} 行 × {len(df.columns)} 列")
            except Exception as e:
                QMessageBox.critical(self, "错误", str(e))

    def _get_sig(self):
        idx = self.combo_sig.currentIndex()
        if idx < 0: return None, None, None
        d = self.combo_sig.itemData(idx)
        if not d: return None, None, None
        fid, ch = d
        if fid not in self.files: return None, None, None
        fd = self.files[fid]
        if ch not in fd.data.columns: return None, None, None
        return fd.time_array, fd.data[ch].values, fd.fs

    def _get_rpm(self, n):
        idx = self.combo_rpm.currentIndex()
        if idx <= 0: QMessageBox.warning(self, "提示", "请选择转速信号"); return None
        d = self.combo_rpm.itemData(idx)
        if not d: return None
        fid, ch = d
        if fid not in self.files: return None
        fd = self.files[fid]
        if ch not in fd.data.columns: return None
        rpm = fd.data[ch].values.copy() * self.spin_rf.value()
        if self.chk_range.isChecked() and fd.time_array is not None:
            m = (fd.time_array >= self.spin_start.value()) & (fd.time_array <= self.spin_end.value());
            rpm = rpm[m]
        if len(rpm) != n: QMessageBox.warning(self, "提示", f"长度不匹配 ({n} vs {len(rpm)})"); return None
        return rpm

    @staticmethod
    def _fft_auto_xlim(freq, amp):
        """自适应计算FFT频率范围，取整到 1/2/5/10/20/50/100... 序列"""
        if len(freq) < 2 or len(amp) < 2:
            return freq[-1] if len(freq) else 100
        # 找到包含99%能量的频率
        cumulative = np.cumsum(amp ** 2)
        total = cumulative[-1]
        if total < 1e-20:
            return freq[-1]
        # 99%能量截止
        idx_99 = np.searchsorted(cumulative, total * 0.99)
        f_cutoff = freq[min(idx_99, len(freq) - 1)]
        # 给一些余量 (1.2x)
        f_cutoff *= 1.2
        # 取整到好看的数值序列: 1, 2, 5, 10, 20, 50, 100, 200, 500 ...
        nice_vals = []
        for exp in range(-1, 7):
            for m in [1, 2, 5]:
                nice_vals.append(m * 10 ** exp)
        nice_vals.sort()
        for nv in nice_vals:
            if nv >= f_cutoff:
                return nv
        return freq[-1]

    def do_fft(self):
        t, sig, fs = self._get_sig()
        if sig is None or len(sig) < 10: QMessageBox.warning(self, "提示", "请选择有效信号"); return
        if self.chk_range.isChecked() and t is not None:
            m = (t >= self.spin_start.value()) & (t <= self.spin_end.value());
            sig = sig[m]
        fs = self.spin_fs.value();
        win = self.combo_win.currentText()

        # 获取NFFT
        nfft_text = self.combo_nfft.currentText()
        nfft = None if nfft_text == '自动' else int(nfft_text)
        overlap = self.spin_overlap.value() / 100.0

        try:
            self.statusBar.showMessage('计算FFT...');
            QApplication.processEvents()

            if nfft and overlap > 0:
                # 使用平均FFT (Welch方法)
                freq, amp, psd = FFTAnalyzer.compute_averaged_fft(sig, fs, win, nfft, overlap)
            else:
                freq, amp = FFTAnalyzer.compute_fft(sig, fs, win, nfft)
                _, psd = FFTAnalyzer.compute_psd(sig, fs, win, nfft)

            self.canvas_fft.clear()

            # 自适应频率范围计算
            if self.chk_fft_autoscale.isChecked():
                x_max = self._fft_auto_xlim(freq, amp)
            else:
                x_max = fs / 2

            psd_db = 10 * np.log10(psd + 1e-12)

            ax1 = self.canvas_fft.fig.add_subplot(2, 1, 1)
            ax1.plot(freq, amp, '#1f77b4', lw=0.8);
            ax1.set_xlabel('Frequency (Hz)');
            ax1.set_ylabel('Amplitude')
            ax1.set_title(f'FFT - {self.combo_sig.currentText()} (窗:{win}, NFFT:{nfft or "auto"})');
            ax1.grid(True, alpha=0.25, ls='--');
            ax1.set_xlim(0, x_max)
            ax2 = self.canvas_fft.fig.add_subplot(2, 1, 2)
            ax2.plot(freq, psd_db, '#d62728', lw=0.8);
            ax2.set_xlabel('Frequency (Hz)');
            ax2.set_ylabel('PSD (dB)')
            ax2.set_title('功率谱密度');
            ax2.grid(True, alpha=0.25, ls='--');
            ax2.set_xlim(0, x_max)

            # 存储曲线数据用于remark吸附
            self.canvas_fft.store_line_data(0, freq, amp)
            self.canvas_fft.store_line_data(1, freq, psd_db)

            self.canvas_fft.fig.tight_layout()
            self.canvas_fft.set_tick_density(self.spin_xt.value(), self.spin_yt.value())
            self.canvas_fft.draw();
            self.tabs.setCurrentIndex(1)
            pi = np.argmax(amp[1:]) + 1;
            self.statusBar.showMessage(f'FFT峰值: {freq[pi]:.2f} Hz ({amp[pi]:.4f})')
        except Exception as e:
            QMessageBox.critical(self, 'FFT错误', str(e))

    def _order_progress(self, current, total):
        """Order分析进度回调"""
        pct = int(current / total * 100) if total > 0 else 0
        self.lbl_order_progress.setText(f"{pct}%")
        QApplication.processEvents()

    def do_order_time(self):
        t, sig, fs = self._get_sig()
        if sig is None or len(sig) < 100: QMessageBox.warning(self, "提示", "请选择有效信号"); return
        if self.chk_range.isChecked() and t is not None:
            m = (t >= self.spin_start.value()) & (t <= self.spin_end.value());
            t, sig = t[m], sig[m]
        rpm = self._get_rpm(len(sig))
        if rpm is None: return
        fs = self.spin_fs.value()

        # 获取参数
        nfft = int(self.combo_order_nfft.currentText())
        order_res = self.spin_order_res.value()
        time_res = self.spin_time_res.value()
        max_ord = self.spin_mo.value()

        try:
            self.statusBar.showMessage('计算时间-阶次谱...');
            self.lbl_order_progress.setText("0%")
            QApplication.processEvents()

            tb, ords, om = OrderAnalyzer.compute_order_spectrum_time_based(
                sig, rpm, t, fs, max_ord, order_res, time_res, nfft, self._order_progress
            )

            self.canvas_order.clear();
            ax = self.canvas_order.fig.add_subplot(1, 1, 1)
            im = ax.pcolormesh(tb, ords, om.T, shading='gouraud', cmap='jet')
            ax.set_xlabel('Time (s)');
            ax.set_ylabel('Order')
            ax.set_title(f'时间-阶次谱 - {self.combo_sig.currentText()} (分辨率:{order_res})')
            self.canvas_order.fig.colorbar(im, ax=ax, label='RMS')
            self.canvas_order.fig.tight_layout()
            self.canvas_order.set_tick_density(self.spin_xt.value(), self.spin_yt.value())
            self.canvas_order.draw();
            self.tabs.setCurrentIndex(2)
            self.lbl_order_progress.setText("")
            self.statusBar.showMessage(f'完成 | {len(tb)} 时间点 × {len(ords)} 阶次')
        except Exception as e:
            self.lbl_order_progress.setText("")
            QMessageBox.critical(self, '错误', str(e))

    def do_order_rpm(self):
        t, sig, fs = self._get_sig()
        if sig is None or len(sig) < 100: QMessageBox.warning(self, "提示", "请选择有效信号"); return
        if self.chk_range.isChecked() and t is not None:
            m = (t >= self.spin_start.value()) & (t <= self.spin_end.value());
            sig = sig[m]
        rpm = self._get_rpm(len(sig))
        if rpm is None: return
        fs = self.spin_fs.value()

        # 获取参数
        nfft = int(self.combo_order_nfft.currentText())
        order_res = self.spin_order_res.value()
        rpm_res = self.spin_rpm_res.value()
        max_ord = self.spin_mo.value()

        try:
            self.statusBar.showMessage('计算转速-阶次谱...');
            self.lbl_order_progress.setText("0%")
            QApplication.processEvents()

            ords, rb, om = OrderAnalyzer.compute_order_spectrum(
                sig, rpm, fs, max_ord, rpm_res, order_res, nfft, self._order_progress
            )

            self.canvas_order.clear();
            ax = self.canvas_order.fig.add_subplot(1, 1, 1)
            im = ax.pcolormesh(ords, rb, om, shading='gouraud', cmap='jet')
            ax.set_xlabel('Order');
            ax.set_ylabel('RPM')
            ax.set_title(f'转速-阶次谱 - {self.combo_sig.currentText()} (阶次分辨率:{order_res}, RPM分辨率:{rpm_res})')
            self.canvas_order.fig.colorbar(im, ax=ax, label='Amplitude')
            self.canvas_order.fig.tight_layout()
            self.canvas_order.set_tick_density(self.spin_xt.value(), self.spin_yt.value())
            self.canvas_order.draw();
            self.tabs.setCurrentIndex(2)
            self.lbl_order_progress.setText("")
            self.statusBar.showMessage(f'转速-阶次谱完成 | {len(rb)} RPM × {len(ords)} 阶次')
        except Exception as e:
            self.lbl_order_progress.setText("")
            QMessageBox.critical(self, '错误', str(e))

    def do_order_track(self):
        t, sig, fs = self._get_sig()
        if sig is None or len(sig) < 100: QMessageBox.warning(self, "提示", "请选择有效信号"); return
        if self.chk_range.isChecked() and t is not None:
            m = (t >= self.spin_start.value()) & (t <= self.spin_end.value());
            sig = sig[m]
        rpm = self._get_rpm(len(sig))
        if rpm is None: return
        fs = self.spin_fs.value();
        to = self.spin_to.value()
        nfft = int(self.combo_order_nfft.currentText())

        try:
            self.statusBar.showMessage(f'跟踪阶次 {to}...');
            QApplication.processEvents()
            rt, oa = OrderAnalyzer.extract_order_track(sig, rpm, fs, to, nfft)
            self.canvas_order.clear()
            ax1 = self.canvas_order.fig.add_subplot(2, 1, 1)
            ax1.plot(rt, oa, '#1f77b4', lw=1);
            ax1.set_xlabel('RPM');
            ax1.set_ylabel('Amplitude')
            ax1.set_title(f'阶次 {to} 跟踪 - {self.combo_sig.currentText()}');
            ax1.grid(True, alpha=0.25, ls='--')
            ax2 = self.canvas_order.fig.add_subplot(2, 1, 2)
            ax2.plot(rpm, '#2ca02c', lw=0.5);
            ax2.set_xlabel('Sample');
            ax2.set_ylabel('RPM')
            ax2.set_title('转速曲线');
            ax2.grid(True, alpha=0.25, ls='--')
            self.canvas_order.fig.tight_layout()
            self.canvas_order.set_tick_density(self.spin_xt.value(), self.spin_yt.value())
            self.canvas_order.draw();
            self.tabs.setCurrentIndex(2)
            self.statusBar.showMessage(f'阶次 {to} 跟踪完成')
        except Exception as e:
            QMessageBox.critical(self, '错误', str(e))


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()