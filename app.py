"""app.py — time_is_money 打工人实时薪资钟 tkinter UI（v4 玻璃拟态 · 可缩放）。

- 视觉：壁纸背景 + 毛玻璃面板（苹果玻璃卡片质感）。窗口默认 348×452，可任意
  拖拽缩放：尺寸变化时即时重排文字/重设圆角区域，停稳后（150ms 防抖）用
  Pillow 按新尺寸重烘焙背景；未安装 Pillow 时回退固定尺寸 + 预生成背景
  （assets/bg_<theme>.png）。
  全部文字不带描边，可读性由烘焙层（渐晕/面板材质）保证；
- 月薪为机密：设置弹窗中默认以 • 掩码显示，可勾选「显示」临时查看；
- 上班开始/结束用 Spinbox 时间选择控件（只读+循环滚动），非手输框；
- 休假两种模式：weekend=固定周末公休+每月额外假期；free=自由假期（当月任选 N 天，
  周末照常上班，通过顶部菜单「标记今天休息」逐日标记）；
- 主界面聚焦实时收入：今日已赚超大字号居中；设置收进顶部菜单栏（苹果风）；
- 三套主题（midnight/paper/glass）共享一套冰蓝强调色 token 表；主数字等宽字体；
  加班期切暗黑壁纸（模糊压暗 + 红字）；单实例互斥体防多开。

约束沿袭：单窗口单线程，全部刷新由 root.after(1000) 单循环驱动（R1）；
每 tick 用真实当前时刻重算（A10/R2）；tick 异常兜底（A11/R5）；公式一律调 money 纯函数；
config.json 固定位于本脚本目录、与 CWD 无关（A12）。
"""

import base64
import ctypes
import ctypes.wintypes
import json
import math
import os
import tkinter as tk
import tkinter.font as tkfont
import tkinter.messagebox
import winsound
from datetime import datetime

import money

# config schema 默认值（缺失 config 时进设置弹窗待保存）；旧版 config 自动补新字段
DEFAULT_CONFIG = {
    "monthly_salary": 10000.0,
    "work_start": "09:00",
    "work_end": "18:00",
    "holiday_mode": "weekend",  # weekend=固定周末公休 | free=自由假期
    "monthly_holidays": 2,
    "free_holidays": [],        # free 模式：当月已标记休息的 ISO 日期列表
    "payday": 15,
    "theme": "midnight",
    "last_asked_date": "",
}

CONFIG_FILENAME = "config.json"
TICK_MS = 1000

# ---- 窗口与布局 ----
# 默认尺寸为旧版 520×680 的 2/3；窗口可任意拖拽缩放，背景毛玻璃随尺寸实时重烘焙
# （需 Pillow，未安装时回退固定尺寸 + 预生成 assets/bg.png）。布局全部按比例计算。
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

