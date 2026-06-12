from __future__ import annotations

import json
import math
import os
import platform
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil
import sounddevice as sd


from PyQt6.QtCore import (
    QEasingCurve, QMimeData, QObject, QPointF, QPropertyAnimation, QRectF, QSize, Qt,
    QTimer, QUrl, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QDragEnterEvent, QDropEvent, QFont, QFontDatabase, QIcon,
    QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
    QRadialGradient, QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGraphicsOpacityEffect,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QScrollArea,
    QSizePolicy, QTextEdit, QVBoxLayout, QWidget, QProgressBar,
)

from version import __version__

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent

def _config_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR   = _base_dir()
CONFIG_DIR = _config_dir()
API_FILE   = CONFIG_DIR / ".env"

_DEFAULT_W, _DEFAULT_H = 1020, 700
_MIN_W,     _MIN_H     = 860, 580
_LEFT_W  = 240
_RIGHT_W = 420

_OS = platform.system()  # "Windows" | "Darwin"


def _force_taskbar_icon():
    """Set the window icon via Win32 API after the window has a native HWND."""
    try:
        if _OS != "Windows":
            return
        import ctypes
        ico = str(BASE_DIR / "icon.ico")
        if not Path(ico).exists():
            return
        hicon = ctypes.windll.user32.LoadImageW(
            None, ico, 1, 0, 0, 0x00000010
        )
        if not hicon:
            return
        app = QApplication.instance()
        if app is None:
            return
        for w in app.topLevelWidgets():
            hwnd = int(w.winId())
            ctypes.windll.user32.SendMessageW(hwnd, 0x80, 0, hicon)  # ICON_SMALL
            ctypes.windll.user32.SendMessageW(hwnd, 0x80, 1, hicon)  # ICON_BIG
    except Exception:
        pass


class _ArrowCombo(QComboBox):
    """QComboBox with a custom painted purple arrow in the dropdown area."""
    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        cx = r.right() - 26
        cy = r.center().y()
        path = QPainterPath()
        path.moveTo(cx - 10, cy - 5)
        path.lineTo(cx,      cy + 7)
        path.lineTo(cx + 10, cy - 5)
        p.setBrush(QColor("#c084fc"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(path)
        p.end()


class C:
    BG        = "#080010"
    PANEL     = "#0d0218"
    PANEL2    = "#12041e"
    BORDER    = "#1e0a34"
    BORDER_B  = "#3a1060"
    BORDER_A  = "#2e0d50"
    PRI       = "#c084fc"
    PRI_DIM   = "#7a3fa0"
    PRI_GHO   = "#1a0433"
    ACC       = "#ff3399"
    ACC2      = "#ff66cc"
    GREEN     = "#00ff88"
    GREEN_D   = "#00aa55"
    RED       = "#ff3355"
    WARN      = "#ffaa00"
    MUTED_C   = "#ff6699"
    TEXT      = "#d8b4fe"
    TEXT_DIM  = "#7a4a9a"
    TEXT_MED  = "#b07ad0"
    WHITE     = "#f0d8ff"
    DARK      = "#0a0014"
    BAR_BG    = "#150424"


def qcol(h: str, a: int = 255) -> QColor:
    c = QColor(h); c.setAlpha(a); return c

class _SysMetrics:
    def __init__(self):
        self.cpu  = 0.0
        self.mem  = 0.0
        self.net  = 0.0   
        self.gpu  = -1.0  
        self.tmp  = -1.0  
        self._lock = threading.Lock()
        self._last_net = psutil.net_io_counters()
        self._last_net_t = time.time()
        self._running = True
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def _loop(self):
        while self._running:
            try:
                self._update()
            except Exception:
                pass
            time.sleep(1.5)

    def _update(self):
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent

        nc  = psutil.net_io_counters()
        now = time.time()
        dt  = now - self._last_net_t
        if dt > 0:
            sent = (nc.bytes_sent - self._last_net.bytes_sent) / dt
            recv = (nc.bytes_recv - self._last_net.bytes_recv) / dt
            net  = (sent + recv) / (1024 * 1024)
        else:
            net = 0.0
        self._last_net   = nc
        self._last_net_t = now

        gpu = self._get_gpu()

        tmp = self._get_temp()

        with self._lock:
            self.cpu = cpu
            self.mem = mem
            self.net = net
            self.gpu = gpu
            self.tmp = tmp

    def _get_gpu(self) -> float:
        _si = subprocess.STARTUPINFO()
        _si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        _kw = {"startupinfo": _si, "capture_output": True, "text": True,
               "creationflags": subprocess.CREATE_NO_WINDOW}

        # NVIDIA
        try:
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu",
                 "--format=csv,noheader,nounits"],
                timeout=2, **_kw
            )
            if r.returncode == 0:
                vals = [float(v.strip()) for v in r.stdout.strip().split("\n") if v.strip()]
                if vals:
                    return sum(vals) / len(vals)
        except Exception:
            pass

        # Windows  --  WMI for AMD iGPU / any DirectX GPU
        if _OS == "Windows":
            try:
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "Get-CimInstance -Namespace root/cimv2 Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine "
                     "| Where-Object { $_.Name -match '3D|Compute|Copy' } "
                     "| Measure-Object -Property PercentOfTime -Average "
                     "| Select-Object -ExpandProperty Average"],
                    timeout=3, **_kw
                )
                if r.returncode == 0 and r.stdout.strip():
                    val = float(r.stdout.strip())
                    if val >= 0:
                        return val
            except Exception:
                pass

            # Windows fallback  --  Get-Counter GPU performance
            try:
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "$c = (Get-Counter '\\GPU(*)\\% GPU Time' -MaxSamples 1 -ErrorAction SilentlyContinue).CounterSamples.CookedValue; "
                     "if ($c) { ($c | Measure-Object -Average).Average }"],
                    timeout=3, **_kw
                )
                if r.returncode == 0 and r.stdout.strip():
                    val = float(r.stdout.strip())
                    if val >= 0:
                        return val
            except Exception:
                pass

        return -1.0

    def _get_temp(self) -> float:
        try:
            temps = psutil.sensors_temperatures()
            candidates = ["coretemp", "k10temp", "cpu_thermal", "acpitz",
                          "cpu-thermal", "zenpower", "it8688"]
            for name in candidates:
                if name in temps:
                    entries = temps[name]
                    if entries:
                        return entries[0].current
            for entries in temps.values():
                if entries:
                    return entries[0].current
        except Exception:
            pass
        _si = subprocess.STARTUPINFO()
        _si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        _kw = {"startupinfo": _si, "capture_output": True, "text": True,
               "creationflags": subprocess.CREATE_NO_WINDOW}

        if _OS == "Windows":
            try:
                r = subprocess.run(
                    ["powershell", "-Command",
                     "(Get-WmiObject MSAcpi_ThermalZoneTemperature -Namespace root/wmi).CurrentTemperature"],
                    timeout=3, **_kw
                )
                if r.returncode == 0 and r.stdout.strip():
                    raw = float(r.stdout.strip().split("\n")[0])
                    return (raw / 10.0) - 273.15
            except Exception:
                pass
            # WMI fallback  --  AMD iGPU / CPU package sensor
            try:
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "$v = Get-CimInstance -Namespace root/wmi -Class MSAcpi_ThermalZoneTemperature "
                     "| Select-Object -First 1 -ExpandProperty CurrentTemperature; "
                     "if ($v) { ($v / 10.0) - 273.15 }"],
                    timeout=3, **_kw
                )
                if r.returncode == 0 and r.stdout.strip():
                    v = float(r.stdout.strip())
                    if 0 < v < 120:
                        return v
            except Exception:
                pass

            # Windows fallback  --  Get-Counter thermal zone
            try:
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "$c = (Get-Counter '\\Thermal Zone Information(*)\\Temperature' -MaxSamples 1 -ErrorAction SilentlyContinue).CounterSamples.CookedValue; "
                     "if ($c) { ($c | Measure-Object -Average).Average }"],
                    timeout=3, **_kw
                )
                if r.returncode == 0 and r.stdout.strip():
                    v = float(r.stdout.strip())
                    if 0 < v < 120:
                        return v
            except Exception:
                pass

        return -1.0

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cpu": self.cpu,
                "mem": self.mem,
                "net": self.net,
                "gpu": self.gpu,
                "tmp": self.tmp,
            }


_metrics = _SysMetrics()

