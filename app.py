"""app.py — time_is_money 打工人实时薪资钟 tkinter UI（v5 极简数显 · 方向A）。

- 视觉：纯色渐变底（无壁纸、无烘焙面板），Canvas 全绘制。标题行：日期状态（左）
  + ◐ 主题切换 / ⚙ 设置图标（右），主区超大等宽数字（整数/小数分字号），
  今日进度条把上班时间流逝可视化，底部三栏统计 + 细分隔线；
- 双主题：dark 暗夜极简（默认）/ light 清晨亮色，共享一套布局与组件结构；
  加班期切换红色警报调色板（压榨金额 + 加班时长条 + 结束加班按钮）；
- 无 Pillow 依赖：窗口任意拖拽缩放，布局按比例即时重排，渐变底逐帧重画；
  窗口圆角经 SetWindowRgn 裁剪（Win10/11 均可用）；
- 操作入口：⚙ 打开设置弹窗，◐ 切换主题，右键菜单含 主题 / 标记今天 / 设置；
- 月薪为机密：设置弹窗中默认以 • 掩码显示，可勾选「显示」临时查看；
- 休假两种模式：weekend=固定周末公休；free=周末照常上班。两种模式均可用
  设置日历或右键菜单「标记今天」按日标记调休/请假（调休重算秒薪，请假扣日薪）；
- 上班开始/结束用 Spinbox 时间选择控件（只读+循环滚动），非手输框；
- 单实例互斥体防多开；
- DPI 感知（SetProcessDpiAwareness）：125%/150% 系统缩放下按物理像素渲染，
  不再被 DWM 位图拉伸发虚；窗口尺寸/圆角按 scale 放大，字号按逻辑宽度取 pt，
  任意缩放下与 100% 的版式比例一致。

约束沿袭：单窗口单线程，全部刷新由 root.after(1000) 单循环驱动（R1）；
每 tick 用真实当前时刻重算（A10/R2）；tick 异常兜底（A11/R5）；公式一律调 money 纯函数；
config.json 固定位于本脚本目录、与 CWD 无关（A12）。

tag 契约：_render 与 _update_display/_set_status 依赖的 tag 名严格一致——
date / cap / amt_int / amt_dec / cd / fill / mark_c / sv0..sv2
（mark_l/mark_r 仅 render 静态写；缺失 = 静默冻结在初始文本）。
"""

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
    "leaves": {                 # 分模式当月休假：{模式: {ISO 日期: "调休"/"请假"}}，互不影响
        "weekend": {},
        "free": {},
    },
    "payday": 15,
    "theme": "dark",
    "last_asked_date": "",
}

CONFIG_FILENAME = "config.json"
TICK_MS = 1000
_TICK_ERROR = "刷新异常：数据可能停更，请检查设置或重启程序"

# ---- 窗口与布局 ----
DEFAULT_WIN_W, DEFAULT_WIN_H = 348, 452
MIN_WIN_W, MIN_WIN_H = 300, 400

MODE_LABELS = {"weekend": "固定周末公休", "free": "自由假期（当月任选）"}

# 加班时长进度条满格刻度（4 小时）
OVERTIME_BAR_SECONDS = 4 * 3600