INK = "#1D1D1F"                  # 主文字（苹果深灰墨色）
LABEL_INK = "#3F3F46"            # 标签文字（玻璃透明后需更深才可读）
SUB = "#6E6E73"                  # 次要文字
DLG_BG = "#F5F5F7"               # 弹窗/菜单底色（苹果浅灰）
LINE = "#D2D2D7"                 # 输入框描边
BLUE = "#0A84FF"                 # 系统蓝（主按钮/菜单高亮）
MENU_DISABLED = "#B0B0B5"        # 菜单禁用项文字色
GLASS_FALLBACK = "#F7F8FA"       # 缺背景资源时的面板兜底色
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
        if not isinstance(loaded["free_holidays"], list):
            raise ValueError("bad free_holidays")
        if money.validate(loaded["monthly_salary"], loaded["work_start"],
                          loaded["work_end"], loaded["monthly_holidays"],
                          loaded["payday"], loaded["holiday_mode"]):
            raise ValueError("config fields failed money.validate")
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
        self._rgn_size = (0, 0)        # 已应用圆角区域对应的窗口尺寸
        self._can_resize_bg = False    # Pillow 可用时才开任意缩放（构建 UI 前探测）
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
            self._set_status(load_warning)
        self.root.after(TICK_MS, self._tick)

    # ---------------- 顶部菜单栏（苹果风：拍平到顶栏，浅灰底/蓝色高亮）----------------

    def _build_menu(self) -> None:
        menu_font = ("Microsoft YaHei UI", 10)
        t = self._tokens()  # 菜单静态上色（主题切换时的换肤在 _restyle_menu，任务 4）

        def apple_menu(master):
            """苹果风菜单：token 取色、去内边框。"""
            return tk.Menu(master, tearoff=0, bg=t["menu_bg"], fg=t["menu_fg"], font=menu_font,
                           activebackground=t["menu_active_bg"],
                           activeforeground=t["menu_active_fg"],
                           activeborderwidth=0, bd=0, relief="flat",
                           disabledforeground=t["menu_disabled"])

        menubar = apple_menu(self.root)
        m_set = apple_menu(menubar)
        m_set.add_command(label="设置…", command=self._open_settings)
        menubar.add_cascade(label="设置", menu=m_set)

        m_theme = apple_menu(menubar)
        self.theme_var = tk.StringVar(
            value=self.cfg["theme"] if self.cfg["theme"] in THEMES else "midnight")
        for key in THEMES:
            m_theme.add_radiobutton(label=THEMES[key]["label"], value=key,
                                    variable=self.theme_var,
                                    command=self._on_theme_change)
        menubar.add_cascade(label="主题", menu=m_theme)
        self._theme_menu = m_theme
        self._menu_set = m_set

        # 「标记今天休息」直接平移到顶栏，点击即切换（仅 free 模式可用）
        menubar.add_command(label="标记今天休息",
                            command=self._toggle_today_holiday)
        self._holiday_idx = menubar.index("end")
        self._menu_bar = menubar
        self.root.configure(menu=menubar)
        self._update_holiday_menu()

    def _update_holiday_menu(self) -> None:
        """free 模式才可用「标记今天休息」，并按当日标记状态切换文案。"""
        free_mode = self.cfg["holiday_mode"] == "free"
        self._menu_bar.entryconfig(self._holiday_idx,
                                   state="normal" if free_mode else "disabled")
        if free_mode:
            today_iso = datetime.now().date().isoformat()
            marked = today_iso in self.cfg["free_holidays"]
            self._menu_bar.entryconfig(
                self._holiday_idx,
                label="取消今天休息" if marked else "标记今天休息")

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

    def _toggle_today_holiday(self) -> None:
        if self.cfg["holiday_mode"] != "free":
            return
        today_iso = datetime.now().date().isoformat()
        holidays = list(self.cfg["free_holidays"])
        if today_iso in holidays:
            holidays.remove(today_iso)
            self._set_status("已取消今天的休息标记")
        else:
            holidays.append(today_iso)
            self._set_status("已标记今天休息（今日不计薪）")
        candidate = {**self.cfg, "free_holidays": holidays}
        if not save_config(candidate):
            self._set_status("警告：config.json 写入失败")
            return
        self.cfg.update(candidate)
        self._refresh_month_cache(datetime.now())
        self._update_holiday_menu()
        self._update_display(datetime.now())

    # ---------------- 界面构建（Canvas + 实时烘焙玻璃背景，可任意缩放）----------------

    def _build_ui(self) -> None:
        self.root.title("时间就是金钱 · 实时薪资钟")
        self.root.geometry(f"{DEFAULT_WIN_W}x{DEFAULT_WIN_H}")
        self.root.minsize(MIN_WIN_W, MIN_WIN_H)

        self.canvas = tk.Canvas(self.root, width=DEFAULT_WIN_W,
                                height=DEFAULT_WIN_H, bg=DLG_BG,
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

    def _rebake_background(self) -> None:
        """按当前窗口尺寸烘焙背景（主壁纸/加班壁纸随模式切换），后重绘内容。"""
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
                data = make_bg.bake_dark(src, (w, h))
            else:
                data = make_bg.bake_glass(src, (w, h), [lay["main"], lay["stats"]],
                                          self.cfg["theme"] if self.cfg["theme"] in THEMES else "midnight")
            self._bg_photo = tk.PhotoImage(data=base64.b64encode(data))
            self._bg_size = (w, h)
        except Exception:
            return  # 烘焙失败保留旧背景，不影响功能
        self._rerender()
        self._update_display(datetime.now())

    def _reload_fallback_bg(self) -> None:
        """无 Pillow 回退：按主题重载预烘焙背景。"""
        key = self.cfg["theme"] if self.cfg["theme"] in THEMES else "midnight"
        bg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "assets", f"bg_{key}.png")
        if os.path.exists(bg_path):
            self._bg_photo = tk.PhotoImage(file=bg_path)
            self._bg_size = (self._bg_photo.width(), self._bg_photo.height())

    def _on_canvas_configure(self, event) -> None:
        # ① 圆角区域必须随尺寸立即重设，否则最大化/拖拽后窗口被旧区域裁剪
        self._apply_window_chrome()
        w = max(MIN_WIN_W, event.width)
        h = max(MIN_WIN_H, event.height)
        if (w, h) == (self._win_w, self._win_h):
            return
        # ② 文字布局立即跟随（轻量），背景重烘焙防抖后执行（重量）
        self._win_w, self._win_h = w, h
        self._rerender()
        self._update_display(datetime.now())
        if (event.width, event.height) == self._bg_size:
            return
        if self._resize_after is not None:
            self.root.after_cancel(self._resize_after)
        self._resize_after = self.root.after(150, self._after_resize)

    def _after_resize(self) -> None:
        self._resize_after = None
        self._rebake_background()

    def _tokens(self) -> dict:
        key = self.cfg["theme"] if self.cfg["theme"] in THEMES else "midnight"
        return THEMES[key]

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
        c.create_text(lay["title"], text="时间就是金钱", font=f["title"], fill=t["title"])
        c.create_text(lay["today_label"], text="今日已赚（元）",
                      font=f["label"], fill=t["label_ink"])
        c.create_text(lay["today"], text="0.00", font=f["huge"], fill=t["accent"])
        c.create_text(lay["sub"], text="", font=f["sub"], fill=t["label_ink"])
        for i, name in enumerate(("本月已赚（元）", "距发薪", "秒薪（元）")):
            c.create_text((lay["stat_xs"][i], lay["stat_label_y"]), text=name,
                          font=f["small"], fill=t["label_ink"])
            c.create_text((lay["stat_xs"][i], lay["stat_value_y"]), text="—",
                          font=f["value"] if i != 1 else f["value_cjk"], fill=t["ink"])
        c.create_text(lay["status"], text="", font=f["small"], fill=t["accent"],
                      width=self._win_w - 2 * lay["margin"])  # 长警告换行，防溢出窗口

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
    def _make_spin(parent, values: list[str], value: str, width: int = 4):
        """只读循环 Spinbox 选择器（时间/天数/日期通用）。

        注意：values 选项会在创建时重置 textvariable，
        必须先创建、后绑变量、再回设初值。
        """
        var = tk.StringVar()
        spin = tk.Spinbox(parent, values=values, wrap=True, width=width,
                          state="readonly", font=FONT_APP, justify="center",
                          bg="#FFFFFF", fg=INK, insertbackground=INK,
                          buttonbackground="#E9E9EB", relief="flat",
                          highlightthickness=1, highlightbackground=LINE,
                          highlightcolor=BLUE)
        spin.configure(textvariable=var)
        var.set(value)
        return spin, var

    def _time_picker(self, parent, hh: int, mm: int, bg: str = DLG_BG):
        """HH:MM 时间选择控件：两个只读 Spinbox（00–23 / 00–59，循环）。"""
        box = tk.Frame(parent, bg=bg)
        h_spin, hv = self._make_spin(box, [f"{i:02d}" for i in range(24)],
                                     f"{hh:02d}", 3)
        h_spin.pack(side="left")
        tk.Label(box, text=" : ", font=("Microsoft YaHei UI", 11, "bold"), bg=bg, fg=SUB).pack(side="left")
        m_spin, mv = self._make_spin(box, [f"{i:02d}" for i in range(60)],
                                     f"{mm:02d}", 3)
        m_spin.pack(side="left")
        return box, hv, mv

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
        dlg.configure(bg=DLG_BG)
        dlg.transient(self.root)
        dlg.grab_set()  # 设置弹窗模态；after 循环不受影响（R1 只禁线程）

        form = tk.Frame(dlg, padx=16, pady=10, bg=DLG_BG)
        form.pack()
        form.columnconfigure(1, weight=1)

        def row(r, text):
            lab = tk.Label(form, text=text, font=FONT_APP, anchor="w",
                           bg=DLG_BG, fg=INK)
            lab.grid(row=r, column=0, sticky="w", padx=(0, 10), pady=5)
            return lab

        # 1) 月薪（机密）：默认 • 掩码，勾选「显示」临时查看；留空 = 保持不变
        row(0, "月薪（元/月）")
        salary_cell = tk.Frame(form, bg=DLG_BG)
        salary_cell.grid(row=0, column=1, sticky="w")
        self._salary_var = tk.StringVar(value=str(self.cfg["monthly_salary"]))
        self._salary_entry = tk.Entry(salary_cell, textvariable=self._salary_var,
                                      show="•", font=FONT_APP, width=12,
                                      bg="#FFFFFF", fg=INK, insertbackground=INK,
                                      relief="flat", highlightthickness=1,
                                      highlightbackground=LINE, highlightcolor=BLUE)
        self._salary_entry.pack(side="left")
        show_var = tk.BooleanVar(value=False)
        tk.Checkbutton(salary_cell, text="显示", variable=show_var,
                       font=FONT_APP_SMALL, bg=DLG_BG, fg=SUB,
                       activebackground=DLG_BG, activeforeground=SUB,
                       command=lambda: self._salary_entry.configure(
                           show="" if show_var.get() else "•")).pack(side="left", padx=6)

        # 2) 上下班时间：时间选择控件
        row(1, "上班开始")
        ws_box, self._ws_h, self._ws_m = self._time_picker(
            form, int(self.cfg["work_start"][:2]), int(self.cfg["work_start"][3:]))
        ws_box.grid(row=1, column=1, sticky="w")
        row(2, "上班结束")
        we_box, self._we_h, self._we_m = self._time_picker(
            form, int(self.cfg["work_end"][:2]), int(self.cfg["work_end"][3:]))
        we_box.grid(row=2, column=1, sticky="w")

        # 3) 休假模式：固定周末公休（默认）/ 自由假期
        row(3, "休假方式")
        mode_cell = tk.Frame(form, bg=DLG_BG)
        mode_cell.grid(row=3, column=1, sticky="w")
        self._mode_var = tk.StringVar(value=self.cfg["holiday_mode"])
        for key in ("weekend", "free"):
            tk.Radiobutton(mode_cell, text=MODE_LABELS[key], value=key,
                           variable=self._mode_var, font=FONT_APP,
                           bg=DLG_BG, fg=INK, activebackground=DLG_BG,
                           activeforeground=INK,
                           command=self._on_mode_change).pack(side="left", padx=(0, 10))

        # 4) 每月假期天数（含义随模式）
        self._hol_label = row(4, "额外假期（天/月）")
        hol_spin, self._hol_var = self._make_spin(form, [str(i) for i in range(29)],
                                                  str(self.cfg["monthly_holidays"]))
        hol_spin.grid(row=4, column=1, sticky="w")

        # 5) 发薪日
        row(5, "发薪日（1–31）")
        pay_spin, self._pay_var = self._make_spin(form, [str(i) for i in range(1, 32)],
                                                  str(self.cfg["payday"]))
        pay_spin.grid(row=5, column=1, sticky="w")

        self._on_mode_change()  # 按当前模式校正假期行文案

        # 弹窗为临时窗体：不进主窗口画布体系（销毁后重绘会碰死控件），
        # 创建时按系统蓝静态上色
        tk.Button(form, text="保存设置", command=lambda: self._on_save(dlg),
                  font=("Microsoft YaHei UI", 12, "bold"), bd=0, padx=18, pady=6, cursor="hand2",
                  bg=BLUE, fg="#FFFFFF", activebackground="#3395FF",
                  activeforeground="#FFFFFF", relief="flat") \
            .grid(row=6, column=0, columnspan=2, pady=(12, 2))
        dlg_status = tk.Label(dlg, text="", font=FONT_APP_SMALL, fg="#E02D2D",
                              bg=DLG_BG)
        dlg_status.pack(pady=(0, 8))
        self._dlg_status = dlg_status

        dlg.update_idletasks()
        x = self.root.winfo_x() + max(0, (self.root.winfo_width() - dlg.winfo_width()) // 2)
        y = self.root.winfo_y() + max(0, (self.root.winfo_height() - dlg.winfo_height()) // 3)
        dlg.geometry(f"+{x}+{y}")

    def _on_mode_change(self) -> None:
        self._hol_label.configure(
            text="自由假期（天/月，用菜单逐日标记）"
            if self._mode_var.get() == "free" else "周末外额外假期（天/月）")

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
            holidays = int(self._hol_var.get())
            payday = int(self._pay_var.get())
        except ValueError:
            self._dlg_status.configure(text="保存失败：请检查月薪与各项数值")
            return
        mode = self._mode_var.get()
        errors = money.validate(salary, ws, we, holidays, payday, mode)
        if errors:
            self._dlg_status.configure(text="保存失败：" + "；".join(errors))
            return
        candidate = {**self.cfg, "monthly_salary": salary, "work_start": ws,
                     "work_end": we, "holiday_mode": mode,
                     "monthly_holidays": holidays, "payday": payday}
        if not save_config(candidate):  # 先落盘，成功才提交内存（修复 A）
            self._dlg_status.configure(text="保存失败：config.json 写入失败")
            return
        self.cfg.update(candidate)
        self.configured = True
        self._refresh_month_cache(datetime.now())
        self._update_holiday_menu()
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
            self._set_status("警告：config.json 写入失败，主题未持久化")
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
        self._update_holiday_menu()          # 跨日刷新「标记今天休息」文案
        self._close_ask_dialog()             # 重置当日询问内存态

    def _refresh_month_cache(self, now: datetime) -> None:
        # free_holidays 只保留当月标记，跨月自动清零
        prefix = f"{now.year:04d}-{now.month:02d}"
        self.cfg["free_holidays"] = [d for d in self.cfg["free_holidays"]
                                     if isinstance(d, str) and d.startswith(prefix)]
        self.pss = money.per_second_salary(
            self.cfg["monthly_salary"], now.year, now.month,
            self.cfg["monthly_holidays"], self.cfg["work_start"], self.cfg["work_end"],
            self.cfg["holiday_mode"])

    def _free_set(self) -> frozenset:
        return frozenset(self.cfg["free_holidays"])

    def _is_workday(self, d) -> bool:
        return money.is_workday(d, self._free_set(), self.cfg["holiday_mode"])

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
        fset, mode = self._free_set(), cfg["holiday_mode"]
        ic("today",
           text=f"{money.earned_today(self.pss, now, ws, we, fset, mode):,.2f}")
        ic("sub", text=self._off_work_text(now, we))
        month_earned = money.earned_this_month(self.pss, now, ws, we, fset, mode)
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
                self._set_status("警告：config.json 写入失败")

    def _play_alert(self) -> None:
        try:
            winsound.PlaySound("SystemExclamation", winsound.SND_ASYNC)  # 异步，R1
        except Exception:
            try:
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)  # 系统级回退
            except Exception:
                pass

    def _open_ask_dialog(self) -> None:
        dlg = tk.Toplevel(self.root)
        self.ask_dialog = dlg
        dlg.title("下班提醒")
        dlg.resizable(False, False)
        dlg.configure(bg="#FFFFFF")
        dlg.transient(self.root)  # 仅窗口归属，不 grab：保持非模态，tick 不停（R1）
        dlg.protocol("WM_DELETE_WINDOW", self._on_ask_dismissed)

        msg = tk.Label(dlg, text="到点啦，今天加班吗？", font=("Microsoft YaHei UI", 14, "bold"),
                       bg="#FFFFFF", fg=INK, padx=28, pady=18)
        msg.pack()
        btns = tk.Frame(dlg, bg="#FFFFFF")
        btns.pack(pady=(0, 20), padx=24)
        yes = tk.Button(btns, text="加班", font=("Microsoft YaHei UI", 12, "bold"), bd=0, padx=22,
                        pady=6, cursor="hand2", relief="flat",
                        bg=BLUE, fg="#FFFFFF", activebackground="#3395FF",
                        activeforeground="#FFFFFF",
                        command=self._on_accept_overtime)
        no = tk.Button(btns, text="不加班", font=("Microsoft YaHei UI", 12, "bold"), bd=0, padx=22,
                       pady=6, cursor="hand2", relief="flat",
                       bg="#E9E9EB", fg=INK, activebackground="#DCDCE0",
                       activeforeground=INK,
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

    def _set_status(self, text: str) -> None:
        if self.overtime_start is None:  # 加班画布无状态行，静默跳过
            self.canvas.itemconfigure("status", text=text)


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
