"""app.py — time_is_money 打工人实时薪资钟 tkinter UI（v4 玻璃拟态 · 可缩放）。

- 视觉：壁纸背景 + 毛玻璃面板（苹果玻璃卡片质感）。窗口默认 348×452，可任意
  拖拽缩放：尺寸变化时即时重排文字/重设圆角区域，停稳后（150ms 防抖）用
  Pillow 按新尺寸重烘焙背景；未安装 Pillow 时回退固定尺寸 + 预生成背景
  （assets/bg_<theme>.png）。
  全部文字不带描边，可读性由烘焙层（渐晕/面板材质）保证；
- 月薪为机密：设置弹窗中默认以 • 掩码显示，可勾选「显示」临时查看；
- 上班开始/结束用 Spinbox 时间选择控件（只读+循环滚动），非手输框；
- 休假两种模式：weekend=固定周末公休；free=周末照常上班。两种模式均可用设置
  日历或菜单「标记今天」按日标记调休/请假（调休重算秒薪，请假扣日薪）；
- 主界面聚焦实时收入：今日已赚超大字号居中；设置收进顶部菜单栏（苹果风）；
- 三套主题（midnight/paper/glass）共享一套冰蓝强调色 token 表；主数字等宽字体；
  加班期切暗黑壁纸（模糊压暗 + 红字）；单实例互斥体防多开。

约束沿袭：单窗口单线程，全部刷新由 root.after(1000) 单循环驱动（R1）；
每 tick 用真实当前时刻重算（A10/R2）；tick 异常兜底（A11/R5）；公式一律调 money 纯函数；
config.json 固定位于本脚本目录、与 CWD 无关（A12）。
"""

import ctypes
import ctypes.wintypes
import json
import math
import os
import time
import tkinter as tk
import tkinter.font as tkfont
import tkinter.messagebox
import winsound
from datetime import date, datetime

import money

# config schema 默认值（缺失 config 时进设置弹窗待保存）；旧版 config 自动补新字段
DEFAULT_CONFIG = {
    "monthly_salary": 10000.0,
    "work_start": "09:00",
    "work_end": "18:00",
    "holiday_mode": "weekend",  # weekend=固定周末公休 | free=自由假期
    "leaves": {                 # 分模式当月休假：{模式: {ISO 日期: "调休"/"请假"}}，互不影响
        "weekend": {},
        "free": {},
    },
    "payday": 15,
    "theme": "midnight",
    "last_asked_date": "",
}

CONFIG_FILENAME = "config.json"
TICK_MS = 1000
LIVE_BAKE_MS = 120      # 拖动中实时重烘焙节流间隔：背景以 ≤120ms 延迟跟手
# 实时烘焙一律走 1/3 快速管线（~20ms，拖动中不卡主线程）；停稳后全质量重烘

# ---- 窗口与布局 ----
# 默认尺寸为旧版 520×680 的 2/3；窗口可任意拖拽缩放，背景毛玻璃随尺寸实时重烘焙
# （需 Pillow，未安装时回退固定尺寸 + 预生成 assets/bg_<theme>.png）。布局全部按比例计算。
DEFAULT_WIN_W, DEFAULT_WIN_H = 348, 452
MIN_WIN_W, MIN_WIN_H = 300, 400
WALLPAPER = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "assets", "wallpaper.jpg")
WALLPAPER_EXPLOIT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "assets", "wallpaper_exploit.jpg")


def _pillow_available() -> bool:
    """启动时探测一次 Pillow（任意缩放需要运行时烘焙背景）。"""
    try:
        import make_bg  # noqa: F401
        return True
    except Exception:
        return False