def compute_layout(w: int, h: int) -> dict:
    """按窗口尺寸比例计算全部绘制位置（比例沿用 v5 设计稿版式，
    并把日期行合并进标题行——系统标题栏已占用窗口顶端，画布内不再重复应用名）。"""
    m = max(14, int(w * 0.063))  # 左右边距（348 宽 ≈ 22px）
    span = w - 2 * m
    track_y = int(h * 0.735)
    return {
        "margin": m,
        "date": (m, int(h * 0.058)),                    # 日期/状态行（anchor w，标题行左）
        "icon_theme": (w - m - int(m * 1.4), int(h * 0.058)),  # ◐（anchor e）
        "icon_gear": (w - m, int(h * 0.058)),           # ⚙（anchor e）
        "cap": (w // 2, int(h * 0.300)),                # 主数字标题
        "amount": (w // 2, int(h * 0.418)),             # 主数字（int anchor e / dec anchor w）
        "cd": (w // 2, int(h * 0.538)),                 # 倒计时/副文案
        "btn": (w // 2, int(h * 0.622)),                # 结束加班按钮（仅压榨模式）
        "track": (m, track_y, w - m, track_y + 4),      # 进度条轨道
        "marks": track_y + 16,                          # 进度条刻度行 y
        "sep": int(h * 0.852),                          # 统计区分隔线 y
        "stat_xs": (m + span // 6, w // 2, w - m - span // 6),
        "stat_label_y": int(h * 0.885),
        "stat_value_y": int(h * 0.932),
    }


# 主题 = 完整外观 token。bg0/bg1 渐变端点；accent 主数字/进度条；
# dlg_*/field_*/btn_* 供设置与询问弹窗使用（弹窗不随压榨模式变色）。
THEMES = {
    "dark": {
        "label": "暗夜极简",
        "bg0": "#0E0F13", "bg1": "#171A21",
        "accent": "#7DB8FF", "ink": "#F5F5F7",
        "label_ink": "#9698A3", "faint": "#5C5F6A", "line": "#262A33",
        "dlg_bg": "#1C1E24", "field_bg": "#26282F", "field_fg": "#F5F5F7",
        "btn_bg": "#7DB8FF", "btn_fg": "#0F1216",
        "btn_active": "#99C6FF", "btn2_bg": "#2E3138", "btn2_fg": "#F5F5F7",
        "err": "#FF6B6B",
        "menu_bg": "#1C1E24", "menu_fg": "#F5F5F7",
        "menu_active_bg": "#7DB8FF", "menu_active_fg": "#0F1216",
        "menu_disabled": "#6B6E78",
    },
    "light": {
        "label": "清晨亮色",
        "bg0": "#F5F5F7", "bg1": "#FFFFFF",
        "accent": "#0A84FF", "ink": "#1D1D1F",
        "label_ink": "#6E6E73", "faint": "#AEAEB2", "line": "#E3E3E8",
        "dlg_bg": "#F5F5F7", "field_bg": "#FFFFFF", "field_fg": "#1D1D1F",
        "btn_bg": "#0A84FF", "btn_fg": "#FFFFFF",
        "btn_active": "#3395FF", "btn2_bg": "#E9E9EB", "btn2_fg": "#1D1D1F",
        "err": "#E02D2D",
        "menu_bg": "#F5F5F7", "menu_fg": "#1D1D1F",
        "menu_active_bg": "#0A84FF", "menu_active_fg": "#FFFFFF",
        "menu_disabled": "#B0B0B5",
    },
}
# 旧主题键 → 新变体观感最接近者（读取时迁移；运行期 _theme_key 不再映射）
LEGACY_THEME = {"midnight": "dark", "paper": "light", "glass": "light",
                "mint": "light", "amber": "light", "sky": "light"}

# 加班红色警报调色板（仅主画布渲染用；弹窗仍走主题 token）
ALERT_PALETTE = {
    "bg0": "#160B0C", "bg1": "#1D0F10",
    "accent": "#FF5252", "ink": "#F5F5F7",
    "label_ink": "#A98A8A", "faint": "#6E4A4A", "line": "#3A2224",
}

FONT_APP = ("Microsoft YaHei UI", 10)
FONT_APP_SMALL = ("Microsoft YaHei UI", 9)


def _mix_hex(c1: str, c2: str, t: float) -> str:
    """两个 #RRGGBB 颜色线性插值（渐变底逐行用）。"""
    a = (int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16))
    b = (int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16))
    return "#%02X%02X%02X" % tuple(int(x + (y - x) * t) for x, y in zip(a, b))


# ---------------------------------------------------------------------------
# config.json 持久化（A12 / R4）
# ---------------------------------------------------------------------------

def config_path() -> str:
    """config.json 固定与 app.py 同目录，与 CWD 无关。"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG_FILENAME)


def load_config(path: str | None = None) -> tuple[dict, str]:
    """读取 config.json，返回 (config, 警告文案)。

    缺失 → 默认值；JSON 损坏或字段非法 → 重置默认并提示（R4）。
    theme 旧值（midnight/paper/glass/mint/amber/sky）自动迁移；非法 theme 回退 dark。
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
        loaded["leaves"]["free"].update(legacy)  # 旧自由假日归入 free 组（同键覆盖，仅新旧混合迁移形态可达）
        # 两个模式的 leaves 都过 validate（各自 mode），非当前模式的垃圾数据同整表重置
        for mode in ("weekend", "free"):
            if money.validate(loaded["monthly_salary"], loaded["work_start"],
                              loaded["work_end"], loaded["leaves"][mode],
                              loaded["payday"], mode):
                raise ValueError("config fields failed money.validate")
        loaded["theme"] = str(loaded["theme"])  # 防不可哈希 JSON 值在下方查找中抛 TypeError
        loaded["theme"] = LEGACY_THEME.get(loaded["theme"], loaded["theme"])
        if loaded["theme"] not in THEMES:
            loaded["theme"] = "dark"
        loaded["last_asked_date"] = str(loaded["last_asked_date"])
        return loaded, ""
    except (OSError, ValueError):
        # 逐层拷贝：避免异常路径返回的配置与 DEFAULT_CONFIG 共享内层 leaves 可变对象
        cfg = dict(DEFAULT_CONFIG)
        cfg["leaves"] = {m: dict(v) for m, v in DEFAULT_CONFIG["leaves"].items()}
        return cfg, "config.json 读取失败，已重置为默认值，请检查后重新保存"


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
    """自绘标题栏 + 实时收入主界面 + 设置弹窗 + 下班询问 + 红色压榨模式。"""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        # DPI 感知后 Tk 坐标即物理像素；未感知时恒报 96 → scale=1（测试/兼容路径）
        try:
            self._scale = max(1.0, root.winfo_fpixels("1i") / 96.0)
        except Exception:
            self._scale = 1.0
        self.cfg, load_warning = load_config()
        self.configured = os.path.exists(config_path()) and not load_warning
        self.pss = 0.0                 # 当月秒薪（月度派生缓存）
        self.daily = 0.0               # 当月日薪（月度派生缓存，请假显示用）
        self.overtime_start = None     # 加班激活时刻；None = 非加班
        self.cached_date = None        # tick 跨日/跨月检测缓存
        self.ask_dialog = None         # 「今天加班吗」非模态弹窗
        self.settings_dialog = None    # 设置弹窗（同一时刻至多一个）
        self.canvas = None             # 主画布（全部实时内容绘在其上）
        self._end_btn = None           # 结束加班按钮引用（防 GC）
        self._win_w = round(DEFAULT_WIN_W * self._scale)  # 当前布局尺寸（物理 px）
        self._win_h = round(DEFAULT_WIN_H * self._scale)
        self._min_w = round(MIN_WIN_W * self._scale)
        self._min_h = round(MIN_WIN_H * self._scale)
        self._tick_errored = False    # tick 异常标志（恢复后撤提示用）
        self._rgn_size = (0, 0)        # 已应用圆角区域对应的窗口尺寸
        self._fonts = None             # 字体缓存（键 = 窗口宽度）
        self._status_msg = None        # 状态行消息（占据日期行位置，自动清除）
        self._status_after = None      # 状态行自动清除定时器
        self._ctx_menu = None          # 右键菜单（主题切换后整体重建）
        self._today_menu = None        # 「标记今天」子菜单引用
        self._unmark_idx = None        # 「取消标记」菜单项索引（避免魔法下标错位）
        self.theme_var = None          # 主题 radiobutton 绑定变量
        # 等宽字体探测（Consolas → Cascadia Mono → Courier New，按系统可用性回退）
        fams = set(tkfont.families(root))
        self._mono = ("Consolas" if "Consolas" in fams
                      else "Cascadia Mono" if "Cascadia Mono" in fams else "Courier New")
        # 图标字体（⚙/◐ 属 Symbol 区，Segoe UI Symbol 全 Win10/11 内置）
        self._iconfont = "Segoe UI Symbol" if "Segoe UI Symbol" in fams \
            else "Microsoft YaHei UI"
        self._build_ui()
        self._build_context_menu()
        self._refresh_month_cache(datetime.now())
        self._render()
        self._update_display(datetime.now())
        self._apply_window_chrome(initial=True)
        if load_warning:
            self._set_status(load_warning, clear_ms=0)
        self.root.after(TICK_MS, self._tick)

    # ---------------- UI 构建（Canvas + 渐变底，全部矢量绘制）----------------

    def _build_ui(self) -> None:
        self.root.title("时间就是金钱 · 实时薪资钟")
        self.root.geometry(f"{self._win_w}x{self._win_h}")
        self.root.minsize(self._min_w, self._min_h)
        self.root.resizable(True, True)

        self.canvas = tk.Canvas(self.root, width=self._win_w,
                                height=self._win_h,
                                bg=self._ui()["bg0"],
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Button-3>", self._post_context_menu)
        # tag 绑定按 tag 生效：delete("all") 重建同 tag 元素后依然有效
        c = self.canvas
        c.tag_bind("icon_gear", "<Button-1>", lambda e: self._open_settings())
        c.tag_bind("icon_theme", "<Button-1>", lambda e: self._on_theme_toggle())
        for tag in ("icon_gear", "icon_theme"):
            c.tag_bind(tag, "<Enter>", lambda e: c.configure(cursor="hand2"))
            c.tag_bind(tag, "<Leave>", lambda e: c.configure(cursor=""))

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
            r = int(24 * self._scale)
            rgn = gdi32.CreateRoundRectRgn(0, 0, size[0], size[1], r, r)
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
        self._update_today_state()
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
        self._update_today_state()
        self._update_display(datetime.now())
        self._set_status("已取消今天的休假标记")

    # ---------------- 主题与调色板 ----------------

    def _theme_key(self) -> str:
        """当前主题键（非法值回退 dark，与 load_config 兜底一致）。"""
        key = self.cfg["theme"]
        return key if key in THEMES else "dark"

    def _tokens(self) -> dict:
        """当前主题 token（弹窗/菜单配色用，不随压榨模式变色）。"""
        return THEMES[self._theme_key()]

    def _ui(self) -> dict:
        """主画布调色板：压榨期间覆盖为红色警报，否则用当前主题。"""
        if self.overtime_start is not None:
            return {**THEMES[self._theme_key()], **ALERT_PALETTE}
        return THEMES[self._theme_key()]

    def _make_fonts(self) -> dict:
        """字号随窗口宽度缩放；数字用等宽字体（tabular，每秒跳动不抖宽）。

        字号单位是 pt（Tk 正数=磅，随 DPI 换算像素）：按逻辑宽度（物理÷scale）
        取比例，任意缩放下与 100% 的版式比例一致。"""
        w = self._win_w
        if self._fonts is not None and self._fonts.get("_w") == w:
            return self._fonts
        wl = round(w / self._scale)  # 逻辑宽度：字号比例基准（DPI 无关，先取整消除抖动）
        yahei = "Microsoft YaHei UI"

        def s(k: float, lo: int, hi: int) -> int:
            return max(lo, min(int(wl * k), hi))

        f = {
            "date": (yahei, s(0.031, 9, 12)),
            "cap": (yahei, s(0.034, 10, 13)),
            "cd": (yahei, s(0.037, 10, 15)),
            "marks": (self._mono, s(0.029, 8, 11)),
            "stat_label": (yahei, s(0.029, 9, 11)),
            "stat_value": (self._mono, s(0.040, 11, 16), "bold"),
            "stat_value_cjk": (yahei, s(0.040, 11, 16), "bold"),
            "icon": (self._iconfont, s(0.045, 11, 15)),
            "int": (self._mono, s(0.161, 34, 76), "bold"),
            "dec": (self._mono, max(16, s(0.161, 34, 76) * 46 // 100), "bold"),
            "_w": w,
        }
        f["_int_font"] = tkfont.Font(family=self._mono, size=f["int"][1], weight="bold")
        f["_dec_font"] = tkfont.Font(family=self._mono, size=f["dec"][1], weight="bold")
        self._fonts = f
        return f

    def _on_theme_toggle(self) -> None:
        """◐ 图标：dark ↔ light 直接切换。"""
        self.theme_var.set("light" if self._theme_key() == "dark" else "dark")
        self._on_theme_change()

    def _on_theme_change(self) -> None:
        key = self.theme_var.get()
        if key not in THEMES:
            return
        self.cfg["theme"] = key
        if not save_config(self.cfg):  # 主题即时持久化
            self._set_status("警告：config.json 写入失败，主题未持久化", clear_ms=0)
        self._build_context_menu()  # 菜单配色跟随新主题
        self._render()
        self._update_display(datetime.now())

    # ---------------- 右键菜单（主题 / 标记今天 / 设置）----------------

    def _styled_menu(self, master) -> tk.Menu:
        t = self._tokens()
        return tk.Menu(master, tearoff=0, font=FONT_APP, bd=0, relief="flat",
                       activeborderwidth=0,
                       bg=t["menu_bg"], fg=t["menu_fg"],
                       activebackground=t["menu_active_bg"],
                       activeforeground=t["menu_active_fg"],
                       disabledforeground=t["menu_disabled"])

    def _build_context_menu(self) -> None:
        if self._ctx_menu is not None:
            self._ctx_menu.destroy()
        menu = self._styled_menu(self.root)
        if self.theme_var is None:
            self.theme_var = tk.StringVar(value=self._theme_key())
        else:
            self.theme_var.set(self._theme_key())
        for key in THEMES:
            menu.add_radiobutton(label=THEMES[key]["label"], value=key,
                                 variable=self.theme_var,
                                 command=self._on_theme_change)
        menu.add_separator()
        m_today = self._styled_menu(menu)
        m_today.add_command(label="调休", command=lambda: self._mark_today("调休"))
        m_today.add_command(label="请假", command=lambda: self._mark_today("请假"))
        m_today.add_command(label="取消标记", command=self._unmark_today)
        self._unmark_idx = m_today.index("end")  # 记录索引，菜单结构变化不错位
        menu.add_cascade(label="标记今天", menu=m_today)
        menu.add_separator()
        menu.add_command(label="设置…", command=self._open_settings)
        self._ctx_menu = menu
        self._today_menu = m_today
        self._update_today_state()

    def _post_context_menu(self, event) -> None:
        try:
            self._ctx_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._ctx_menu.grab_release()

    def _update_today_state(self) -> None:
        """今天已标记 → 「取消标记」可用；未标记 → 禁用（调休/请假随时可点）。"""
        if self._today_menu is None or self._unmark_idx is None:
            return
        mode_leaves = self.cfg["leaves"].get(self.cfg["holiday_mode"], {})
        marked = datetime.now().date().isoformat() in mode_leaves
        self._today_menu.entryconfig(self._unmark_idx,
                                     state="normal" if marked else "disabled")

    # ---------------- 渲染（主视图 / 红色压榨视图共用骨架）----------------

    def _render(self) -> None:
        c = self.canvas
        w, h = self._win_w, self._win_h
        lay = compute_layout(w, h)
        f = self._make_fonts()
        p = self._ui()
        alert = self.overtime_start is not None
        m = lay["margin"]
        c.delete("all")
        c.configure(bg=p["bg0"])
        # 渐变底（96 行带，垂直方向 bg0→bg1）
        steps = 96
        for i in range(steps):
            y0, y1 = h * i // steps, h * (i + 1) // steps
            col = _mix_hex(p["bg0"], p["bg1"], i / (steps - 1))
            c.create_rectangle(0, y0, w, y1 + 1, fill=col, outline=col, tags="bg")
        # 标题行：日期/状态（左）+ 主题切换/设置图标（右），内容每秒由
        # _update_display 写入 date；系统标题栏已占用窗口顶端，不重复应用名
        c.create_text(lay["date"], text="", font=f["date"], fill=p["faint"],
                      anchor="w", width=w - 2 * m - int(m * 2.4), tags="date")
        c.create_text(lay["icon_theme"], text="◐", font=f["icon"],
                      fill=p["faint"], anchor="e", tags="icon_theme")
        c.create_text(lay["icon_gear"], text="⚙", font=f["icon"],
                      fill=p["faint"], anchor="e", tags="icon_gear")
        # 主数字区
        c.create_text(lay["cap"], text="今日已赚（元）", font=f["cap"],
                      fill=p["label_ink"], tags="cap")
        c.create_text((0, 0), text="0", font=f["int"], fill=p["accent"],
                      anchor="e", tags="amt_int")
        c.create_text((0, 0), text=".00", font=f["dec"], fill=p["accent"],
                      anchor="w", tags="amt_dec")
        c.create_text(lay["cd"], text="", font=f["cd"], fill=p["label_ink"],
                      tags="cd")
        if alert:
            if self._end_btn is None or not self._end_btn.winfo_exists():
                # 复用按钮：缩放期 _render 高频重建，canvas.delete 不销毁
                # widget，每次新建会泄漏控件
                self._end_btn = tk.Button(c, text="结束加班", command=self._on_end_overtime,
                                          font=("Microsoft YaHei UI", max(10, f["cap"][1] + 1), "bold"),
                                          bd=0, relief="flat", cursor="hand2",
                                          bg="#241214", fg="#FF8585",
                                          activebackground="#38181B", activeforeground="#FF8585",
                                          highlightthickness=1, highlightbackground="#4A1F22",
                                          highlightcolor="#FF5252", padx=24, pady=6)
            c.create_window(lay["btn"], window=self._end_btn)
        # 进度条（主 = 今日进度；压榨 = 加班时长）+ 刻度
        c.create_rectangle(*lay["track"], fill=p["line"], outline=p["line"],
                           tags="track")
        tx0, ty0, _, ty1 = lay["track"]
        c.create_rectangle(tx0, ty0, tx0, ty1, fill=p["accent"],
                           outline=p["accent"], tags="fill")
        c.create_text((m, lay["marks"]), text="", font=f["marks"],
                      fill=p["faint"], anchor="w", tags="mark_l")
        c.create_text((w // 2, lay["marks"]), text="", font=f["marks"],
                      fill=p["label_ink"], tags="mark_c")
        c.create_text((w - m, lay["marks"]), text="", font=f["marks"],
                      fill=p["faint"], anchor="e", tags="mark_r")
        if alert:
            c.itemconfigure("mark_l", text=f"下班 {self.cfg['work_end']}")
            c.itemconfigure("mark_r", text="加班中")
        else:
            c.itemconfigure("mark_l", text=self.cfg["work_start"])
            c.itemconfigure("mark_r", text=self.cfg["work_end"])
        # 统计区（分隔线 + 三栏）
        c.create_rectangle(m, lay["sep"], w - m, lay["sep"] + 1,
                           fill=p["line"], outline=p["line"], tags="sep")
        labels = ("本月已赚（元）", "距发薪",
                  "每秒损失" if alert else "秒薪（元）")
        for i, name in enumerate(labels):
            c.create_text((lay["stat_xs"][i], lay["stat_label_y"]), text=name,
                          font=f["stat_label"], fill=p["faint"], tags=f"sl{i}")
            c.create_text((lay["stat_xs"][i], lay["stat_value_y"]), text="—",
                          font=f["stat_value_cjk"] if i == 1 else f["stat_value"],
                          fill=p["ink"], tags=f"sv{i}")

    def _on_canvas_configure(self, event) -> None:
        self._apply_window_chrome()
        w = max(self._min_w, event.width)
        h = max(self._min_h, event.height)
        if (w, h) == (self._win_w, self._win_h):
            return
        self._win_w, self._win_h = w, h
        self._render()
        self._update_display(datetime.now())

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
                 bg=t["dlg_bg"], fg=t["label_ink"]).pack(side="left")
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
                     bg=t["dlg_bg"], fg=t["label_ink"]).grid(row=0, column=c)
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
                       font=FONT_APP_SMALL, bg=t["dlg_bg"], fg=t["label_ink"],
                       activebackground=t["dlg_bg"], activeforeground=t["label_ink"],
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
        # 两模式都校验：异模式 leaves 若把应出勤天数吃光，重启时 load_config
        # 会整表重置（连月薪一起丢），必须在保存点拦下
        errors: list[str] = []
        for m in ("weekend", "free"):
            errs = money.validate(salary, ws, we, leaves[m], payday, m)
            errors += errs if m == mode else [f"（{MODE_LABELS[m]}）{e}" for e in errs]
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
        self._update_today_state()
        self._set_status("已保存")
        self._update_display(datetime.now())
        dlg.destroy()

    # ---------------- 每秒 tick ----------------

    def _tick(self) -> None:
        try:
            self._tick_once()
            if self._tick_errored:  # 恢复正常后撤下错误提示
                self._tick_errored = False
                self._clear_status()
        except Exception:
            self._tick_errored = True  # A11/R5：单次 tick 异常兜底，不终止刷新循环
            try:
                if self._status_msg != _TICK_ERROR:  # 持续异常可见（原为静默冻结）
                    self._set_status(_TICK_ERROR, clear_ms=0)
            except Exception:
                pass
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
        self._update_today_state()           # 跨日刷新「取消标记」可用态
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

    # ---------------- 每秒显示更新 ----------------

    @staticmethod
    def _fmt(v: float) -> str:
        return f"{v:,.2f}"

    def _set_amount(self, value: float) -> None:
        """主数字 = 大号整数 + 小号小数，整体居中（按字形实测宽度拼位）。"""
        c = self.canvas
        lay = compute_layout(self._win_w, self._win_h)
        f = self._make_fonts()
        int_txt, dec_txt = self._fmt(value).split(".")
        dec_txt = "." + dec_txt
        w_int = f["_int_font"].measure(int_txt)
        w_dec = f["_dec_font"].measure(dec_txt)
        x = lay["amount"][0] + (w_int - w_dec) // 2
        c.itemconfigure("amt_int", text=int_txt)
        c.itemconfigure("amt_dec", text=dec_txt)
        c.coords("amt_int", x, lay["amount"][1])
        c.coords("amt_dec", x, lay["amount"][1])

    def _set_fill(self, fraction: float) -> None:
        """进度条填充比例（0–1）。"""
        lay = compute_layout(self._win_w, self._win_h)
        tx0, ty0, tx1, ty1 = lay["track"]
        self.canvas.coords("fill", tx0, ty0, tx0 + (tx1 - tx0) * max(0.0, min(1.0, fraction)), ty1)

    def _date_text(self, now: datetime, state: str) -> str:
        return f"{now.month}月{now.day}日 周{'日一二三四五六'[now.weekday()]} · {state}"

    def _update_display(self, now: datetime) -> None:
        cfg = self.cfg
        ic = self.canvas.itemconfigure
        alert = self.overtime_start is not None
        if alert:  # 压榨视图：主数字 = 老板压榨金额，进度条 = 加班时长
            over = money.overtime_seconds(now, cfg["work_end"], self.overtime_start)
            self._set_amount(self.pss * over)
            ic("cap", text="老板压榨金额（元）")
            hh, rem = divmod(over, 3600)
            ic("cd", text=f"本次加班 {hh:02d}:{rem // 60:02d}:{rem % 60:02d}")
            self._set_fill(over / OVERTIME_BAR_SECONDS)
            ic("mark_c", text=f"+{self.pss:.4f}/s")
            ic("sv2", text=f"{self.pss:.4f}")
            month_earned = money.earned_this_month(
                self.pss, now, cfg["work_start"], cfg["work_end"],
                cfg["leaves"].get(cfg["holiday_mode"], {}), cfg["holiday_mode"]) \
                + self.pss * over
            ic("sv0", text=self._fmt(month_earned))
        else:
            ic("cap", text="今日已赚（元）")
            if not self.configured:  # 未配置不渲染默认金额，显示引导占位
                self._set_amount(0.0)
                ic("amt_int", text="—")
                ic("amt_dec", text="")
                ic("cd", text="右键窗口 → 设置… 完成配置")
                ic("mark_c", text="")
                self._set_fill(0.0)
                for k in ("sv0", "sv1", "sv2"):
                    ic(k, text="—")
            else:
                ws, we = cfg["work_start"], cfg["work_end"]
                mode = cfg["holiday_mode"]
                leaves = cfg["leaves"].get(mode, {})
                today_earned = money.earned_today(self.pss, now, ws, we, leaves, mode)
                self._set_amount(today_earned)
                paid_sec = money.today_paid_seconds(now, ws, we, leaves, mode)
                daily_sec = money.daily_work_seconds(ws, we)
                self._set_fill(paid_sec / daily_sec)
                ic("mark_c", text=f"{paid_sec / daily_sec * 100:.1f}%")
                ic("sv0", text=self._fmt(money.earned_this_month(
                    self.pss, now, ws, we, leaves, mode)))
                ic("sv2", text=f"{self.pss:.4f}")
                # 倒计时/副文案：请假 / 调休 / 休息日 / 距下班
                today_type = leaves.get(now.date().isoformat())
                if today_type == "请假":
                    ic("cd", text=f"今天没了 {self._fmt(self.daily)} 元")
                elif today_type == "调休":
                    ic("cd", text="今日不计薪，秒薪已上调")
                elif not self._is_workday(now.date()):
                    ic("cd", text="今天不计薪")
                else:
                    end_sec = money.daily_work_seconds("00:00", we)
                    now_sec = now.hour * 3600 + now.minute * 60 + now.second
                    if now_sec >= end_sec:
                        ic("cd", text="已下班")
                    else:
                        h, rem = divmod(end_sec - now_sec, 3600)
                        ic("cd", text=f"距离下班 {h:02d}:{rem // 60:02d}:{rem % 60:02d}")
        if alert or self.configured:  # 距发薪：两种视图通用（未配置态除外）
            days = money.days_until_payday(now.date(), cfg["payday"])
            ic("sv1", text="今天发薪" if days == 0 else f"{days} 天")
        # 日期/状态行：状态消息优先，否则显示日期 + 当前状态
        if self._status_msg is not None:
            ic("date", text=self._status_msg)
        else:
            if alert:
                state = "加班中"
            elif not self.configured:
                state = "待配置"
            else:
                today_type = cfg["leaves"].get(cfg["holiday_mode"], {}).get(
                    now.date().isoformat())
                if today_type == "请假":
                    state = "请假中"
                elif today_type == "调休":
                    state = "调休中"
                elif not self._is_workday(now.date()):
                    state = "休息日"
                else:
                    end_sec = money.daily_work_seconds("00:00", cfg["work_end"])
                    now_sec = now.hour * 3600 + now.minute * 60 + now.second
                    start_sec = money.daily_work_seconds("00:00", cfg["work_start"])
                    if now_sec < start_sec:
                        state = "未上班"
                    elif now_sec >= end_sec:
                        state = "已下班"
                    else:
                        state = "上班中"
            ic("date", text=self._date_text(now, state))

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
        dlg.update_idletasks()
        x = self.root.winfo_x() + max(0, (self.root.winfo_width() - dlg.winfo_reqwidth()) // 2)
        y = self.root.winfo_y() + max(0, (self.root.winfo_height() - dlg.winfo_reqheight()) // 3)
        dlg.geometry(f"+{x}+{y}")

    def _close_ask_dialog(self) -> None:
        dlg, self.ask_dialog = self.ask_dialog, None
        if dlg is not None and dlg.winfo_exists():
            dlg.destroy()

    def _on_ask_dismissed(self) -> None:
        self._mark_asked()       # 不加班 & 直接关窗均视为已答复
        self._close_ask_dialog()

    # ---------------- 加班（红色压榨）模式（A8）----------------

    def _on_accept_overtime(self) -> None:
        self._mark_asked()
        self._close_ask_dialog()
        if self.overtime_start is None:
            self.overtime_start = datetime.now()  # A8 origin = max(当日下班, 激活时刻)
        self._render()  # 切红色警报调色板 + 压榨内容
        self._update_display(datetime.now())

    def _on_end_overtime(self) -> None:
        self.overtime_start = None  # 停止累计；exploit 为临时强制态
        self._render()  # 切回主题调色板主视图
        self._update_display(datetime.now())

    # ---------------- 状态行（占据日期行位置，自动清除）----------------

    def _set_status(self, text: str, clear_ms: int = 3000) -> None:
        """状态提示：默认 3 秒后自动消失；clear_ms=0 常驻（警告类）直到被替换。"""
        if self._status_after is not None:
            self.root.after_cancel(self._status_after)
            self._status_after = None
        self._status_msg = text
        self.canvas.itemconfigure("date", text=text)
        if clear_ms:
            self._status_after = self.root.after(clear_ms, self._clear_status)

    def _clear_status(self) -> None:
        self._status_after = None
        self._status_msg = None
        self._update_display(datetime.now())


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


def _enable_dpi_awareness() -> None:
    """声明进程 DPI 感知：否则 125%/150% 系统缩放下窗口被 DWM 位图拉伸、
    文字发虚。必须在创建任何 Tk 窗口前调用；失败静默（观感退回拉伸，
    功能不受影响）。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # 系统级 DPI 感知
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()  # 无 shcore 的旧系统回退
        except Exception:
            pass


def main() -> None:
    _enable_dpi_awareness()
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