class HudCanvas(QWidget):
    def __init__(self, face_path: str = "", parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.muted    = False
        self.speaking = False
        self.state    = "INITIALISING"

        self._tick       = 0
        self._scale      = 1.0
        self._tgt_scale  = 1.0
        self._halo       = 55.0
        self._tgt_halo   = 55.0
        self._last_t     = time.time()
        self._scan       = 0.0
        self._scan2      = 180.0
        self._rings      = [0.0, 120.0, 240.0]
        self._pulses: list[float] = [0.0, 50.0, 100.0]
        self._blink      = True
        self._blink_tick = 0
        self._hue_shift  = 270.0  # target hue for glow overlay
        self._hue_now    = 270.0
        self._nova_speed = 0.006
        self._face_px: QPixmap | None = None
        self._load_face(face_path)

        # nova 3D dot sphere
        self._nova_dots: list[list[float]] = []
        self._nova_floaters: list[list[float]] = []
        self._nova_rings: list[list[float]] = []
        self._nova_rot = 0.0
        self._nova_last_beat = 0.0
        self._nova_init()

    def _nova_init(self):
        n_outer = 180
        n_inner = 60
        for _ in range(n_outer):
            theta = random.random() * 2 * math.pi
            phi = math.acos(2 * random.random() - 1)
            r = 100 * (0.7 + random.random() * 0.3)
            self._nova_dots.append([
                math.sin(phi) * math.cos(theta) * r,
                math.sin(phi) * math.sin(theta) * r,
                math.cos(phi) * r,
                6 + random.random() * 8,
                270 + random.random() * 40,
                0.6 + random.random() * 0.4,
                random.random() * 2 * math.pi,
                0.01 + random.random() * 0.02,
            ])
        for _ in range(n_inner):
            theta = random.random() * 2 * math.pi
            phi = math.acos(2 * random.random() - 1)
            r = 40 * (0.7 + random.random() * 0.3)
            self._nova_dots.append([
                math.sin(phi) * math.cos(theta) * r,
                math.sin(phi) * math.sin(theta) * r,
                math.cos(phi) * r,
                5 + random.random() * 6,
                290 + random.random() * 30,
                0.5 + random.random() * 0.3,
                random.random() * 2 * math.pi,
                0.01 + random.random() * 0.02,
            ])
        for _ in range(60):
            self._nova_floaters.append([
                random.random(), random.random(),
                0.5 + random.random() * 1.5,
                random.random() * 100,
                0.3 + random.random() * 0.3,
                1 + random.random() * 2,
            ])

        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._tmr.start(16)

        self._restart_armed = False

    def _load_face(self, path: str):
        try:
            from PIL import Image, ImageDraw
            import io
            img = Image.open(path).convert("RGBA")
            sz  = min(img.size)
            img = img.resize((sz, sz), Image.LANCZOS)
            mk  = Image.new("L", (sz, sz), 0)
            ImageDraw.Draw(mk).ellipse((2, 2, sz - 2, sz - 2), fill=255)
            img.putalpha(mk)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            px = QPixmap(); px.loadFromData(buf.getvalue())
            self._face_px = px
        except Exception:
            self._face_px = None

    def _step(self):
        self._tick += 1
        now = time.time()
        is_active = self.state in ("THINKING", "PROCESSING", "EXECUTING") or self.speaking
        if now - self._last_t > (0.12 if is_active else 0.5):
            if self.speaking:
                self._tgt_scale = random.uniform(1.06, 1.14)
                self._tgt_halo  = random.uniform(145, 190)
                self._hue_shift = 270.0
            elif self.state == "THINKING":
                self._tgt_scale = random.uniform(1.01, 1.04)
                self._tgt_halo  = random.uniform(80, 110)
                self._hue_shift = 210.0 + math.sin(now * 0.5) * 15  # blue tint
            elif self.state in ("PROCESSING", "EXECUTING"):
                self._tgt_scale = random.uniform(1.02, 1.08)
                self._tgt_halo  = random.uniform(100, 140)
                self._hue_shift = 280.0 + math.sin(now * 0.8) * 20  # purple wobble
            elif self.state == "LISTENING":
                self._tgt_scale = random.uniform(1.005, 1.015)
                self._tgt_halo  = random.uniform(55, 78)
                self._hue_shift = 270.0
            elif self.state == "DONE":
                self._tgt_scale = random.uniform(0.998, 1.002)
                self._tgt_halo  = random.uniform(35, 50)
                self._hue_shift = 140.0  # green glow
            elif self.state == "IDLE":
                self._tgt_scale = random.uniform(0.998, 1.004)
                self._tgt_halo  = random.uniform(30, 48)
                self._hue_shift = 270.0
            elif self.muted:
                self._tgt_scale = random.uniform(0.998, 1.002)
                self._tgt_halo  = random.uniform(15, 28)
                self._hue_shift = 320.0
            else:
                self._tgt_scale = random.uniform(1.001, 1.008)
                self._tgt_halo  = random.uniform(48, 68)
                self._hue_shift = 270.0
            self._last_t = now

        self._hue_now += (self._hue_shift - self._hue_now) * 0.08

        sp = 0.38 if is_active else 0.15
        self._scale += (self._tgt_scale - self._scale) * sp
        self._halo  += (self._tgt_halo  - self._halo)  * sp

        speeds = [2.0, -1.4, 2.8] if self.speaking else ([2.4, -1.6, 3.0] if self.state in ("PROCESSING", "EXECUTING") else [0.55, -0.35, 0.9])
        for i, spd in enumerate(speeds):
            self._rings[i] = (self._rings[i] + spd) % 360

        scan_spd = 4.5 if self.speaking else (3.5 if self.state in ("PROCESSING", "EXECUTING") else (2.0 if self.state == "THINKING" else 1.3))
        self._scan  = (self._scan  + scan_spd) % 360
        self._scan2 = (self._scan2 + -scan_spd * 0.6) % 360

        fw  = min(self.width(), self.height())
        lim = fw * 0.74
        spd = 4.2 if is_active else 2.0
        self._pulses = [r + spd for r in self._pulses if r + spd < lim]
        spawn_chance = 0.07 if is_active else 0.025
        if len(self._pulses) < 3 and random.random() < spawn_chance:
            self._pulses.append(0.0)

        self._blink_tick += 1
        blink_thresh = 25 if is_active else 38
        if self._blink_tick >= blink_thresh:
            self._blink = not self._blink
            self._blink_tick = 0

        # nova sphere update
        self._nova_speed = 0.022 if self.state in ("PROCESSING", "EXECUTING") else (0.015 if self.speaking else (0.010 if self.state == "THINKING" else (0.008 if self.state == "LISTENING" else 0.004)))
        self._nova_rot += self._nova_speed
        t = time.time()
        jitter = 0.30 if self.state in ("PROCESSING", "EXECUTING") else (0.20 if self.speaking else 0.15)
        for d in self._nova_dots:
            d[6] += d[7]
            d[0] += math.sin(t + d[6]) * jitter
            d[1] += math.cos(t + d[6] * 0.7) * jitter
            d[2] += math.sin(t + d[6] * 1.3) * jitter

        for f in self._nova_floaters:
            f[1] -= f[2] * 0.002
            f[0] += math.sin(t * 0.001 + f[3]) * 0.001
            if f[1] < -0.05:
                f[1] = 1.05
                f[0] = random.random()

        beat_int = 1900 if self.speaking else (1200 if self.state in ("PROCESSING", "EXECUTING") else (2400 if self.state == "LISTENING" else 3600))
        now_ms = time.time() * 1000
        bp = (now_ms % beat_int) / beat_int
        if bp < self._nova_last_beat:
            hue_offset = 210 if self.state == "THINKING" else (280 if self.state in ("PROCESSING", "EXECUTING") else 270)
            self._nova_rings.append([now_ms, hue_offset + random.random() * 50])
        self._nova_last_beat = bp
        self._nova_rings = [r for r in self._nova_rings if time.time() * 1000 - r[0] < beat_int * 4]

        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), qcol(C.BG))

        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2
        fw = min(W, H)

        # grid dots  --  subtle
        p.setPen(QPen(qcol(C.BORDER), 1))
        for x in range(0, W, 48):
            for y in range(0, H, 48):
                p.drawPoint(x, y)

        # face
        if self._face_px:
            fsz    = int(fw * 0.62 * self._scale)
            scaled = self._face_px.scaled(
                fsz, fsz,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            p.drawPixmap(int(cx - fsz / 2), int(cy - fsz / 2), scaled)

            # state-based glow overlay
            glow_r = fsz * 0.75
            glow_bg = QColor()
            glow_bg.setHsv(int(self._hue_now), 200, 180, 30)
            glow_fg = QColor()
            glow_fg.setHsv(int(self._hue_now), 220, 220, 8)
            gg = QRadialGradient(QPointF(cx, cy), glow_r, QPointF(cx, cy))
            gg.setColorAt(0, glow_fg)
            gg.setColorAt(0.5, glow_bg)
            gg.setColorAt(1, QColor(0, 0, 0, 0))
            p.setBrush(QBrush(gg))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx, cy), glow_r, glow_r)
        else:
            # Nova 3D dot sphere
            sf = fw * 0.0025
            beat_int = 1900 if self.speaking else (1200 if self.state in ("PROCESSING", "EXECUTING") else (2400 if self.state == "LISTENING" else 3600))
            now_ms = time.time() * 1000
            bp = (now_ms % beat_int) / beat_int
            t_b = bp * 1.5
            if self.speaking:
                pulse = math.sin(t_b * math.pi) * math.exp(-t_b * 2) * 1.8 if t_b < 1 else 0
            else:
                pulse = math.sin(t_b * math.pi) * math.exp(-t_b * 5) * 2.5 if t_b < 1 else 0

            cos_y = math.cos(self._nova_rot)
            sin_y = math.sin(self._nova_rot)
            sorted_dots = []
            for d in self._nova_dots:
                rx = d[0] * cos_y - d[2] * sin_y
                ry = d[1]
                rz = d[0] * sin_y + d[2] * cos_y
                sorted_dots.append((rx, ry, rz, d[3], d[4], d[5], d[6]))
            sorted_dots.sort(key=lambda x: -x[2])

            for f in self._nova_floaters:
                fx = f[0] * W
                fy = f[1] * H
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(QColor(180, 160, 220, int(f[4] * 255))))
                p.drawEllipse(QPointF(fx, fy), f[5], f[5])

            for rx, ry, rz, dr, hue, alpha, pv in sorted_dots:
                depth = (rz + 180) / 360
                sc = 0.8 + depth * 0.4
                px = cx + rx * sf * sc
                py = cy + ry * sf * sc
                rd = dr * sc * (1 + math.sin(pv) * 0.12) * (1 + pulse)
                a = int(alpha * (0.5 + depth * 0.5) * 255)
                c_hi = QColor()
                c_hi.setHsv(int(hue), 200, 245, a)
                c_base = QColor()
                c_base.setHsv(int(hue), 190, 190, a)
                c_shadow = QColor()
                c_shadow.setHsv(int(hue), 160, 90, a)
                grad = QRadialGradient(QPointF(px, py), rd * 1.3, QPointF(px, py))
                grad.setColorAt(0, c_hi)
                grad.setColorAt(0.4, c_base)
                grad.setColorAt(0.7, c_shadow)
                grad.setColorAt(1, QColor(0, 0, 0, 0))
                p.setBrush(QBrush(grad))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QPointF(px, py), rd * 1.3, rd * 1.3)

            for r in self._nova_rings:
                el = time.time() * 1000 - r[0]
                prog = el / (beat_int * 4)
                if prog < 1:
                    rr = prog * fw * 1.0
                    ra = int(255 * (1 - prog * prog))
                    rc = QColor()
                    rc.setHsv(int(r[1]), 220, 240, ra)
                    p.setPen(QPen(rc, 3))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawEllipse(QRectF(cx - rr, cy - rr, rr * 2, rr * 2))

        # status text
        sy = cy + fw * 0.40
        if self.muted:
            txt, col = "MUTED",       qcol(C.MUTED_C)
        elif self.speaking:
            txt, col = "SPEAKING",    qcol(C.ACC)
        elif self.state == "THINKING":
            txt, col = "THINKING",   qcol(C.ACC2)
        elif self.state in ("PROCESSING", "EXECUTING"):
            txt, col = "EXECUTING", qcol(C.ACC2)
        elif self.state == "LISTENING":
            txt, col = "LISTENING", qcol(C.GREEN)
        elif self.state == "DONE":
            txt, col = "DONE",       qcol(C.GREEN)
        elif self.state == "IDLE":
            txt, col = "IDLE",      qcol(C.PRI_DIM)
        elif self.state == "INITIALISING":
            txt, col = "INITIALIZING", qcol(C.PRI_DIM)
        elif self.state == "RESTARTING":
            txt, col = "RESTARTING...", qcol(C.ACC)
        else:
            txt, col = None, None
            if not self._restart_armed:
                self._restart_armed = True
                QTimer.singleShot(0, lambda: self.window().restart_app() if self.window() else None)

        if txt:
            if self.state == "RESTARTING":
                alpha = 128 + int(127 * math.sin(self._tick * 0.15))
                col.setAlpha(alpha)
                p.setPen(QPen(col, 2))
                p.setFont(QFont("Courier New", 16, QFont.Weight.Bold))
                p.drawText(QRectF(0, sy - 8, W, 40), Qt.AlignmentFlag.AlignCenter, txt)
            else:
                p.setPen(QPen(col, 1))
                p.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
                p.drawText(QRectF(0, sy, W, 26), Qt.AlignmentFlag.AlignCenter, txt)

        # waveform
        wy = sy + 30
        N, bw = 36, 8
        wx0 = (W - N * bw) / 2
        for i in range(N):
            if self.muted:
                hgt, cl = 2, qcol(C.MUTED_C)
            elif self.speaking:
                hgt = random.randint(3, 20)
                cl  = qcol(C.PRI) if hgt > 12 else qcol(C.PRI_DIM)
            elif self.state == "LISTENING":
                hgt = int(6 + 14 * abs(math.sin(self._tick * 0.1 + i * 0.5)))
                cl  = qcol(C.PRI) if hgt > 14 else qcol(C.PRI_DIM)
            elif self.state == "DONE":
                hgt = int(3 + 2 * math.sin(self._tick * 0.05 + i * 0.3))
                cl  = qcol(C.GREEN_D)
            elif self.state == "IDLE":
                hgt = int(2 + 2 * math.sin(self._tick * 0.06 + i * 0.4))
                cl  = qcol(C.BORDER)
            elif self.state in ("INITIALISING", "RESTARTING"):
                hgt = int(3 + 3 * math.sin(self._tick * 0.09 + i * 0.6))
                cl  = qcol(C.BORDER_B)
            else:
                hgt = int(3 + 2 * math.sin(self._tick * 0.09 + i * 0.6))
                cl  = qcol(C.BORDER_B)
            p.fillRect(QRectF(wx0 + i * bw, wy + 20 - hgt, bw - 1, hgt), cl)