def compute_layout(w: int, h: int) -> dict:
    """按窗口尺寸比例计算全部绘制位置（app 绘制与 make_bg 烘焙共用，防止错位）。"""
    m = max(14, int(w * 0.075))  # 左右边距
    span = w - 2 * m
    return {
        "margin": m,
        "title": (w // 2, int(h * 0.075)),
        "main": (m, int(h * 0.14), w - m, int(h * 0.505)),   # 今日已赚面板
        "today_label": (w // 2, int(h * 0.18)),
        "today": (w // 2, int(h * 0.305)),
        "sub": (w // 2, int(h * 0.44)),
        "stats": (m, int(h * 0.545), w - m, int(h * 0.685)),  # 统计面板
        "stat_xs": (int(m + span / 6), w // 2, int(w - m - span / 6)),
        "stat_label_y": int(h * 0.592),
        "stat_value_y": int(h * 0.648),
        "status": (w // 2, int(h * 0.925)),
    }

# 主题 = 完整外观 token（冰蓝强调色锁定：暗色 #7DB8FF / 亮色 #0A84FF / glass #0066D6）
THEMES = {
    "midnight": {
        "label": "暗夜玻璃",
        "accent": "#7DB8FF", "title": "#F5F5F7", "ink": "#F5F5F7",
        "label_ink": "#9698A3", "sub": "#6B6E78",
        "dlg_bg": "#1C1E24", "field_bg": "#26282F", "field_fg": "#F5F5F7",
        "line": "#3A3D46", "btn_bg": "#7DB8FF", "btn_fg": "#0F1216",
        "btn_active": "#99C6FF", "btn2_bg": "#2E3138", "btn2_fg": "#F5F5F7",
        "err": "#FF6B6B", "menu_bg": "#1C1E24", "menu_fg": "#F5F5F7",
        "menu_active_bg": "#7DB8FF", "menu_active_fg": "#0F1216",
        "menu_disabled": "#6B6E78", "fallback": "#1F2128",
    },
    "paper": {
        "label": "纯净亮色",
        "accent": "#0A84FF", "title": "#3A3A3C", "ink": "#1D1D1F",
        "label_ink": "#6E6E73", "sub": "#98989D",
        "dlg_bg": "#F5F5F7", "field_bg": "#FFFFFF", "field_fg": "#1D1D1F",
        "line": "#D2D2D7", "btn_bg": "#0A84FF", "btn_fg": "#FFFFFF",
        "btn_active": "#3395FF", "btn2_bg": "#E9E9EB", "btn2_fg": "#1D1D1F",
        "err": "#E02D2D", "menu_bg": "#F5F5F7", "menu_fg": "#1D1D1F",
        "menu_active_bg": "#0A84FF", "menu_active_fg": "#FFFFFF",
        "menu_disabled": "#B0B0B5", "fallback": "#F7F8FA",
    },
    "glass": {
        "label": "经典白玻璃",
        "accent": "#0066D6", "title": "#FFFFFF", "ink": "#1D1D1F",
        "label_ink": "#515154", "sub": "#6E6E73",
        "dlg_bg": "#F5F5F7", "field_bg": "#FFFFFF", "field_fg": "#1D1D1F",
        "line": "#D2D2D7", "btn_bg": "#0066D6", "btn_fg": "#FFFFFF",
        "btn_active": "#2A7AE0", "btn2_bg": "#E9E9EB", "btn2_fg": "#1D1D1F",
        "err": "#E02D2D", "menu_bg": "#F5F5F7", "menu_fg": "#1D1D1F",
        "menu_active_bg": "#0066D6", "menu_active_fg": "#FFFFFF",
        "menu_disabled": "#B0B0B5", "fallback": "#F2F3F5",
    },
}
LEGACY_THEME = {"mint": "glass", "amber": "glass", "sky": "glass"}  # 旧强调色 → 观感最接近
MODE_LABELS = {"weekend": "固定周末公休", "free": "自由假期（当月任选）"}

EXPLOIT_BG = "#0D0D0D"
EXPLOIT_FG = "#FF5252"
EXPLOIT_HIGHLIGHT = "#FF1744"
EXPLOIT_ACCENT = "#B71C1C"

FONT_APP = ("Microsoft YaHei UI", 10)
FONT_APP_SMALL = ("Microsoft YaHei UI", 9)


def scale_fonts(w: int, mono: str = "Consolas") -> dict:
    """字号随窗口宽度缩放；数字用等宽字体（tabular，每秒跳动不抖宽）。"""
    yahei = "Microsoft YaHei UI"
    return {
        "app": (yahei, 10),
        "small": (yahei, 9),
        "title": (yahei, max(11, min(int(w * 0.036), 18)), "bold"),
        "label": (yahei, max(9, min(int(w * 0.03), 13))),
        "sub": (yahei, max(10, min(int(w * 0.032), 14))),
        "value": (mono, max(10, min(int(w * 0.037), 15)), "bold"),
        "value_cjk": (yahei, max(10, min(int(w * 0.037), 15)), "bold"),
        "huge": (mono, max(24, min(int(w * 0.135), 72)), "bold"),
    }


# ---------------------------------------------------------------------------
# config.json 持久化（A12 / R4）
# ---------------------------------------------------------------------------

def config_path() -> str:
    """config.json 固定与 app.py 同目录，与 CWD 无关。"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG_FILENAME)


def load_config(path: str | None = None) -> tuple[dict, str]:
    """读取 config.json，返回 (config, 警告文案)。

    缺失 → 默认值；JSON 损坏或字段非法 → 重置默认并提示（R4）。
    theme 旧值（mint/amber/sky）自动迁移；非法 theme 回退 midnight（不重置整表）。
    """
    cfg = dict(DEFAULT_CONFIG)
    # 嵌套 leaves 浅拷会与 DEFAULT_CONFIG 共享可变对象，必须逐层复制
    cfg["leaves"] = {m: dict(v) for m, v in DEFAULT_CONFIG["leaves"].items()}
    target = path or config_path()
    if not os.path.exists(target):
        return cfg, ""
    try:
        with open(target, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("config root is not a JSON object")
        loaded = dict(DEFAULT_CONFIG)
        for key in DEFAULT_CONFIG:
            if key in data:
                loaded[key] = data[key]
        if loaded["holiday_mode"] not in ("weekend", "free"):
            raise ValueError("bad holiday_mode")
        loaded["leaves"] = {"weekend": {}, "free": {}}
        legacy = {}
        fh = data.get("free_holidays", [])
        if not isinstance(fh, list):  # 标量/对象 → 沿袭 R4 整表重置；缺失容忍（新配置无此键）
            raise ValueError("bad free_holidays")
        for d in fh:  # 旧自由假日 → 调休（归入 free 组）
            if isinstance(d, str):
                legacy[d] = "调休"
        raw = data.get("leaves")
        if isinstance(raw, dict):
            if "weekend" in raw or "free" in raw:      # 嵌套形态（分模式）
                for mode in ("weekend", "free"):
                    if isinstance(raw.get(mode), dict):
                        loaded["leaves"][mode].update(raw[mode])
            else:                                       # 本分支早期 flat 形态 → free 组
                loaded["leaves"]["free"].update(raw)
        elif raw is not None:
            raise ValueError("bad leaves")  # 非法类型 → 沿袭 R4 整表重置
        loaded["leaves"]["free"].update(legacy)  # 旧自由假日最后放，不覆盖已有
        if money.validate(loaded["monthly_salary"], loaded["work_start"],
                          loaded["work_end"], loaded["leaves"][loaded["holiday_mode"]],
                          loaded["payday"], loaded["holiday_mode"]):
            raise ValueError("config fields failed money.validate")
        loaded["theme"] = str(loaded["theme"])  # 防不可哈希 JSON 值在下方查找中抛 TypeError
        loaded["theme"] = LEGACY_THEME.get(loaded["theme"], loaded["theme"])
        if loaded["theme"] not in THEMES:
            loaded["theme"] = "midnight"
        loaded["last_asked_date"] = str(loaded["last_asked_date"])
        return loaded, ""
    except (OSError, ValueError):
        return dict(DEFAULT_CONFIG), "config.json 读取失败，已重置为默认值，请检查后重新保存"


def save_config(cfg: dict) -> bool:
    """整体写回 config.json。"""
    try:
        with open(config_path(), "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------

class PayClockApp:
    """顶部菜单 + 实时收入主界面 + 设置弹窗 + 下班询问 + 暗黑压榨模式。"""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.cfg, load_warning = load_config()
        self.configured = os.path.exists(config_path()) and not load_warning
        self.pss = 0.0                 # 当月秒薪（月度派生缓存）
        self.daily = 0.0               # 当月日薪（月度派生缓存，请假显示用）
        self.overtime_start = None     # 加班激活时刻；None = 非加班
        self.cached_date = None        # tick 跨日/跨月检测缓存
        self.ask_dialog = None         # 「今天加班吗」非模态弹窗
        self.settings_dialog = None    # 设置弹窗（同一时刻至多一个）
        self.canvas = None             # 主画布（全部实时内容绘在其上）
        self._bg_photo = None          # 背景图引用（防 GC）
        self._end_btn = None           # 结束加班按钮引用（防 GC）
        self._win_w = DEFAULT_WIN_W    # 当前布局尺寸（缩放时跟随更新）
        self._win_h = DEFAULT_WIN_H
        self._bg_size = (0, 0)         # 已烘焙背景对应的窗口尺寸
        self._resize_after = None      # 缩放防抖定时器
        self._status_after = None      # 状态行自动清除定时器
        self._last_live_bake = 0.0     # 上次拖动中实时烘焙的时刻（monotonic 秒）
        self._rgn_size = (0, 0)        # 已应用圆角区域对应的窗口尺寸
        self._can_resize_bg = False    # Pillow 可用时才开任意缩放（构建 UI 前探测）
        self._menu_bar = None          # 菜单引用（_restyle_menu 用，None 守卫）
        self._menu_set = None
        self._theme_menu = None
        self._today_menu = None        # 「标记今天」子菜单引用
        # 等宽字体探测（Consolas → Cascadia Mono → Courier New，按系统可用性回退）
        fams = set(tkfont.families(root))
        self._mono = ("Consolas" if "Consolas" in fams
                      else "Cascadia Mono" if "Cascadia Mono" in fams else "Courier New")
        self._build_menu()
        # 先探测 Pillow（决定可缩放/固定尺寸分支），再构建 UI，避免先绑回调后发现回退
        self._can_resize_bg = _pillow_available()
        self._build_ui()
        self._refresh_month_cache(datetime.now())
        self._rebake_background()
        self._rerender()
        self._update_display(datetime.now())
        self._apply_window_chrome(initial=True)
        if load_warning:
            self._set_status(load_warning, clear_ms=0)
        self.root.after(TICK_MS, self._tick)

    # ---------------- 顶部菜单栏（苹果风：拍平到顶栏，配色随主题 token）----------------

    def _build_menu(self) -> None:
        menu_font = ("Microsoft YaHei UI", 10)

        def apple_menu(master):
            """苹果风菜单骨架：颜色统一由 _restyle_menu 按主题上色。"""
            return tk.Menu(master, tearoff=0, font=menu_font,
                           activeborderwidth=0, bd=0, relief="flat")

        menubar = apple_menu(self.root)
        m_set = apple_menu(menubar)
        m_set.add_command(label="设置…", command=self._open_settings)
        menubar.add_cascade(label="设置", menu=m_set)

        m_theme = apple_menu(menubar)
        self.theme_var = tk.StringVar(value=self._theme_key())
        for key in THEMES:
            m_theme.add_radiobutton(label=THEMES[key]["label"], value=key,
                                    variable=self.theme_var,
                                    command=self._on_theme_change)
        menubar.add_cascade(label="主题", menu=m_theme)
        self._theme_menu = m_theme
        self._menu_set = m_set

        # 「标记今天」子菜单：调休/请假/取消标记（两种假期模式都可用）
        m_today = apple_menu(menubar)
        m_today.add_command(label="调休", command=lambda: self._mark_today("调休"))
        m_today.add_command(label="请假", command=lambda: self._mark_today("请假"))
        m_today.add_command(label="取消标记", command=self._unmark_today)
        menubar.add_cascade(label="标记今天", menu=m_today)
        self._today_menu = m_today
        self._menu_bar = menubar
        self.root.configure(menu=menubar)
        self._restyle_menu()
        self._update_today_menu()

    def _update_today_menu(self) -> None:
        """今天已标记 → 「取消标记」可用；未标记 → 禁用（调休/请假随时可点）。"""
        if self._today_menu is None:
            return
        mode_leaves = self.cfg["leaves"].get(self.cfg["holiday_mode"], {})
        marked = datetime.now().date().isoformat() in mode_leaves
        self._today_menu.entryconfig(2, state="normal" if marked else "disabled")

    def _apply_window_chrome(self, initial: bool = False) -> None:
        """窗口圆角（Win10/11 均可用，SetWindowRgn + GDI 圆角矩形区域）。

        实测要点：① 区域必须用 GetWindowRect 逻辑尺寸且不得超出窗口范围
        （超出会被系统拒绝，窗口变回直角）；② 窗口缩放/最大化后区域不会自动
        跟随，必须按新尺寸重新应用（本方法在每次尺寸变化时被调用）。
        调用失败则静默跳过，不影响功能。
        """
        try:
            user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
            if initial:
                self.root.update_idletasks()
            hwnd = user32.GetParent(self.root.winfo_id())
            wr = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(wr))
            size = (wr.right - wr.left, wr.bottom - wr.top)
            if size == self._rgn_size:
                return  # 尺寸没变，无需重设
            rgn = gdi32.CreateRoundRectRgn(0, 0, size[0], size[1], 24, 24)
            user32.SetWindowRgn(hwnd, rgn, True)
            self._rgn_size = size
        except Exception:
            pass

    def _mark_today(self, leave_type: str) -> None:
        """把今天标记为指定类型休假（weekend 模式的公休日拒绝标记）。"""
        today = datetime.now().date()
        mode = self.cfg["holiday_mode"]
        if today.isoformat() in money.fixed_rest_iso(today.year, today.month, mode):
            self._set_status("公休日本就休息，无需标记")
            return
        leaves = {m: dict(v) for m, v in self.cfg["leaves"].items()}
        leaves[mode][today.isoformat()] = leave_type
        candidate = {**self.cfg, "leaves": leaves}
        # A2 预检：标完最后一个工作日会使 D=0，先把非法配置写盘会被下次启动整表重置
        if money.month_paid_days(datetime.now().year, datetime.now().month,
                                 candidate["leaves"][mode], mode) <= 0:
            self._set_status("标记失败：本月应出勤天数已用尽")
            return
        if not save_config(candidate):
            self._set_status("警告：config.json 写入失败", clear_ms=0)
            return
        self.cfg.update(candidate)
        self._refresh_month_cache(datetime.now())
        self._update_today_menu()
        self._update_display(datetime.now())
        self._set_status(f"已标记今天{leave_type}")

    def _unmark_today(self) -> None:
        """取消今天的休假标记（未标记时静默返回）。"""
        mode = self.cfg["holiday_mode"]
        key = datetime.now().date().isoformat()
        if key not in self.cfg["leaves"].get(mode, {}):
            return
        leaves = {m: dict(v) for m, v in self.cfg["leaves"].items()}
        leaves[mode].pop(key, None)
        candidate = {**self.cfg, "leaves": leaves}
        if not save_config(candidate):
            self._set_status("警告：config.json 写入失败", clear_ms=0)
            return
        self.cfg.update(candidate)
        self._refresh_month_cache(datetime.now())
        self._update_today_menu()
        self._update_display(datetime.now())
        self._set_status("已取消今天的休假标记")

    # ---------------- 界面构建（Canvas + 实时烘焙玻璃背景，可任意缩放）----------------

    def _build_ui(self) -> None:
        self.root.title("时间就是金钱 · 实时薪资钟")
        self.root.geometry(f"{DEFAULT_WIN_W}x{DEFAULT_WIN_H}")
        self.root.minsize(MIN_WIN_W, MIN_WIN_H)

        self.canvas = tk.Canvas(self.root, width=DEFAULT_WIN_W,
                                height=DEFAULT_WIN_H,
                                bg=self._tokens()["dlg_bg"],
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        if self._can_resize_bg:  # 窗口缩放 → 防抖后按新尺寸重烘焙背景与布局
            self.root.resizable(True, True)
            self.canvas.bind("<Configure>", self._on_canvas_configure)
        else:
            self.root.resizable(False, False)  # 无 Pillow：回退固定尺寸 + 预生成背景
            self._reload_fallback_bg()
            if self._bg_photo is not None:
                self._win_w, self._win_h = self._bg_size
                self.root.geometry(f"{self._win_w}x{self._win_h}")  # 跟随预生成背景尺寸

    def _rebake_background(self, fast: bool = False) -> None:
        """按当前窗口尺寸烘焙背景（主壁纸/加班壁纸随模式切换），后重绘内容。

        fast=True 用 1/3 快速管线（拖动中实时预览），停稳后用全质量重烘。
        """
        if not self._can_resize_bg:
            return  # 无 Pillow：固定尺寸回退，不烘焙
        w = max(MIN_WIN_W, self.canvas.winfo_width()) if self.canvas.winfo_ismapped() \
            else self._win_w
        h = max(MIN_WIN_H, self.canvas.winfo_height()) if self.canvas.winfo_ismapped() \
            else self._win_h
        self._win_w, self._win_h = w, h
        try:
            import make_bg
            src = WALLPAPER_EXPLOIT if self.overtime_start is not None else WALLPAPER
            lay = compute_layout(w, h)
            if self.overtime_start is not None:
                data = make_bg.bake_dark(src, (w, h), fmt="PPM")
            else:
                data = make_bg.bake_glass(src, (w, h), [lay["main"], lay["stats"]],
                                          self._theme_key(), fast=fast, fmt="PPM")
            # PPM 无压缩 + 原始字节直传（免 base64）：tk 解码比 PNG 快一个量级
            self._bg_photo = tk.PhotoImage(data=data.decode("latin-1"))
            self._bg_size = (w, h)
        except Exception:
            return  # 烘焙失败保留旧背景，不影响功能
        self._rerender()
        self._update_display(datetime.now())

    def _reload_fallback_bg(self) -> None:
        """无 Pillow 回退：按主题重载预烘焙背景。"""
        key = self._theme_key()
        bg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "assets", f"bg_{key}.png")
        if os.path.exists(bg_path):
            self._bg_photo = tk.PhotoImage(file=bg_path)
            self._bg_size = (self._bg_photo.width(), self._bg_photo.height())
        else:  # 主题资产缺失：清空旧主题背景走素色兜底，避免跨主题混搭
            self._bg_photo = None

    def _on_canvas_configure(self, event) -> None:
        # ① 圆角区域必须随尺寸立即重设，否则最大化/拖拽后窗口被旧区域裁剪
        self._apply_window_chrome()
        w = max(MIN_WIN_W, event.width)
        h = max(MIN_WIN_H, event.height)
        if (w, h) == (self._win_w, self._win_h):
            return
        # ② 文字布局立即跟随（轻量）；背景：拖动中每 LIVE_BAKE_MS 节流实时烘焙
        #    一次（大窗口自动切快速管线），停稳 150ms 后全质量重烘收尾
        self._win_w, self._win_h = w, h
        self._rerender()
        self._update_display(datetime.now())
        if self._resize_after is not None:
            self.root.after_cancel(self._resize_after)
        now = time.monotonic()
        if (now - self._last_live_bake) * 1000 >= LIVE_BAKE_MS:
            self._last_live_bake = now
            self._rebake_background(fast=True)
        self._resize_after = self.root.after(150, self._after_resize)

    def _after_resize(self) -> None:
        self._resize_after = None
        self._rebake_background()

    def _theme_key(self) -> str:
        """当前主题键（非法值回退 midnight，与 load_config 兕底一致）。"""
        key = self.cfg["theme"]
        return key if key in THEMES else "midnight"

    def _tokens(self) -> dict:
        return THEMES[self._theme_key()]

    def _restyle_menu(self) -> None:
        """菜单栏/子菜单按当前主题换肤（构建后与主题切换时各调一次）。"""
        t = self._tokens()
        for m in (self._menu_bar, self._menu_set, self._theme_menu, self._today_menu):
            if m is not None:
                m.configure(bg=t["menu_bg"], fg=t["menu_fg"],
                            activebackground=t["menu_active_bg"],
                            activeforeground=t["menu_active_fg"],
                            disabledforeground=t["menu_disabled"])

    def _rerender(self) -> None:
        """按当前状态（常规/加班）重建画布内容；主题切换后也走这里。"""
        if self.overtime_start is not None:
            self._render_exploit()
        else:
            self._render_main()

    def _render_main(self) -> None:
        c = self.canvas
        lay = compute_layout(self._win_w, self._win_h)
        f = scale_fonts(self._win_w, self._mono)
        t = self._tokens()
        c.delete("all")
        c.configure(bg=t["dlg_bg"])
        if self._bg_photo is not None:
            c.create_image(0, 0, anchor="nw", image=self._bg_photo)
        else:  # 缺背景资源：素色面板兜底
            for box in (lay["main"], lay["stats"]):
                c.create_rectangle(*box, fill=t["fallback"], outline=t["fallback"])
        # tags 契约：_update_display/_set_status 靠 itemconfigure(tag) 每秒刷新，
        # 这里的 tag 名必须与那两处引用严格一致（缺失 = 静默冻结在初始文本）
        c.create_text(lay["title"], text="时间就是金钱", font=f["title"], fill=t["title"],
                      tags="title")
        c.create_text(lay["today_label"], text="今日已赚（元）",
                      font=f["label"], fill=t["label_ink"], tags="today_label")
        c.create_text(lay["today"], text="0.00", font=f["huge"], fill=t["accent"],
                      tags="today")
        c.create_text(lay["sub"], text="", font=f["sub"], fill=t["label_ink"],
                      tags="sub")
        for i, name in enumerate(("本月已赚（元）", "距发薪", "秒薪（元）")):
            c.create_text((lay["stat_xs"][i], lay["stat_label_y"]), text=name,
                          font=f["small"], fill=t["label_ink"], tags=f"sl{i}")
            c.create_text((lay["stat_xs"][i], lay["stat_value_y"]), text="—",
                          font=f["value"] if i != 1 else f["value_cjk"], fill=t["ink"],
                          tags=f"sv{i}")
        c.create_text(lay["status"], text="", font=f["small"], fill=t["accent"],
                      width=self._win_w - 2 * lay["margin"],  # 长警告换行，防溢出窗口
                      tags="status")

    def _render_exploit(self) -> None:
        c = self.canvas
        w, h = self._win_w, self._win_h
        f = scale_fonts(w, self._mono)
        c.delete("all")
        c.configure(bg=EXPLOIT_BG)
        if self._bg_photo is not None:  # 暗黑壁纸（Dreamy di TikTok）
            c.create_image(0, 0, anchor="nw", image=self._bg_photo)
        c.create_text(w // 2, int(h * 0.30), text="老板在你这里压榨了多少金额",
                      font=f["title"], fill=EXPLOIT_FG, tags="ex_title")
        c.create_text(w // 2, int(h * 0.44), text="0.00", font=f["huge"],
                      fill=EXPLOIT_HIGHLIGHT, tags="ex_amount")
        c.create_text(w // 2, int(h * 0.53), text="元", font=f["app"],
                      fill=EXPLOIT_FG, tags="ex_unit")
        btn = tk.Button(c, text="结束加班", command=self._on_end_overtime,
                        font=f["value"], bg=EXPLOIT_ACCENT, fg="#FFFFFF",
                        activebackground="#D32F2F", activeforeground="#FFFFFF",
                        relief="flat", bd=0, padx=20, pady=7, cursor="hand2")
        self._end_btn = btn  # 防 GC
        c.create_window(w // 2, int(h * 0.66), window=btn)

    # ---------------- 设置弹窗 ----------------

    @staticmethod
    def _make_spin(parent, values: list[str], value: str, t: dict, width: int = 4):
        """只读循环 Spinbox 选择器（时间/天数/日期通用），颜色取主题 token。

        注意：values 选项会在创建时重置 textvariable，
        必须先创建、后绑变量、再回设初值。
        """
        var = tk.StringVar()
        spin = tk.Spinbox(parent, values=values, wrap=True, width=width,
                          state="readonly", font=FONT_APP, justify="center",
                          bg=t["field_bg"], fg=t["field_fg"],
                          insertbackground=t["field_fg"],
                          buttonbackground=t["btn2_bg"], relief="flat",
                          highlightthickness=1, highlightbackground=t["line"],
                          highlightcolor=t["accent"])
        spin.configure(textvariable=var)
        var.set(value)
        return spin, var

    def _time_picker(self, parent, hh: int, mm: int, t: dict):
        """HH:MM 时间选择控件：两个只读 Spinbox（00–23 / 00–59，循环）。"""
        box = tk.Frame(parent, bg=t["dlg_bg"])
        h_spin, hv = self._make_spin(box, [f"{i:02d}" for i in range(24)],
                                     f"{hh:02d}", t, 3)
        h_spin.pack(side="left")
        tk.Label(box, text=" : ", font=("Microsoft YaHei UI", 11, "bold"),
                 bg=t["dlg_bg"], fg=t["sub"]).pack(side="left")
        m_spin, mv = self._make_spin(box, [f"{i:02d}" for i in range(60)],
                                     f"{mm:02d}", t, 3)
        m_spin.pack(side="left")
        return box, hv, mv

    def _build_calendar(self, parent, draft: dict, mode: str) -> tk.Frame:
        """当月日历多选：单击循环 计薪→调休→请假→计薪。草稿写入 draft（原地）。

        fixed 公休格（weekend 模式 = 周末非补班 + 法定节休；free = 空集）
        由 money.fixed_rest_iso 决定，不可点击；两模式各自 draft 互不影响。"""
        import calendar as _cal
        t = self._tokens()
        now = datetime.now()
        y, m = now.year, now.month
        today_iso = now.date().isoformat()
        fixed_iso = money.fixed_rest_iso(y, m, mode)
        weeks = _cal.Calendar(firstweekday=0).monthdayscalendar(y, m)
        frame = tk.Frame(parent, bg=t["dlg_bg"])
        for c, name in enumerate(("一", "二", "三", "四", "五", "六", "日")):
            tk.Label(frame, text=name, font=FONT_APP_SMALL, width=3,
                     bg=t["dlg_bg"], fg=t["sub"]).grid(row=0, column=c)
        painters = []
        state_style = {None: (t["field_bg"], t["ink"]),
                       "调休": (t["btn_bg"], t["btn_fg"]),
                       "请假": (t["err"], "#FFFFFF")}
        for r, week in enumerate(weeks, start=1):
            for c, day in enumerate(week):
                if day == 0:
                    tk.Label(frame, text="", bg=t["dlg_bg"], width=3).grid(row=r, column=c)
                    continue
                iso = f"{y:04d}-{m:02d}-{day:02d}"
                fixed = iso in fixed_iso
                btn = tk.Button(frame, width=3, relief="flat", bd=0, font=FONT_APP_SMALL)

                def paint(b=btn, d=day, iso=iso, fixed=fixed):
                    if fixed:
                        b.configure(text=str(d), bg=t["dlg_bg"], fg=t["menu_disabled"],
                                    highlightthickness=0, state="disabled", cursor="arrow")
                        return
                    bg, fg = state_style.get(draft.get(iso), state_style[None])
                    b.configure(text=str(d), bg=bg, fg=fg, state="normal", cursor="hand2",
                                activebackground=bg, activeforeground=fg,
                                highlightthickness=2 if iso == today_iso else 0,
                                highlightbackground=t["accent"], highlightcolor=t["accent"])

                def click(iso=iso, fixed=fixed):
                    if fixed:
                        return
                    cycle = {None: "调休", "调休": "请假", "请假": None}
                    nxt = cycle.get(draft.get(iso), "调休")
                    if nxt is None:
                        draft.pop(iso, None)
                    else:
                        draft[iso] = nxt
                    for fn in painters:
                        fn()

                btn.configure(command=click)
                btn.grid(row=r, column=c, padx=1, pady=1)
                painters.append(paint)
                paint()
        return frame

    def _rebuild_calendar(self) -> None:
        """按草稿休假模式重建日历：编辑对应模式的 draft，固定格由 money 决定。"""
        for w in self._cal_holder.winfo_children():
            w.destroy()
        mode = self._mode_var.get()
        # 内层 frame 必须显式 grid，否则整历不映射（0 尺寸不可见）
        self._build_calendar(self._cal_holder, self._leaves_draft[mode],
                             mode).grid(padx=2, pady=2)

    def _open_settings(self) -> None:
        dlg = self.settings_dialog
        if dlg is not None and dlg.winfo_exists():
            dlg.deiconify()
            dlg.lift()
            dlg.focus_force()
            return
        dlg = tk.Toplevel(self.root)
        self.settings_dialog = dlg
        dlg.title("设置")
        dlg.resizable(False, False)
        t = self._tokens()  # 弹窗随打开时的当前主题上色
        dlg.configure(bg=t["dlg_bg"])
        dlg.transient(self.root)
        dlg.grab_set()  # 设置弹窗模态；after 循环不受影响（R1 只禁线程）

        form = tk.Frame(dlg, padx=16, pady=10, bg=t["dlg_bg"])
        form.pack()
        form.columnconfigure(1, weight=1)

        def row(r, text):
            lab = tk.Label(form, text=text, font=FONT_APP, anchor="w",
                           bg=t["dlg_bg"], fg=t["ink"])
            lab.grid(row=r, column=0, sticky="w", padx=(0, 10), pady=5)
            return lab

        # 1) 月薪（机密）：默认 • 掩码，勾选「显示」临时查看；留空 = 保持不变
        row(0, "月薪（元/月）")
        salary_cell = tk.Frame(form, bg=t["dlg_bg"])
        salary_cell.grid(row=0, column=1, sticky="w")
        self._salary_var = tk.StringVar(value=str(self.cfg["monthly_salary"]))
        self._salary_entry = tk.Entry(salary_cell, textvariable=self._salary_var,
                                      show="•", font=FONT_APP, width=12,
                                      bg=t["field_bg"], fg=t["field_fg"],
                                      insertbackground=t["field_fg"],
                                      relief="flat", highlightthickness=1,
                                      highlightbackground=t["line"],
                                      highlightcolor=t["accent"])
        self._salary_entry.pack(side="left")
        show_var = tk.BooleanVar(value=False)
        tk.Checkbutton(salary_cell, text="显示", variable=show_var,
                       font=FONT_APP_SMALL, bg=t["dlg_bg"], fg=t["sub"],
                       activebackground=t["dlg_bg"], activeforeground=t["sub"],
                       command=lambda: self._salary_entry.configure(
                           show="" if show_var.get() else "•")).pack(side="left", padx=6)

        # 2) 上下班时间：时间选择控件
        row(1, "上班开始")
        ws_box, self._ws_h, self._ws_m = self._time_picker(
            form, int(self.cfg["work_start"][:2]), int(self.cfg["work_start"][3:]), t)
        ws_box.grid(row=1, column=1, sticky="w")
        row(2, "上班结束")
        we_box, self._we_h, self._we_m = self._time_picker(
            form, int(self.cfg["work_end"][:2]), int(self.cfg["work_end"][3:]), t)
        we_box.grid(row=2, column=1, sticky="w")

        # 3) 休假模式：固定周末公休（默认）/ 自由假期
        row(3, "休假方式")
        mode_cell = tk.Frame(form, bg=t["dlg_bg"])
        mode_cell.grid(row=3, column=1, sticky="w")
        self._mode_var = tk.StringVar(value=self.cfg["holiday_mode"])
        for key in ("weekend", "free"):
            tk.Radiobutton(mode_cell, text=MODE_LABELS[key], value=key,
                           variable=self._mode_var, font=FONT_APP,
                           bg=t["dlg_bg"], fg=t["ink"], activebackground=t["dlg_bg"],
                           activeforeground=t["ink"],
                           command=self._on_mode_change).pack(side="left", padx=(0, 10))

        # 4) 当月休假：日历多选（单击循环 计薪→调休→请假；草稿制，保存才生效；
        #    分模式草稿，两模式标记互不影响）
        raw_leaves = self.cfg.get("leaves", {})
        self._leaves_draft = {
            m: dict(raw_leaves.get(m, {})) if isinstance(raw_leaves.get(m), dict) else {}
            for m in ("weekend", "free")}
        self._cal_holder = tk.Frame(form, bg=t["dlg_bg"])
        self._cal_holder.grid(row=4, column=0, columnspan=2, pady=(2, 6))

        # 5) 发薪日
        row(5, "发薪日（1–31）")
        pay_spin, self._pay_var = self._make_spin(form, [str(i) for i in range(1, 32)],
                                                  str(self.cfg["payday"]), t)
        pay_spin.grid(row=5, column=1, sticky="w")

        self._on_mode_change()  # 校正日历禁用格（随草稿休假模式）

        # 弹窗为临时窗体：不进主窗口画布体系（销毁后重绘会碰死控件），
        # 打开时按当前主题 token 静态上色
        tk.Button(form, text="保存设置", command=lambda: self._on_save(dlg),
                  font=("Microsoft YaHei UI", 12, "bold"), bd=0, padx=18, pady=6, cursor="hand2",
                  bg=t["btn_bg"], fg=t["btn_fg"], activebackground=t["btn_active"],
                  activeforeground=t["btn_fg"], relief="flat") \
            .grid(row=6, column=0, columnspan=2, pady=(12, 2))
        dlg_status = tk.Label(dlg, text="", font=FONT_APP_SMALL, fg=t["err"],
                              bg=t["dlg_bg"])
        dlg_status.pack(pady=(0, 8))
        self._dlg_status = dlg_status

        dlg.update_idletasks()
        x = self.root.winfo_x() + max(0, (self.root.winfo_width() - dlg.winfo_width()) // 2)
        y = self.root.winfo_y() + max(0, (self.root.winfo_height() - dlg.winfo_height()) // 3)
        dlg.geometry(f"+{x}+{y}")

    def _on_mode_change(self) -> None:
        self._rebuild_calendar()

    def _on_save(self, dlg: tk.Toplevel) -> None:
        raw = self._salary_var.get().strip()
        try:
            if raw == "":
                salary = self.cfg["monthly_salary"]  # 掩码保护：留空保持原值
            else:
                salary = float(raw)
                if not math.isfinite(salary):
                    raise ValueError
            ws = f"{int(self._ws_h.get()):02d}:{int(self._ws_m.get()):02d}"
            we = f"{int(self._we_h.get()):02d}:{int(self._we_m.get()):02d}"
            payday = int(self._pay_var.get())
        except ValueError:
            self._dlg_status.configure(text="保存失败：请检查月薪与各项数值")
            return
        mode = self._mode_var.get()
        prefix = datetime.now().strftime("%Y-%m-")
        # 两模式草稿都做当月过滤写回（未编辑模式原样保留），互不覆盖
        leaves = {m: {k: v for k, v in self._leaves_draft.get(m, {}).items()
                      if isinstance(k, str) and k.startswith(prefix)}
                  for m in ("weekend", "free")}
        errors = money.validate(salary, ws, we, leaves[mode], payday, mode)
        if errors:
            self._dlg_status.configure(text="保存失败：" + "；".join(errors))
            return
        candidate = {**self.cfg, "monthly_salary": salary, "work_start": ws,
                     "work_end": we, "holiday_mode": mode, "leaves": leaves,
                     "payday": payday}
        if not save_config(candidate):  # 先落盘，成功才提交内存（修复 A）
            self._dlg_status.configure(text="保存失败：config.json 写入失败")
            return
        self.cfg.update(candidate)
        self.configured = True
        self._refresh_month_cache(datetime.now())
        self._update_today_menu()
        self._set_status("已保存")
        self._update_display(datetime.now())
        dlg.destroy()

    # ---------------- 主题 ----------------

    def _on_theme_change(self) -> None:
        key = self.theme_var.get()
        if key not in THEMES:
            return
        self.cfg["theme"] = key
        if not save_config(self.cfg):  # 主题即时持久化
            self._set_status("警告：config.json 写入失败，主题未持久化", clear_ms=0)
        self._restyle_menu()  # 菜单栏跟随新主题
        if self.overtime_start is None:
            if self._can_resize_bg:
                self._rebake_background()  # 材质随主题变，按主题重烘焙（内部含重绘+刷新）
            else:
                self._reload_fallback_bg()
                self._render_main()
                self._update_display(datetime.now())

    # ---------------- 每秒 tick ----------------

    def _tick(self) -> None:
        try:
            self._tick_once()
        except Exception:
            pass  # A11/R5：单次 tick 异常兜底，不终止刷新循环
        self.root.after(TICK_MS, self._tick)

    def _tick_once(self) -> None:
        now = datetime.now()
        if now.date() != self.cached_date:  # 跨日/跨月检测
            self._on_date_rollover(now)
        self._update_display(now)
        self._check_off_work(now)

    def _on_date_rollover(self, now: datetime) -> None:
        self.cached_date = now.date()
        self._refresh_month_cache(now)       # 跨月重算秒薪等月度派生值
        self._update_today_menu()            # 跨日刷新「取消标记」可用态
        self._close_ask_dialog()             # 重置当日询问内存态

    def _refresh_month_cache(self, now: datetime) -> None:
        # leaves 两模式各自只保留当月标记，跨月自动清零；秒薪/日薪按当前模式整月重算
        prefix = f"{now.year:04d}-{now.month:02d}-"
        self.cfg["leaves"] = {
            m: {k: v for k, v in self.cfg["leaves"].get(m, {}).items()
                if isinstance(k, str) and k.startswith(prefix)}
            for m in ("weekend", "free")}
        mode = self.cfg["holiday_mode"]
        active = self.cfg["leaves"].get(mode, {})
        self.pss = money.per_second_salary(
            self.cfg["monthly_salary"], now.year, now.month, active,
            self.cfg["work_start"], self.cfg["work_end"], mode)
        self.daily = money.daily_salary(
            self.cfg["monthly_salary"], now.year, now.month, active,
            self.cfg["work_start"], self.cfg["work_end"], mode)

    def _is_workday(self, d) -> bool:
        return money.is_workday(d, self.cfg["leaves"].get(self.cfg["holiday_mode"], {}),
                                self.cfg["holiday_mode"])

    def _update_display(self, now: datetime) -> None:
        cfg = self.cfg
        ic = self.canvas.itemconfigure
        if self.overtime_start is not None:  # 压榨画布：只更新金额（tag 连描边一并更新）
            amount = money.exploited_amount(self.pss, now, cfg["work_end"],
                                            self.overtime_start)
            ic("ex_amount", text=f"{amount:,.2f}")
            return
        if not self.configured:  # 未配置不渲染默认金额，显示引导占位
            ic("today", text="请先通过顶部菜单「设置」完成设置并保存",
               font=("Microsoft YaHei UI", 12, "bold"))
            for k in ("sub", "sv0", "sv1", "sv2"):
                ic(k, text="—" if k.startswith("sv") else "")
            return
        ic("today", font=scale_fonts(self._win_w, self._mono)["huge"])  # 从占位态恢复大字号
        ws, we = cfg["work_start"], cfg["work_end"]
        mode = cfg["holiday_mode"]
        leaves = cfg["leaves"].get(mode, {})
        ic("today",
           text=f"{money.earned_today(self.pss, now, ws, we, leaves, mode):,.2f}")
        today_type = leaves.get(now.date().isoformat())
        if today_type == "请假":
            sub_text = f"请假中 · 今天没了 {self.daily:,.2f} 元"
        elif today_type == "调休":
            sub_text = "调休中 · 今日不计薪，秒薪已上调"
        else:
            sub_text = self._off_work_text(now, we)
        ic("sub", text=sub_text)
        month_earned = money.earned_this_month(self.pss, now, ws, we, leaves, mode)
        ic("sv0", text=f"{month_earned:,.2f}")
        ic("sv2", text=f"{self.pss:.4f}")
        days = money.days_until_payday(now.date(), cfg["payday"])
        ic("sv1", text="今天发薪" if days == 0 else f"{days} 天")

    def _off_work_text(self, now: datetime, end_hm: str) -> str:
        if not self._is_workday(now.date()):
            return "休息日"
        if self.overtime_start is not None:
            return "加班中"
        end_sec = money.daily_work_seconds("00:00", end_hm)
        now_sec = now.hour * 3600 + now.minute * 60 + now.second
        if now_sec >= end_sec:
            return "已下班"
        h, rem = divmod(end_sec - now_sec, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    # ---------------- 下班检测 / 询问弹窗（A7 / A9 / R1 / R7）----------------

    def _check_off_work(self, now: datetime) -> None:
        if self.overtime_start is not None or self.ask_dialog is not None:
            return  # 加班中不重复触发；弹窗未关闭前不重复弹
        if not self._is_workday(now.date()):
            return
        end_sec = money.daily_work_seconds("00:00", self.cfg["work_end"])
        now_sec = now.hour * 3600 + now.minute * 60 + now.second
        if now_sec < end_sec:
            return
        if self.cfg.get("last_asked_date") == now.date().isoformat():  # A9 去重
            return
        self._mark_asked(now)  # 打开即落盘，保证跨重启当日只问一次
        self._play_alert()
        self._open_ask_dialog()

    def _mark_asked(self, now: datetime | None = None) -> None:
        today_str = (now or datetime.now()).date().isoformat()
        if self.cfg.get("last_asked_date") != today_str:
            self.cfg["last_asked_date"] = today_str
            if not save_config(self.cfg):
                self._set_status("警告：config.json 写入失败", clear_ms=0)

    def _play_alert(self) -> None:
        try:
            winsound.PlaySound("SystemExclamation", winsound.SND_ASYNC)  # 异步，R1
        except Exception:
            try:
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)  # 系统级回退
            except Exception:
                pass

    def _open_ask_dialog(self) -> None:
        t = self._tokens()
        dlg = tk.Toplevel(self.root)
        self.ask_dialog = dlg
        dlg.title("下班提醒")
        dlg.resizable(False, False)
        dlg.configure(bg=t["dlg_bg"])
        dlg.transient(self.root)  # 仅窗口归属，不 grab：保持非模态，tick 不停（R1）
        dlg.protocol("WM_DELETE_WINDOW", self._on_ask_dismissed)

        msg = tk.Label(dlg, text="到点啦，今天加班吗？", font=("Microsoft YaHei UI", 14, "bold"),
                       bg=t["dlg_bg"], fg=t["ink"], padx=28, pady=18)
        msg.pack()
        btns = tk.Frame(dlg, bg=t["dlg_bg"])
        btns.pack(pady=(0, 20), padx=24)
        yes = tk.Button(btns, text="加班", font=("Microsoft YaHei UI", 12, "bold"), bd=0, padx=22,
                        pady=6, cursor="hand2", relief="flat",
                        bg=t["btn_bg"], fg=t["btn_fg"], activebackground=t["btn_active"],
                        activeforeground=t["btn_fg"],
                        command=self._on_accept_overtime)
        no = tk.Button(btns, text="不加班", font=("Microsoft YaHei UI", 12, "bold"), bd=0, padx=22,
                       pady=6, cursor="hand2", relief="flat",
                       bg=t["btn2_bg"], fg=t["btn2_fg"], activebackground=t["btn2_bg"],
                       activeforeground=t["btn2_fg"],
                       command=self._on_ask_dismissed)
        yes.pack(side="left", padx=8)
        no.pack(side="left", padx=8)
        self.root.update_idletasks()
        x = self.root.winfo_x() + max(0, (self.root.winfo_width() - 320) // 2)
        y = self.root.winfo_y() + max(0, (self.root.winfo_height() - 180) // 3)
        dlg.geometry(f"+{x}+{y}")

    def _close_ask_dialog(self) -> None:
        dlg, self.ask_dialog = self.ask_dialog, None
        if dlg is not None and dlg.winfo_exists():
            dlg.destroy()

    def _on_ask_dismissed(self) -> None:
        self._mark_asked()       # 不加班 & 直接关窗均视为已答复
        self._close_ask_dialog()

    # ---------------- 加班（暗黑压榨）模式（A8）----------------

    def _on_accept_overtime(self) -> None:
        self._mark_asked()
        self._close_ask_dialog()
        if self.overtime_start is None:
            self.overtime_start = datetime.now()  # A8 origin = max(当日下班, 激活时刻)
        self._rebake_background()  # 切到暗黑壁纸 + 压榨画布
        self._update_display(datetime.now())

    def _on_end_overtime(self) -> None:
        self.overtime_start = None  # 停止累计；exploit 为临时强制态
        self._rebake_background()  # 切回主壁纸玻璃画布
        self._update_display(datetime.now())

    # ---------------- 状态条 ----------------

    def _set_status(self, text: str, clear_ms: int = 3000) -> None:
        """状态行提示：默认 3 秒后自动消失；clear_ms=0 常驻（警告类）直到被替换。"""
        if self.overtime_start is not None:  # 加班画布无状态行，静默跳过
            return
        if self._status_after is not None:
            self.root.after_cancel(self._status_after)
            self._status_after = None
        self.canvas.itemconfigure("status", text=text)
        if clear_ms:
            self._status_after = self.root.after(clear_ms, self._clear_status)

    def _clear_status(self) -> None:
        self._status_after = None
        self.canvas.itemconfigure("status", text="")


def _acquire_single_instance_lock() -> bool:
    """命名互斥体防多开：多实例并发写 config.json 会互相覆盖，且重复窗口
    易被误认为「程序不运行」。句柄不关，进程存活期间始终持有。"""
    try:
        ERROR_ALREADY_EXISTS = 183
        ctypes.windll.kernel32.CreateMutexW(None, False,
                                           "time_is_money_single_instance")
        return ctypes.windll.kernel32.GetLastError() != ERROR_ALREADY_EXISTS
    except Exception:
        return True  # 检测失败不阻断使用


def main() -> None:
    if not _acquire_single_instance_lock():
        root = tk.Tk()
        root.withdraw()
        tk.messagebox.showinfo(
            "时间就是金钱", "已经在运行了，请查看任务栏中的窗口。")
        return
    root = tk.Tk()
    PayClockApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