class MetricBar(QWidget):

    def __init__(self, label: str, color: str = C.PRI, parent=None):
        super().__init__(parent)
        self._label = label
        self._color = color
        self._value = 0.0       # 0 - 100
        self._text  = "--"
        self.setFixedHeight(36)
        self.setMinimumWidth(80)

    def set_value(self, pct: float, text: str):
        self._value = max(0.0, min(100.0, pct))
        self._text  = text
        self.update()

    def set_label(self, label: str):
        self._label = label
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        p.setBrush(QBrush(qcol(C.PANEL2)))
        p.setPen(QPen(qcol(C.BORDER), 1))
        p.drawRoundedRect(QRectF(1, 1, W - 2, H - 2), 5, 5)

        bar_h   = 3
        bar_y   = H - bar_h - 5
        bar_w   = W - 12
        bar_x   = 6
        fill_w  = int(bar_w * self._value / 100)

        p.setBrush(QBrush(qcol(C.BAR_BG)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 2, 2)

        if self._value > 85:
            bar_col = qcol(C.RED)
        elif self._value >= 70:
            bar_col = qcol(C.WARN)
        else:
            bar_col = qcol(C.GREEN)

        if fill_w > 0:
            p.setBrush(QBrush(bar_col))
            p.drawRoundedRect(QRectF(bar_x, bar_y, fill_w, bar_h), 2, 2)

        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.WHITE), 1))
        p.drawText(QRectF(8, 4, W - 90, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._label)

        p.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        p.setPen(QPen(bar_col if self._text != "--" else qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(0, 3, W - 6, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._text)

class LogWidget(QTextEdit):
    _sig = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Courier New", 18, QFont.Weight.Bold))
        self.document().setDefaultStyleSheet("p, div, li { line-height: 150%; }")
        self.setStyleSheet(f"""
            QTextEdit {{
                background: {C.PANEL};
                color: {C.WHITE};
                border: 1px solid {C.BORDER};
                border-radius: 5px;
                padding: 8px;
                selection-background-color: {C.PRI_GHO};
                font-size: 18px;
                line-height: 150%;
            }}
            QScrollBar:vertical {{
                background: {C.BG};
                width: 8px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_B};
                border-radius: 4px;
                min-height: 20px;
            }}
        """)
        self._queue: list[str] = []
        self._typing  = False
        self._text    = ""
        self._pos     = 0
        self._tag     = "sys"
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._nova_buf = ""
        self._nova_pos = 0
        self._nova_active = False
        self._nova_has_prefix = False
        self._sig.connect(self._enqueue)

    def append_log(self, text: str):
        self._sig.emit(text)

    def _enqueue(self, text: str):
        self._queue.append(text)
        if not self._typing:
            self._next()

    def _next(self):
        if not self._queue:
            self._typing = False
            return
        if self._text:
            return
        self._typing = True
        self._text   = self._queue.pop(0)
        self._pos    = 0
        tl = self._text.lower()
        if   tl.startswith("you:"):    self._tag = "you"
        elif tl.startswith("nova:"): self._tag = "ai"
        elif tl.startswith("file:"):   self._tag = "file"
        elif "err" in tl:              self._tag = "err"
        else:                          self._tag = "sys"
        self._tmr.start(6)

    def _step(self):
        if self._nova_active and self._nova_pos < len(self._nova_buf):
            ch = self._nova_buf[self._nova_pos]
            cur = self.textCursor()
            cur.movePosition(cur.MoveOperation.End)
            fmt = cur.charFormat()
            fmt.setForeground(QBrush(qcol(C.PRI)))
            cur.insertText(ch, fmt)
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            self._nova_pos += 1
            return
        if self._nova_active and self._nova_pos >= len(self._nova_buf):
            self._nova_active = False
            if not self.toPlainText().endswith(("\n", "\u2029")):
                cur = self.textCursor()
                cur.movePosition(cur.MoveOperation.End)
                cur.insertText("\n")
                self.setTextCursor(cur)
                self.ensureCursorVisible()
            if not self._nova_buf or not self._nova_has_prefix:
                self._typing = False
                QTimer.singleShot(20, self._next)
        if self._pos < len(self._text):
            ch  = self._text[self._pos]
            cur = self.textCursor()
            fmt = cur.charFormat()
            col = {
                "you":  qcol(C.WHITE),
                "ai":   qcol(C.PRI),
                "err":  qcol(C.RED),
                "file": qcol(C.GREEN),
                "sys":  qcol(C.TEXT_MED),
            }.get(self._tag, qcol(C.WHITE))
            fmt.setForeground(QBrush(col))
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText(ch, fmt)
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            self._pos += 1
            return
        if self._pos >= len(self._text) and self._text:
            cur = self.textCursor()
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText("\n")
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            self._text = ""
            self._pos = 0
            QTimer.singleShot(20, self._next)
            return
        if not self._nova_active and not self._text:
            self._tmr.stop()

    def _update_last_nova(self, text: str):
        old_len = len(self._nova_buf)
        self._nova_buf = text
        if self._nova_active:
            # Chunk arrived while typing in progress — flush remaining old chars synchronously
            while self._nova_pos < old_len:
                ch = self._nova_buf[self._nova_pos]
                cur = self.textCursor()
                cur.movePosition(cur.MoveOperation.End)
                fmt = cur.charFormat()
                fmt.setForeground(QBrush(qcol(C.PRI)))
                cur.insertText(ch, fmt)
                self._nova_pos += 1
            return
        if self._nova_pos > 0 and old_len > 0:
            # Continuation after buffer exhaustion — undo trailing \n
            if self.toPlainText().endswith("\n"):
                cur = self.textCursor()
                cur.movePosition(cur.MoveOperation.End)
                cur.movePosition(cur.MoveOperation.Left, cur.MoveMode.KeepAnchor)
                cur.removeSelectedText()
                self.setTextCursor(cur)
                self.ensureCursorVisible()
        else:
            # New turn — flush interrupted queue entry
            if self._text:
                rest = self._text[self._pos:]
                if not rest and self.toPlainText().endswith("\n"):
                    self._text = ""
                    self._pos = 0
                else:
                    cur = self.textCursor()
                    cur.movePosition(cur.MoveOperation.End)
                    fmt = cur.charFormat()
                    col = {
                        "you": qcol(C.WHITE), "ai": qcol(C.PRI),
                        "err": qcol(C.RED), "file": qcol(C.GREEN),
                        "sys": qcol(C.TEXT_MED),
                    }.get(self._tag, qcol(C.WHITE))
                    fmt.setForeground(QBrush(col))
                    t = rest if rest else ""
                    cur.insertText(t + "\n" if t else "\n", fmt)
                    self._text = ""
                    self._pos = 0
        self._nova_active = True
        if not self._nova_has_prefix:
            self._nova_has_prefix = True
            cur = self.textCursor()
            cur.movePosition(cur.MoveOperation.End)
            fmt = cur.charFormat()
            fmt.setForeground(QBrush(qcol(C.PRI)))
            cur.insertText("Nova: ", fmt)
            self.setTextCursor(cur)
            self.ensureCursorVisible()
        if self._nova_pos < old_len:
            self._nova_pos = old_len
        if not self._tmr.isActive():
            self._tmr.start(6)

    def _finish_nova(self):
        self._nova_has_prefix = False
        if not self._nova_active:
            self._nova_buf = ""
            self._nova_pos = 0
            self._typing = False
            self._next()

_FILE_ICONS = {
    "image":   ("", "#00d4ff"), "video":   ("", "#ff6b00"),
    "audio":   ("", "#cc44ff"), "pdf":     ("", "#ff4444"),
    "word":    ("[memo]", "#4488ff"), "excel":   ("", "#44bb44"),
    "code":    ("", "#ffcc00"), "archive": ("", "#ff8844"),
    "pptx":    ("", "#ff6622"), "text":    ("", "#aaaaaa"),
    "data":    ("", "#88ddff"), "unknown": ("", "#888888"),
}
_EXT_TO_CAT = {
    **dict.fromkeys(["jpg","jpeg","png","gif","webp","bmp","tiff","svg","ico"], "image"),
    **dict.fromkeys(["mp4","avi","mov","mkv","wmv","flv","webm","m4v"],         "video"),
    **dict.fromkeys(["mp3","wav","ogg","m4a","aac","flac","wma","opus"],        "audio"),
    **dict.fromkeys(["pdf"],                                                     "pdf"),
    **dict.fromkeys(["doc","docx"],                                              "word"),
    **dict.fromkeys(["xls","xlsx","ods"],                                        "excel"),
    **dict.fromkeys(["ppt","pptx"],                                              "pptx"),
    **dict.fromkeys(["py","js","ts","jsx","tsx","html","css","java","c","cpp",
                     "cs","go","rs","rb","php","swift","kt","sh","sql","lua"],   "code"),
    **dict.fromkeys(["zip","rar","tar","gz","7z","bz2","xz"],                   "archive"),
    **dict.fromkeys(["txt","md","rst","log"],                                    "text"),
    **dict.fromkeys(["csv","tsv","json","xml"],                                  "data"),
}

def _file_category(path: Path) -> str:
    return _EXT_TO_CAT.get(path.suffix.lower().lstrip("."), "unknown")

def _fmt_size(size: int) -> str:
    if   size < 1024:    return f"{size} B"
    elif size < 1024**2: return f"{size/1024:.1f} KB"
    elif size < 1024**3: return f"{size/1024**2:.1f} MB"
    else:                return f"{size/1024**3:.1f} GB"


class FileDropZone(QWidget):
    file_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(100)
        self._current_file: str | None = None
        self._hovering  = False
        self._drag_over = False
        self._dash_offset = 0.0
        self._anim_tmr = QTimer(self)
        self._anim_tmr.timeout.connect(self._animate)
        self._anim_tmr.start(40)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._canvas = _DropCanvas(self)
        layout.addWidget(self._canvas)

    def _animate(self):
        self._dash_offset = (self._dash_offset + 0.8) % 20
        self._canvas.update()

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._drag_over = True; self._canvas.update()

    def dragLeaveEvent(self, e):
        self._drag_over = False; self._canvas.update()

    def dropEvent(self, e: QDropEvent):
        self._drag_over = False
        urls = e.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if Path(path).is_file():
                self._set_file(path)
        self._canvas.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._browse()

    def enterEvent(self, e):
        self._hovering = True; self._canvas.update()

    def leaveEvent(self, e):
        self._hovering = False; self._canvas.update()

    def current_file(self) -> str | None:
        return self._current_file

    def clear_file(self):
        self._current_file = None; self._canvas.update()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a file for Nova", str(Path.home()),
            "All Files (*.*);;"
            "Images (*.jpg *.jpeg *.png *.gif *.webp *.bmp *.svg);;"
            "Documents (*.pdf *.docx *.txt *.md *.pptx);;"
            "Data (*.csv *.xlsx *.json *.xml);;"
            "Code (*.py *.js *.ts *.html *.css *.java *.cpp *.go);;"
            "Audio (*.mp3 *.wav *.ogg *.m4a *.aac *.flac);;"
            "Video (*.mp4 *.avi *.mov *.mkv *.wmv *.webm);;"
            "Archives (*.zip *.rar *.tar *.gz *.7z)",
        )
        if path:
            self._set_file(path)

    def _set_file(self, path: str):
        self._current_file = path
        self._canvas.update()
        self.file_selected.emit(path)


class _DropCanvas(QWidget):
    def __init__(self, zone: FileDropZone):
        super().__init__(zone)
        self._z = zone

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        z    = self._z
        W, H = self.width(), self.height()
        pad  = 6
        rect = QRectF(pad, pad, W - pad * 2, H - pad * 2)

        bg_col = qcol("#001a24" if z._drag_over else ("#001218" if z._hovering else C.PANEL))
        p.setBrush(QBrush(bg_col)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 6, 6)

        if z._current_file:   border_col = qcol(C.GREEN, 200)
        elif z._drag_over:    border_col = qcol(C.PRI, 200)
        elif z._hovering:     border_col = qcol(C.BORDER_B, 180)
        else:                 border_col = qcol(C.BORDER, 140)

        pen = QPen(border_col, 1.5, Qt.PenStyle.DashLine)
        pen.setDashOffset(z._dash_offset)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 6, 6)

        if z._current_file:   self._paint_file(p, W, H)
        elif z._drag_over:    self._paint_drag_over(p, W, H)
        else:                 self._paint_idle(p, W, H, z._hovering)

    def _paint_idle(self, p, W, H, hover):
        cx, cy = W / 2, H / 2
        col = qcol(C.PRI_DIM if not hover else C.PRI)
        p.setPen(QPen(col, 2)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(cx, cy - 14), QPointF(cx, cy + 4))
        p.drawLine(QPointF(cx - 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx + 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx - 14, cy + 4), QPointF(cx + 14, cy + 4))
        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.PRI_DIM if not hover else C.TEXT), 1))
        p.drawText(QRectF(0, cy + 8, W, 16), Qt.AlignmentFlag.AlignCenter,
                   "Drop file here  or  Click to Browse")
        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.ACC2), 1))
        p.drawText(QRectF(0, cy + 24, W, 14), Qt.AlignmentFlag.AlignCenter,
                   "Images | Video | Audio | PDF | Docs | Code | Data")

    def _paint_drag_over(self, p, W, H):
        cx, cy = W / 2, H / 2
        p.setFont(QFont("Courier New", 20))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy - 24, W, 32), Qt.AlignmentFlag.AlignCenter, "down")
        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy + 12, W, 16), Qt.AlignmentFlag.AlignCenter, "Release to load")

    def _paint_file(self, p, W, H):
        path = Path(self._z._current_file)
        cat  = _file_category(path)
        icon, icon_col = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size_str = _fmt_size(path.stat().st_size)
        ext_str  = path.suffix.upper().lstrip(".") or "FILE"

        block_x, block_w = 10, 60
        p.setFont(QFont("Segoe UI Emoji", 22) if _OS == "Windows" else QFont("Arial", 22))
        p.setPen(QPen(qcol(icon_col), 1))
        p.drawText(QRectF(block_x, 0, block_w, H), Qt.AlignmentFlag.AlignCenter, icon)

        tx = block_x + block_w + 6
        tw = W - tx - 38

        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.WHITE), 1))
        name = path.name if len(path.name) <= 34 else path.name[:31] + "..."
        p.drawText(QRectF(tx, H * 0.18, tw, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)

        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(tx, H * 0.18 + 18, tw, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{ext_str}   |   {size_str}")

        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        par = str(path.parent)
        if len(par) > 42: par = "..." + par[-41:]
        p.drawText(QRectF(tx, H * 0.18 + 34, tw, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, par)

        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.RED, 180), 1))
        p.drawText(QRectF(W - 34, 0, 28, H), Qt.AlignmentFlag.AlignCenter, "[X]")

    def mousePressEvent(self, e):
        z = self._z
        if z._current_file and e.pos().x() > self.width() - 34:
            z.clear_file()
        else:
            z.mousePressEvent(e)


class SetupOverlay(QWidget):
    done = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            SetupOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 8px;
            }}
        """)

        detected = {"darwin": "mac", "windows": "windows"}.get(
            _OS.lower(), "windows"
        )
        self._sel_os = detected

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 22, 30, 22)
        layout.setSpacing(8)

        def _lbl(txt, font_size=9, bold=True, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont("Courier New", font_size,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        layout.addWidget(_lbl("  Welcome to Nova", 24, True, C.WHITE))
        layout.addWidget(_lbl("One-time setup to get you started.", 18, color=C.PRI_DIM))
        layout.addSpacing(8)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep)
        layout.addSpacing(4)

        layout.addWidget(_lbl("LLM PROVIDER", 16, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        self._provider_cb = _ArrowCombo()
        self._provider_cb.addItems(["Gemini", "OpenAI", "Ollama"])
        self._provider_cb.setFont(QFont("Courier New", 17, QFont.Weight.Bold))
        self._provider_cb.setFixedHeight(46)
        self._provider_cb.setStyleSheet(f"""
            QComboBox {{
                background: #000d12; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 4px; padding: 2px 8px;
            }}
            QComboBox::drop-down {{
                border: none; width: 28px;
                subcontrol-origin: padding;
                subcontrol-position: top right;
            }}
            QComboBox::down-arrow {{
                image: none; width: 10px; height: 6px;
            }}
        """)
        self._provider_cb.currentIndexChanged.connect(self._on_provider_change)
        layout.addWidget(self._provider_cb)
        layout.addSpacing(4)

        self._key_lbl = _lbl("GEMINI API KEY", 16, color=C.TEXT_DIM, align=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._key_lbl)
        key_row = QHBoxLayout()
        key_row.setSpacing(4)
        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setPlaceholderText("AIza...")
        self._key_input.setFont(QFont("Courier New", 18, QFont.Weight.Bold))
        self._key_input.setFixedHeight(52)
        self._key_input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d12; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 4px; padding: 4px 8px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        key_row.addWidget(self._key_input)
        self._key_toggle = QPushButton("Show")
        self._key_toggle.setFixedSize(130, 52)
        self._key_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._key_toggle.setCheckable(True)
        self._key_toggle.setFont(QFont("Courier New", 26, QFont.Weight.Bold))
        self._key_toggle.setStyleSheet(f"""
            QPushButton {{
                background: #000d12; color: {C.PRI};
                border: 1px solid {C.BORDER}; border-radius: 4px; font-size: 26px; font-weight: bold; font-family: "Courier New";
            }}
            QPushButton:hover {{
                border: 1px solid {C.PRI}; color: {C.PRI};
            }}
            QPushButton:checked {{
                background: #001a20; color: {C.PRI};
                border: 1px solid {C.PRI};
            }}
        """)
        self._key_toggle.toggled.connect(self._on_key_toggle)
        key_row.addWidget(self._key_toggle)
        layout.addLayout(key_row)
        self._key_link = QLabel(
                '<a href="https://aistudio.google.com" style="color: #ff80d5; text-decoration: underline;">Get your free key <span style="font-size:22px;">&rarr;</span></a>'
        )
        self._key_link.setFont(QFont("Courier New", 15, QFont.Weight.Bold))
        self._key_link.setOpenExternalLinks(True)
        self._key_link.setStyleSheet("background: transparent;")
        layout.addWidget(self._key_link)

        self._url_lbl = _lbl("BASE URL", 16, color=C.TEXT_DIM, align=Qt.AlignmentFlag.AlignLeft)
        self._url_lbl.hide()
        layout.addWidget(self._url_lbl)
        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText("http://localhost:11434/v1")
        self._url_input.setFont(QFont("Courier New", 18, QFont.Weight.Bold))
        self._url_input.setFixedHeight(52)
        self._url_input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d12; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 4px; padding: 4px 8px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        self._url_input.hide()
        layout.addWidget(self._url_input)
        layout.addSpacing(8)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep2)
        layout.addSpacing(4)

        layout.addWidget(_lbl("MICROPHONE TEST", 16, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        mic_row = QHBoxLayout(); mic_row.setSpacing(6)
        self._mic_test_btn = QPushButton("> Test Mic")
        self._mic_test_btn.setFont(QFont("Courier New", 17, QFont.Weight.Bold))
        self._mic_test_btn.setFixedSize(200, 48)
        self._mic_test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mic_test_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.ACC2};
                border: 1px solid {C.BORDER_B}; border-radius: 4px;
            }}
            QPushButton:hover {{
                background: {C.PRI_GHO}; border: 1px solid {C.ACC};
            }}
        """)
        self._mic_test_btn.clicked.connect(self._run_mic_test)
        mic_row.addStretch()
        mic_row.addWidget(self._mic_test_btn)
        mic_row.addStretch()
        layout.addLayout(mic_row)
        self._mic_status = QLabel("--")
        self._mic_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mic_status.setFont(QFont("Courier New", 17, QFont.Weight.Bold))
        self._mic_status.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        layout.addWidget(self._mic_status)
        layout.addSpacing(6)

        self._os_btns: dict[str, QPushButton] = {}
        layout.addSpacing(12)

        rem_row = QHBoxLayout(); rem_row.setSpacing(10)
        self._remember_cb = QPushButton()
        self._remember_cb.setCheckable(True)
        self._remember_cb.setChecked(True)
        self._remember_cb.setFixedSize(30, 30)
        self._remember_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        self._remember_cb.setStyleSheet(f"""
            QPushButton {{
                background: #001a20; border: 2px solid {C.PRI};
                border-radius: 4px;
            }}
            QPushButton:!checked {{
                background: #000d12; border: 2px solid {C.BORDER_B};
            }}
        """)
        self._draw_checkmark(True)
        self._remember_cb.toggled.connect(lambda c: self._draw_checkmark(c))
        rem_row.addWidget(self._remember_cb)
        rem_lbl = QLabel("Remember settings (skip this screen next time)")
        rem_lbl.setFont(QFont("Courier New", 18, QFont.Weight.Bold))
        rem_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        rem_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        rem_lbl.mousePressEvent = lambda e: self._remember_cb.toggle()
        rem_row.addWidget(rem_lbl)
        rem_row.addStretch()
        layout.addLayout(rem_row)

        init_btn = QPushButton(">  Start Nova")
        init_btn.setFont(QFont("Courier New", 18, QFont.Weight.Bold))
        init_btn.setFixedHeight(56)
        init_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        init_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.PRI};
                border: 1px solid {C.BORDER_B}; border-radius: 5px;
            }}
            QPushButton:hover {{
                background: {C.PRI_GHO}; border: 1px solid {C.PRI};
            }}
        """)
        init_btn.clicked.connect(self._submit)
        layout.addWidget(init_btn)

    def _on_provider_change(self, idx: int):
        providers = {0: "gemini", 1: "openai", 2: "ollama"}
        prov = providers.get(idx, "gemini")
        self._key_input.clear()
        self._key_toggle.setChecked(False)
        if prov == "gemini":
            self._key_lbl.setText("GEMINI API KEY")
            self._key_input.setPlaceholderText("AIza...")
            self._key_input.show()
            self._key_link.setText(
            '<a href="https://aistudio.google.com" style="color: #ff80d5; text-decoration: underline;">Get your free key <span style="font-size:22px;">&rarr;</span></a>'
            )
            self._key_link.show()
            self._url_lbl.hide()
            self._url_input.hide()
        elif prov == "openai":
            self._key_lbl.setText("OPENAI API KEY")
            self._key_input.setPlaceholderText("sk-...")
            self._key_input.show()
            self._key_link.setText(
                '<a href="https://platform.openai.com" style="color: #ff80d5; text-decoration: underline;">Get your OpenAI key <span style="font-size:22px;">&rarr;</span></a>'
            )
            self._key_link.setOpenExternalLinks(True)
            self._key_link.show()
            self._url_lbl.setText("BASE URL (optional, for Cerebras/Together)")
            self._url_input.setPlaceholderText("https://api.cerebras.ai/v1")
            self._url_lbl.show()
            self._url_input.show()
        elif prov == "ollama":
            self._key_lbl.setText("OLLAMA BASE URL")
            self._key_input.setPlaceholderText("http://localhost:11434/v1")
            self._key_input.show()
            self._key_link.hide()
            self._url_lbl.hide()
            self._url_input.hide()

    def _on_key_toggle(self, checked: bool):
        if checked:
            self._key_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self._key_toggle.setText("Hide")
        else:
            self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
            self._key_toggle.setText("Show")

    def _draw_checkmark(self, checked: bool):
        pix = QPixmap(30, 30)
        pix.fill(Qt.GlobalColor.transparent)
        if checked:
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(C.PRI), 4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(7, 15, 13, 22)
            p.drawLine(13, 22, 24, 8)
            p.end()
        self._remember_cb.setIcon(QIcon(pix))
        self._remember_cb.setIconSize(pix.size())

    def _style_os_default(self, btn: QPushButton):
        btn.setStyleSheet(f"""
            QPushButton {{
                background: #000d12; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 4px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
        """)

    def _sel(self, key: str):
        self._sel_os = key
        pal = {"windows":(C.PRI,"#001a22"),"mac":(C.ACC2,"#1a1400")}
        for k, btn in self._os_btns.items():
            if k == key:
                fg, bg = pal[k]
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {fg}; color: {bg};
                        border: none; border-radius: 3px; font-weight: bold;
                    }}
                """)
            else:
                self._style_os_default(btn)

    def _run_mic_test(self):
        self._mic_test_btn.setEnabled(False)
        self._mic_status.setText("Recording...")
        self._mic_status.setStyleSheet(f"color: {C.WARN}; background: transparent;")
        try:
            duration = 2
            sr = 16000
            recording = sd.rec(int(duration * sr), samplerate=sr, channels=1, dtype="int16")
            sd.wait()
            if recording is not None and len(recording) > sr:
                self._mic_status.setText("PASS")
                self._mic_status.setStyleSheet(f"color: {C.GREEN}; background: transparent;")
            else:
                self._mic_status.setText("FAIL")
                self._mic_status.setStyleSheet(f"color: {C.RED}; background: transparent;")
        except Exception:
            self._mic_status.setText("FAIL")
            self._mic_status.setStyleSheet(f"color: {C.RED}; background: transparent;")
        self._mic_test_btn.setEnabled(True)

    def _submit(self):
        providers = {0: "gemini", 1: "openai", 2: "ollama"}
        prov = providers.get(self._provider_cb.currentIndex(), "gemini")
        key = self._key_input.text().strip()
        url = self._url_input.text().strip()
        if prov == "ollama":
            base_url = key or url or "http://localhost:11434/v1"
        else:
            if not key:
                self._key_input.setStyleSheet(
                    self._key_input.styleSheet() +
                    f" QLineEdit {{ border: 1px solid {C.RED}; }}"
                )
                return
            base_url = url or ""
        self.done.emit({"provider": prov, "api_key": key, "base_url": base_url,
                        "os_name": self._sel_os, "remember": self._remember_cb.isChecked()})

    def apply_scale(self, s: float):
        self.layout().setContentsMargins(int(30 * s), int(22 * s), int(30 * s), int(22 * s))
        self.layout().setSpacing(int(8 * s))
        for w in self.findChildren(QLabel):
            cur = w.font()
            cur.setPointSize(max(5, int(cur.pointSize() * s)))
            w.setFont(cur)
        for w in self.findChildren(QPushButton):
            cur = w.font()
            cur.setPointSize(max(7, int(cur.pointSize() * s)))
            w.setFont(cur)
            w.setFixedHeight(max(24, int(w.height() * s)))
        for w in self.findChildren(QLineEdit):
            cur = w.font()
            cur.setPointSize(max(7, int(cur.pointSize() * s)))
            w.setFont(cur)
            w.setFixedHeight(max(20, int(w.height() * s)))
        for w in self.findChildren(QCheckBox):
            cur = w.font()
            cur.setPointSize(max(5, int(cur.pointSize() * s)))
            w.setFont(cur)
        for w in self.findChildren(QComboBox):
            cur = w.font()
            cur.setPointSize(max(7, int(cur.pointSize() * s)))
            w.setFont(cur)
            w.setFixedHeight(max(24, int(w.height() * s)))


class MainWindow(QMainWindow):
    _log_sig     = pyqtSignal(str)
    _nova_sig    = pyqtSignal(str)
    _nova_end_sig = pyqtSignal()
    _state_sig   = pyqtSignal(str)
    _update_sig  = pyqtSignal(dict)
    _dl_done_sig = pyqtSignal(str)

    def __init__(self, face_path: str = ""):
        super().__init__()
        self.setWindowTitle("Nova")
        ico = BASE_DIR / "icon.ico"
        if ico.exists():
            self.setWindowIcon(QIcon(str(ico)))
        self._update_sig.connect(self._on_update_result)
        self._dl_done_sig.connect(self._on_dl_done)
        self._overlay: SetupOverlay | None = None
        self._orb_opacity: QGraphicsOpacityEffect | None = None
        self._orb_anim: QPropertyAnimation | None = None
        self._font_scale = 1.0
        self._base_font_sizes: dict[int, int] = {}
        self.setMinimumSize(_MIN_W, _MIN_H)
        self.showMaximized()
        self._font_scale = max(0.7, self.height() / 700)

        self.on_text_command  = None
        self._muted           = False
        self._current_file: str | None = None

        central = QWidget()
        central.setStyleSheet(f"background: {C.BG};")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._left_panel = self._build_left_panel()
        body.addWidget(self._left_panel, stretch=0)

        self.hud = HudCanvas(face_path)
        self.hud.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        body.addWidget(self.hud, stretch=5)

        self._right_panel = self._build_right_panel()
        body.addWidget(self._right_panel, stretch=0)

        root.addLayout(body, stretch=1)
        root.addWidget(self._build_footer())

        self._clock_tmr = QTimer(self)
        self._clock_tmr.timeout.connect(self._tick_clock)
        self._clock_tmr.start(1000)
        self._tick_clock()

        # Metrik güncelleme timer'ı
        self._metric_tmr = QTimer(self)
        self._metric_tmr.timeout.connect(self._update_metrics)
        self._metric_tmr.start(2000)
        self._update_metrics()

        self._log_sig.connect(self._log.append_log)
        self._nova_sig.connect(self._log._update_last_nova)
        self._nova_end_sig.connect(self._log._finish_nova)
        self._state_sig.connect(self._apply_state)

        self._ready = self._check_config()
        if not self._ready:
            self._show_setup()

        self._rescale_main_ui(self._font_scale)

        sc_mute = QShortcut(QKeySequence("F4"), self)
        sc_mute.activated.connect(self._toggle_mute)
        sc_full = QShortcut(QKeySequence("F11"), self)
        sc_full.activated.connect(self._toggle_fullscreen)

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cw = self.centralWidget()
        if cw is None:
            return
        self._font_scale = max(0.7, cw.height() / 700)
        self._rescale_main_ui(self._font_scale)
        if self._overlay and self._overlay.isVisible():
            self._overlay.setGeometry(0, 0, cw.width(), cw.height())
            self._overlay.apply_scale(self._font_scale)

    def _rescale_main_ui(self, scale: float):
        def _is_in_overlay(w):
            p = w.parent()
            while p:
                if p is self._overlay:
                    return True
                p = p.parent()
            return False

        for w in self.centralWidget().findChildren(QWidget):
            if _is_in_overlay(w):
                continue
            wid = id(w)
            if isinstance(w, (QLabel, QPushButton, QLineEdit, QCheckBox, QComboBox)):
                f = w.font()
                ps = f.pointSize()
                if ps > 0 and ps < 40:
                    if wid not in self._base_font_sizes:
                        self._base_font_sizes[wid] = ps
                    base = self._base_font_sizes[wid]
                    new_ps = max(5, int(base * scale))
                    if new_ps != ps:
                        f.setPointSize(new_ps)
                        w.setFont(f)
            elif isinstance(w, QTextEdit):
                if wid not in self._base_font_sizes:
                    self._base_font_sizes[wid] = w.font().pointSize()
                base = self._base_font_sizes[wid]
                new_ps = max(5, int(base * scale))
                if new_ps != w.font().pointSize():
                    f = w.font()
                    f.setPointSize(new_ps)
                    w.setFont(f)
                    ss = w.styleSheet()
                    w.setStyleSheet(ss.replace("font-size: 16px", f"font-size: {new_ps}px")
                                      .replace("font-size: 16pt", f"font-size: {new_ps}pt"))

    def _update_metrics(self):
        snap = _metrics.snapshot()

        # CPU
        cpu = snap["cpu"]
        self._bar_cpu.set_value(cpu, f"{cpu:.0f}%")

        # MEM
        mem = snap["mem"]
        self._bar_mem.set_value(mem, f"{mem:.0f}%")

        # NET
        net = snap["net"]
        if net < 1.0:
            net_str = f"{net*1024:.0f}KB/s"
        else:
            net_str = f"{net:.1f}MB/s"
        net_pct = min(100, net * 10)  # 10 MB/s = %100
        self._bar_net.set_value(net_pct, net_str)

        # GPU
        gpu = snap["gpu"]
        if gpu >= 0:
            self._bar_gpu.set_value(gpu, f"{gpu:.0f}%")
            self._bar_gpu.setVisible(True)
        else:
            self._bar_gpu.setVisible(False)

        # TMP
        tmp = snap["tmp"]
        if tmp >= 0:
            tmp_pct = min(100, (tmp / 100) * 100)
            self._bar_tmp.set_value(tmp_pct, f"{tmp:.0f} degC")
            self._bar_tmp.setVisible(True)
        else:
            self._bar_tmp.setVisible(False)


        try:
            boot_t  = psutil.boot_time()
            elapsed = time.time() - boot_t
            h = int(elapsed // 3600)
            m = int((elapsed % 3600) // 60)
            self._uptime_lbl.setText(f"UP  {h:02d}:{m:02d}")
        except Exception:
            self._uptime_lbl.setText("UP  --:--")

        try:
            proc_count = len(psutil.pids())
            self._proc_lbl.setText(f"PROC  {proc_count}")
        except Exception:
            self._proc_lbl.setText("PROC  --")


    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(54)
        w.setStyleSheet(f"background: {C.DARK}; border-bottom: 1px solid {C.BORDER};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(16, 0, 16, 0)

        def _badge(txt, color=C.TEXT_MED):
            l = QLabel(txt)
            l.setFont(QFont("Courier New", 9))
            l.setStyleSheet(f"color: {color}; background: transparent;")
            return l

        lay.addWidget(_badge("Nova", C.PRI_DIM))
        lay.addStretch()

        mid = QVBoxLayout(); mid.setSpacing(0)
        title = QLabel("Nova")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Courier New", 15, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        mid.addWidget(title)
        sub = QLabel("Prompt Once. Done.")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setFont(QFont("Courier New", 9))
        sub.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        mid.addWidget(sub)
        lay.addLayout(mid)
        lay.addStretch()

        right_col = QVBoxLayout(); right_col.setSpacing(1)
        self._clock_lbl = QLabel("00:00:00")
        self._clock_lbl.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
        self._clock_lbl.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        self._clock_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._clock_lbl)
        self._date_lbl = QLabel("")
        self._date_lbl.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        self._date_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        self._date_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._date_lbl)
        lay.addLayout(right_col)
        return w

    def _tick_clock(self):
        self._clock_lbl.setText(time.strftime("%H:%M:%S"))
        self._date_lbl.setText(time.strftime("%a %d %b %Y"))

    def _build_left_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(_LEFT_W)
        w.setStyleSheet(f"background: {C.DARK}; border-right: 1px solid {C.BORDER};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(5)

        hdr = QLabel("# SYS MONITOR")
        hdr.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent; "
                          f"border-bottom: 1px solid {C.BORDER}; padding-bottom: 3px;")
        lay.addWidget(hdr)
        lay.addSpacing(2)

        self._bar_cpu = MetricBar("CPU", C.PRI)
        self._bar_mem = MetricBar("MEM", C.ACC2)
        self._bar_net = MetricBar("NET", C.GREEN)
        self._bar_gpu = MetricBar("GPU", C.ACC)
        self._bar_tmp = MetricBar("TMP", "#ff6688")

        for bar in [self._bar_cpu, self._bar_mem, self._bar_net,
                    self._bar_gpu, self._bar_tmp]:
            lay.addWidget(bar)

        lay.addSpacing(2)

        info_panel = QWidget()
        info_panel.setStyleSheet(
            f"background: {C.PANEL2}; border: 1px solid {C.BORDER}; border-radius: 5px;"
        )
        ip_lay = QVBoxLayout(info_panel)
        ip_lay.setContentsMargins(6, 5, 6, 5)
        ip_lay.setSpacing(2)

        self._uptime_lbl = QLabel("UP  --:--")
        self._uptime_lbl.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        self._uptime_lbl.setStyleSheet(f"color: {C.GREEN}; background: transparent; border: none;")
        ip_lay.addWidget(self._uptime_lbl)

        self._proc_lbl = QLabel("PROC  --")
        self._proc_lbl.setFont(QFont("Courier New", 10))
        self._proc_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; border: none;")
        ip_lay.addWidget(self._proc_lbl)

        os_lbl = QLabel(f"OS  WIN")
        os_lbl.setFont(QFont("Courier New", 10))
        os_lbl.setStyleSheet(f"color: {C.ACC2}; background: transparent; border: none;")
        ip_lay.addWidget(os_lbl)

        lay.addWidget(info_panel)
        lay.addStretch()

        # version selector
        ver_lbl = QLabel("VERSION")
        ver_lbl.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        ver_lbl.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent; "
                              f"border-bottom: 1px solid {C.BORDER}; padding-bottom: 2px; margin-top: 4px;")
        lay.addWidget(ver_lbl)

        self._ver_combo = QComboBox()
        self._ver_combo.setFont(QFont("Courier New", 11))
        self._ver_combo.addItem(f"v{__version__} (current)")
        self._ver_combo.addItem("v2.0.5")
        self._ver_combo.addItem("v2.0.3")
        self._ver_combo.addItem("v2.0.1")
        self._ver_combo.addItem("v2.0.0")
        self._ver_combo.addItem("v1.0.0")
        self._ver_combo.setCurrentIndex(0)
        self._ver_combo.currentIndexChanged.connect(self._on_version_changed)
        self._ver_combo.setStyleSheet(
            f"background: {C.PANEL2}; color: {C.TEXT}; border: 1px solid {C.BORDER};"
            f"border-radius: 4px; padding: 3px 4px;"
        )
        lay.addWidget(self._ver_combo)

        return w

    def _on_version_changed(self, idx: int):
        vers = ["v2.0.5", "v2.0.4", "v2.0.3", "v2.0.1", "v2.0.0", "v1.0.0"]
        if idx == 0:
            return
        ver = vers[idx]
        url = f"https://github.com/coolcat125/Nova-AI/releases/download/{ver}/Nova.exe"
        self._log.append_log(f"SYS: Downloading {ver}...")
        self._ver_combo.setEnabled(False)
        threading.Thread(target=self._dl_version, args=(url,), daemon=True).start()

    def _dl_version(self, url: str):
        from update import download_to_temp
        path = download_to_temp(url)
        self._dl_done_sig.emit(path)

    def _on_dl_done(self, path: str):
        self._ver_combo.setEnabled(True)
        if not path:
            self._log.append_log("SYS: Download failed")
            return
        self._log.append_log("SYS: Applying...")
        from update import apply_local
        apply_local(path)

    def _build_right_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(_RIGHT_W)
        w.setStyleSheet(f"background: {C.DARK}; border-left: 1px solid {C.BORDER};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(5)

        def _sec(txt):
            l = QLabel(f"> {txt}")
            l.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
            l.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
            return l

        lay.addWidget(_sec("ACTIVITY LOG"))
        self._log = LogWidget()
        lay.addWidget(self._log, stretch=1)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        lay.addWidget(_sec("FILE UPLOAD"))
        self._drop_zone = FileDropZone()
        self._drop_zone.file_selected.connect(self._on_file_selected)
        lay.addWidget(self._drop_zone)

        self._file_hint = QLabel("No file loaded  --  drop or click above to upload")
        self._file_hint.setFont(QFont("Courier New", 9))
        self._file_hint.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._file_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._file_hint.setWordWrap(True)
        lay.addWidget(self._file_hint)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep2)

        lay.addWidget(_sec("COMMAND INPUT"))
        lay.addLayout(self._build_input_row())

        self._mute_btn = QPushButton("  MICROPHONE ACTIVE")
        self._mute_btn.setFixedHeight(28)
        self._mute_btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.clicked.connect(self._toggle_mute)
        self._style_mute_btn()
        lay.addWidget(self._mute_btn)

        fs_btn = QPushButton("FULLSCREEN  [F11]")
        fs_btn.setFixedHeight(30)
        fs_btn.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        fs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        fs_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 4px;
            }}
            QPushButton:hover {{
                color: {C.PRI}; border: 1px solid {C.BORDER_B};
            }}
        """)
        fs_btn.clicked.connect(self._toggle_fullscreen)
        lay.addWidget(fs_btn)

        upd_btn = QPushButton("CHECK FOR UPDATES")
        upd_btn.setFixedHeight(30)
        upd_btn.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        upd_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        upd_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.ACC2};
                border: 1px solid {C.BORDER}; border-radius: 4px;
            }}
            QPushButton:hover {{
                color: {C.TEXT}; border: 1px solid {C.BORDER_B};
            }}
        """)
        upd_btn.clicked.connect(self._manual_update_check)
        lay.addWidget(upd_btn)

        return w

    def _build_input_row(self) -> QHBoxLayout:
        row = QHBoxLayout(); row.setSpacing(5)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a command or question...")
        self._input.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        self._input.setFixedHeight(42)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: #0d0218; color: {C.WHITE};
                border: 2px solid {C.BORDER}; border-radius: 5px; padding: 6px 10px;
            }}
            QLineEdit:focus {{ border: 2px solid {C.BORDER_B}; }}
        """)
        self._input.returnPressed.connect(self._send)
        row.addWidget(self._input)

        send = QPushButton(">")
        send.setFixedSize(32, 32)
        send.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL}; color: {C.PRI};
                border: 1px solid {C.BORDER}; border-radius: 5px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        send.clicked.connect(self._send)
        row.addWidget(send)
        return row

    def _build_footer(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(28)
        w.setStyleSheet(f"background: {C.DARK}; border-top: 1px solid {C.BORDER};")
        lay = QHBoxLayout(w); lay.setContentsMargins(14, 0, 14, 0)

        def _fl(txt, color=C.TEXT_DIM):
            l = QLabel(txt); l.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
            l.setStyleSheet(f"color: {color}; background: transparent;")
            return l

        lay.addWidget(_fl("[F4] Mute   |   [F11] Fullscreen"))
        lay.addStretch()
        lay.addWidget(_fl("Nova"))
        return w

    def _on_file_selected(self, path: str):
        self._current_file = path
        p    = Path(path)
        cat  = _file_category(p)
        icon, _ = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size = _fmt_size(p.stat().st_size)
        self._file_hint.setText(f"{icon}  {p.name}   |   {size}   |   Tell Nova what to do with it")
        self._log.append_log(f"FILE: {p.name} ({size}) loaded")
        if self.on_text_command:
            msg = (
                f"[FILE_UPLOADED] path={path} | name={p.name} | "
                f"type={p.suffix.lstrip('.')} | size={size} | "
                f"Briefly tell the user you can see the file '{p.name}' "
                f"({size}) has been uploaded and ask what they'd like to do with it."
            )
            threading.Thread(target=self.on_text_command, args=(msg,), daemon=True).start()

    def _on_update_result(self, result: dict):
        if result.get("update_available"):
            ver = result.get("version", "?")
            reply = QMessageBox.question(
                self, "Update Available",
                f"Nova v{ver} is available.\n\nDownload and install now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                from update import apply_update
                self._log.append_log(f"SYS: Downloading v{ver}...")
                threading.Thread(
                    target=lambda: self._do_update(result.get("download_url", "")),
                    daemon=True,
                ).start()
        elif result.get("error"):
            self._log.append_log(f"SYS: Update check failed: {result['error']}")

    def _do_update(self, url: str):
        from update import apply_update
        result = apply_update(url)
        if result.get("error"):
            self._log.append_log(f"SYS: Update failed: {result['error']}")

    def restart_app(self):
        self._log.append_log("SYS: Restarting...")
        self._apply_state("RESTARTING")
        QTimer.singleShot(5000, self._do_restart)

    def _do_restart(self):
        import subprocess, sys
        if getattr(sys, "frozen", False):
            subprocess.Popen([sys.executable])
        else:
            subprocess.Popen([sys.executable, str(Path(__file__).resolve().parent / "main.py")])
        QApplication.instance().quit()

    def _manual_update_check(self):
        self._log.append_log("SYS: Checking for updates...")
        from update import check_for_update_async
        check_for_update_async(callback=lambda r: self._update_sig.emit(r))

    def _toggle_mute(self):
        self._muted = not self._muted
        self.hud.muted = self._muted
        self._style_mute_btn()
        if self._muted:
            self._apply_state("MUTED")
            self._log.append_log("SYS: Microphone muted.")
        else:
            self._apply_state("LISTENING")
            self._log.append_log("SYS: Microphone active.")

    def _style_mute_btn(self):
        if self._muted:
            self._mute_btn.setText("  MICROPHONE MUTED")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #140006; color: {C.MUTED_C};
                    border: 1px solid {C.MUTED_C}; border-radius: 4px;
                }}
                QPushButton:hover {{ background: #1e000a; }}
            """)
        else:
            self._mute_btn.setText("  MICROPHONE ACTIVE")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #00140a; color: {C.GREEN};
                    border: 1px solid {C.GREEN}; border-radius: 4px;
                }}
                QPushButton:hover {{ background: #001f10; }}
            """)

    def _send(self):
        txt = self._input.text().strip()
        if not txt: return
        self._input.clear()
        self._log.append_log(f"You: {txt}")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(txt,), daemon=True).start()

    def _apply_state(self, state: str):
        self.hud.state    = state
        self.hud.speaking = (state == "SPEAKING")

    def _check_config(self) -> bool:
        if not API_FILE.exists(): return False
        try:
            from dotenv import load_dotenv
            load_dotenv(API_FILE)
            prov = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
            if prov == "gemini":
                return bool(os.getenv("GEMINI_API_KEY")) and bool(os.getenv("OS_SYSTEM"))
            elif prov == "openai":
                return bool(os.getenv("OPENAI_API_KEY")) and bool(os.getenv("OS_SYSTEM"))
            elif prov == "ollama":
                return bool(os.getenv("OS_SYSTEM"))
        except Exception:
            return False

    def _show_setup(self):
        self._orb_opacity = QGraphicsOpacityEffect(self.hud)
        self._orb_opacity.setOpacity(0.0)
        self.hud.setGraphicsEffect(self._orb_opacity)

        ov = SetupOverlay(self.centralWidget())
        cw = self.centralWidget()
        ov.setGeometry(0, 0, cw.width(), cw.height())
        ov.apply_scale(self._font_scale)
        ov.done.connect(self._on_setup_done)
        ov.show()
        self._overlay = ov

    def _on_setup_done(self, cfg: dict):
        prov = cfg.get("provider", "gemini")
        os_name = cfg.get("os_name", "windows")
        remember = cfg.get("remember", True)
        api_key = cfg.get("api_key", "")
        base_url = cfg.get("base_url", "")

        os.environ["LLM_PROVIDER"] = prov
        os.environ["OS_SYSTEM"] = os_name
        if prov == "gemini":
            os.environ["GEMINI_API_KEY"] = api_key
        elif prov == "openai":
            os.environ["OPENAI_API_KEY"] = api_key
            if base_url:
                os.environ["OPENAI_BASE_URL"] = base_url
        elif prov == "ollama":
            os.environ["OLLAMA_BASE_URL"] = base_url

        if remember:
            API_FILE.parent.mkdir(parents=True, exist_ok=True)
            lines = [f"LLM_PROVIDER={prov}", f"OS_SYSTEM={os_name}"]
            if prov == "gemini":
                lines.append(f"GEMINI_API_KEY={api_key}")
            elif prov == "openai":
                lines.append(f"OPENAI_API_KEY={api_key}")
                if base_url:
                    lines.append(f"OPENAI_BASE_URL={base_url}")
            elif prov == "ollama":
                lines.append(f"OLLAMA_BASE_URL={base_url}")
            with open(API_FILE, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        elif API_FILE.exists():
            API_FILE.unlink()
        self._ready = True
        if self._overlay:
            self._overlay.hide()
            self._overlay = None
        if self._orb_opacity:
            anim = QPropertyAnimation(self._orb_opacity, b"opacity")
            anim.setDuration(300)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.start()
            self._orb_anim = anim
        self._apply_state("LISTENING")
        self._log.append_log(f"SYS: Initialised. OS={os_name.upper()}. Nova online.")

class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app
    def mainloop(self):
        self._app.exec()
    def protocol(self, *_):
        pass


class NovaUI:
    def __init__(self, face_path: str = "", size=None):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("nova.desktop.v2")
        except Exception:
            pass
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")
        ico = BASE_DIR / "icon.ico"
        if ico.exists():
            self._app.setWindowIcon(QIcon(str(ico)))
        self._win = MainWindow(face_path)
        self._win.show()
        QTimer.singleShot(0, _force_taskbar_icon)
        self.root = _RootShim(self._app)

    @property
    def muted(self) -> bool:
        return self._win._muted

    @muted.setter
    def muted(self, v: bool):
        if v != self._win._muted:
            self._win._toggle_mute()

    @property
    def current_file(self) -> str | None:
        return self._win._drop_zone.current_file()

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    def set_state(self, state: str):
        self._win._state_sig.emit(state)

    def write_log(self, text: str):
        self._win._log_sig.emit(text)

    def write_nova(self, text: str):
        self._win._nova_sig.emit(text)

    def finish_nova(self):
        self._win._nova_end_sig.emit()

    def wait_for_api_key(self):
        while not self._win._ready:
            time.sleep(0.1)

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")
