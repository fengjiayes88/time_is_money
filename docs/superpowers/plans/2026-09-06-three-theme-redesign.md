# 三主题可切换 UI 重设计 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 把现有单一样式重构为 midnight / paper / glass 三套可切换主题，主数字换等宽字体、删描边光晕、冰蓝强调色锁定、弹窗菜单跟随主题。

**架构：** `make_bg.py` 的 `bake_glass()` 按 theme 参数分支出三套材质（压暗渐晕 / 白化卡片 / 白玻璃），`app.py` 的 `THEMES` 从「强调色表」升级为「完整 token 表」，渲染层、菜单、弹窗全部从 token 取色。`money.py`、config 其余字段、缩放机制零改动。

**技术栈：** Python 3.11 + tkinter（stdlib）、Pillow（可选，运行时烘焙）、Consolas（系统等宽字体）。

**规格：** `docs/superpowers/specs/2026-09-06-three-theme-redesign-design.md`

**两处规格级微调（实现时采纳，已在下方任务内体现）：**
1. glass 主题底部保留一条 α70 渐晕（规格只写了顶部）——状态行白字在原壁纸上必须靠烘焙层保可读，与规格 §4.2 原则一致；
2. 倒计时「距下班 HH:MM:SS」保留雅黑（规格写 Consolas）——14px 小字每秒抖动不可感知，避免 CJK 前缀与等宽字体混排的回退风险；等宽只用于主数字与统计数值。

---

## 文件结构

- 修改：`make_bg.py` — 三主题材质参数 + `bake_glass(theme)` 重构 + CLI 生成三份预烘焙背景
- 修改：`app.py` — THEMES token 化、迁移、字体、渲染、菜单、弹窗、回退背景
- 创建：`test_redesign.py` — assert 自检（迁移 + 烘焙），风格对齐 `money.py`
- 删除：`assets/bg.png`（被 `bg_midnight/paper/glass.png` 取代；`bg_exploit.png` 保留）
- 修改：`README.md` — 主题表更新

---

### 任务 0：git 基线（可选，10 秒）

目录不是 git 仓库。为后续每任务可回滚，先建基线；用户明确不要 git 则整个计划跳过所有 commit 步骤。

- [ ] **步骤 1：初始化并提交现状**

```bash
cd D:/pi_work/time_is_money
git init
git add app.py money.py make_bg.py README.md config.json 启动.bat assets/
git commit -m "baseline before three-theme redesign"
```

（`__pycache__`、`.superpowers/`、`pi-tasks/`、`docs/` 不入库：`printf '__pycache__/\n.superpowers/\npi-tasks/\n' > .gitignore` 后再 add）

---

### 任务 1：make_bg.py 三主题烘焙

**文件：**
- 修改：`make_bg.py`
- 创建：`test_redesign.py`

- [ ] **步骤 1：写失败测试（先建骨架，bake 尚无 theme 参数会 TypeError）**

创建 `test_redesign.py`：

```python
"""test_redesign.py — 重设计自检：三主题烘焙 + 主题迁移。运行：python test_redesign.py"""
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))


def check_bake():
    try:
        import make_bg
    except Exception:
        print("Pillow 未安装，跳过 bake 检查")
        return
    from PIL import Image
    size = (348, 452)
    panels = [(26, 63, 322, 228), (26, 246, 322, 309)]
    src = os.path.join(HERE, "assets", "wallpaper.jpg")
    avgs = {}
    for theme in ("midnight", "glass", "paper"):
        data = make_bg.bake_glass(src, size, panels, theme)
        img = Image.open(io.BytesIO(data)).convert("RGB")
        assert img.size == size, (theme, img.size)
        px = list(img.getdata())
        avgs[theme] = sum(sum(p) for p in px) / (len(px) * 3)
    assert avgs["midnight"] < avgs["glass"] < avgs["paper"], avgs
    print("bake OK", {k: round(v) for k, v in avgs.items()})


if __name__ == "__main__":
    check_bake()
    print("ALL OK")
```

- [ ] **步骤 2：运行验证失败**

运行：`python test_redesign.py`
预期：`TypeError: bake_glass() takes 3 positional arguments but 4 were given`

- [ ] **步骤 3：实现三主题烘焙**

`make_bg.py` 顶部参数区替换为（旧的 BLUR/GLASS_WHITE/SCRIM_* 常量删除；α 透明度按面底近似换算成实色）：

```python
# —— 三主题材质参数（edge/hilite 为实色，α 已按面底换算）——
THEME_BAKE = {
    "midnight": {  # 壁纸压暗 + 渐晕 + 暗玻璃面板
        "brightness": 0.5, "vignette_alpha": 110,
        "panel_blur": 22, "tint": (15, 17, 22), "tint_alpha": 132,
        "edge": (110, 115, 126), "hilite": (140, 146, 158),
    },
    "paper": {     # 壁纸强模糊白化 + 近实白卡片
        "blur": 26, "wash": 0.78,
        "tint": (255, 255, 255), "tint_alpha": 184,
        "edge": (232, 232, 235), "shadow_alpha": 26,
    },
    "glass": {     # 壁纸原样 + 白玻璃面板 + 顶/底窄渐晕
        "top_bottom_alpha": 70,
        "panel_blur": 20, "tint": (255, 255, 255), "tint_alpha": 117,
        "edge": (244, 244, 246), "hilite": (255, 255, 255),
    },
}
RADIUS = 24
```

`_add_scrims` 与 `bake_glass`/`bake_dark` 整体替换为：

```python
def _radial_vignette(img: Image.Image, alpha: int) -> None:
    """大半径径向渐晕（1/8 分辨率计算后双线性放大，消除色带）。中心 55% 不压。"""
    w, h = img.size
    W, H = max(1, w // 8), max(1, h // 8)
    m = Image.new("L", (W, H), 0)
    px = m.load()
    cx, cy = (W - 1) / 2, (H - 1) / 2
    maxd = (cx * cx + cy * cy) ** 0.5
    for y in range(H):
        for x in range(W):
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / maxd
            t = max(0.0, (d - 0.55) / 0.45)
            px[x, y] = int(alpha * t * t)
    img.paste(Image.new("RGB", (w, h), (6, 8, 12)), (0, 0),
              m.resize((w, h), Image.BILINEAR))


def _band_scrims(img: Image.Image, alpha: int) -> None:
    """glass 用顶/底窄渐晕（标题与状态行可读），高度 12%。"""
    w, h = img.size
    band = max(8, int(h * 0.12))
    overlay = Image.new("L", (1, h), 0)
    px = overlay.load()
    for y in range(min(band, h)):
        px[0, y] = int(alpha * (1 - y / band))
        px[0, h - 1 - y] = int(alpha * (1 - y / band))
    img.paste(Image.new("RGB", (w, h), (0, 0, 0)), (0, 0),
              overlay.resize((w, h)))


def _paste_panel(base: Image.Image, glass: Image.Image, box, p: dict) -> None:
    mask = Image.new("L", base.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=RADIUS, fill=255)
    if "shadow_alpha" in p:  # paper：面板下柔和投影
        sh = Image.new("L", base.size, 0)
        ImageDraw.Draw(sh).rounded_rectangle(
            (box[0], box[1] + 6, box[2], box[3] + 6), radius=RADIUS, fill=p["shadow_alpha"])
        sh = sh.filter(ImageFilter.GaussianBlur(12))
        base.paste(Image.new("RGB", base.size, (20, 24, 34)), (0, 0), sh)
    base.paste(glass, (0, 0), mask)
    d = ImageDraw.Draw(base)
    d.rounded_rectangle(box, radius=RADIUS, outline=p["edge"], width=1)
    if "hilite" in p:  # 上缘内高光（x 两端内收 RADIUS，y = 面板顶 +2）
        d.line((box[0] + RADIUS, box[1] + 2, box[2] - RADIUS, box[1] + 2),
               fill=p["hilite"], width=1)


def bake_glass(src: str, size: tuple[int, int],
               panels: list[tuple[int, int, int, int]],
               theme: str = "glass") -> bytes:
    p = THEME_BAKE[theme]
    base = _fit(src, size)
    if theme == "midnight":
        base = ImageEnhance.Brightness(base).enhance(p["brightness"])
        _radial_vignette(base, p["vignette_alpha"])
        glass = base.filter(ImageFilter.GaussianBlur(p["panel_blur"]))
    elif theme == "paper":
        base = base.filter(ImageFilter.GaussianBlur(p["blur"]))
        base = Image.blend(base, Image.new("RGB", size, (255, 255, 255)), p["wash"])
        glass = base
    else:  # glass
        _band_scrims(base, p["top_bottom_alpha"])
        glass = base.filter(ImageFilter.GaussianBlur(p["panel_blur"]))
    glass = Image.blend(glass, Image.new("RGB", size, p["tint"]),
                        p["tint_alpha"] / 255)
    for box in panels:
        _paste_panel(base, glass, box, p)
    return _png_bytes(base)


def bake_dark(src: str, size: tuple[int, int]) -> bytes:
    """加班暗黑背景：模糊压暗 + 8% 暗红（三主题通用）。"""
    base = _fit(src, size).filter(ImageFilter.GaussianBlur(10))
    base = Image.blend(base, Image.new("RGB", size, (0, 0, 0)), 0.58)
    return _png_bytes(Image.blend(base, Image.new("RGB", size, (60, 0, 0)), 0.08))
```

导入区加 `from PIL import ImageEnhance`（并入现有 PIL import 行）。

- [ ] **步骤 4：CLI 生成三主题预烘焙背景**

`make_bg.py` 的 `main()` 替换为：

```python
def main() -> None:
    import app
    size = (app.DEFAULT_WIN_W, app.DEFAULT_WIN_H)
    lay = app.compute_layout(*size)
    src_main = os.path.join(BASE, "assets", "wallpaper.jpg")
    names = []
    for theme in app.THEMES:
        out = os.path.join(BASE, "assets", f"bg_{theme}.png")
        open(out, "wb").write(
            bake_glass(src_main, size, [lay["main"], lay["stats"]], theme))
        names.append(os.path.basename(out))
    src_exp = os.path.join(BASE, "assets", "wallpaper_exploit.jpg")
    if os.path.exists(src_exp):
        open(os.path.join(BASE, "assets", "bg_exploit.png"), "wb").write(
            bake_dark(src_exp, size))
        names.append("bg_exploit.png")
    old = os.path.join(BASE, "assets", "bg.png")
    if os.path.exists(old):
        os.remove(old)
    print(f"OK {', '.join(names)} {size}")
```

（此时 `app.THEMES` 还是旧结构、键为 mint/amber/sky → 生成的文件名暂为 bg_mint 等，任务 2 完成后重跑即正确。测试只调 `bake_glass(theme=...)`，不受影响。）

- [ ] **步骤 5：运行测试验证通过**

运行：`python test_redesign.py`
预期：`bake OK {'midnight': ..., 'glass': ..., 'paper': ...}` + `ALL OK`（midnight 平均亮度 < glass < paper）

- [ ] **步骤 6：Commit**

```bash
git add make_bg.py test_redesign.py
git commit -m "feat: three-theme background baking (midnight/paper/glass)"
```

---

### 任务 2：app.py 主题模型与迁移

**文件：**
- 修改：`app.py`（THEMES/常量/load_config/DEFAULT_CONFIG）
- 修改：`test_redesign.py`（迁移检查）

- [ ] **步骤 1：写失败测试**

`test_redesign.py` 在 `check_bake` 后追加：

```python
def check_migration():
    import app
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "config.json")
        base = dict(app.DEFAULT_CONFIG)
        for legacy, want in (("mint", "glass"), ("amber", "glass"), ("sky", "glass")):
            base["theme"] = legacy
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(base, fh)
            cfg, warn = app.load_config(p)
            assert cfg["theme"] == want, (legacy, cfg["theme"])
        base["theme"] = "nope"
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(base, fh)
        cfg, _ = app.load_config(p)
        assert cfg["theme"] == "midnight", cfg["theme"]
    print("migration OK")
```

并把 `__main__` 块改为 `check_migration(); check_bake(); print("ALL OK")`。

- [ ] **步骤 2：运行验证失败**

运行：`python test_redesign.py`
预期：migration 处 AssertionError（旧 `load_config` 对 mint 不迁移、对 nope 整表重置，断言不成立）

- [ ] **步骤 3：实现主题 token 表与迁移**

`app.py` 中 `DEFAULT_CONFIG` 的 `"theme": "mint"` 改为 `"theme": "midnight"`。

`THEMES`/`MODE_LABELS`/颜色常量块整体替换为：

```python
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
```

（旧 `INK/LABEL_INK/SUB/DLG_BG/LINE/BLUE/MENU_DISABLED/GLASS_FALLBACK` 常量保留不动——任务 3 的渲染、任务 4 的弹窗仍引用它们，任务 4 步骤 4 统一删除。）

`load_config` 签名与主题校验改为（其余不变）：

```python
def load_config(path: str | None = None) -> tuple[dict, str]:
    cfg = dict(DEFAULT_CONFIG)
    target = path or config_path()
    if not os.path.exists(target):
        return cfg, ""
    try:
        with open(target, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        ...
        loaded["theme"] = LEGACY_THEME.get(loaded["theme"], loaded["theme"])
        if loaded["theme"] not in THEMES:
            loaded["theme"] = "midnight"
        ...
```

（原 `raise ValueError("unknown theme key")` 分支删除；`open(path...)`/`os.path.exists(path)` 全改用 `target`。）

- [ ] **步骤 4：运行测试验证通过**

运行：`python test_redesign.py`
预期：`migration OK` + `bake OK` + `ALL OK`

- [ ] **步骤 5：Commit**

```bash
git add app.py test_redesign.py
git commit -m "feat: theme token model + legacy theme migration"
```

---

### 任务 3：主画布渲染重构

**文件：**
- 修改：`app.py`（scale_fonts/字体探测/_render_main/_update_display/_rebake_background/_build_ui 回退分支/_build_menu 主题菜单/_on_theme_change/_accent）

- [ ] **步骤 1：字体系统（等宽数字 + 72 上限）**

`scale_fonts` 替换为（新增 `mono` 参数与 `value_cjk`/`sub` 槽）：

```python
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
```

`PayClockApp.__init__` 中 `_build_menu()` 之前加等宽字体探测（需 root 已存在）：

```python
import tkinter.font as tkfont  # 文件顶部 import 区
fams = set(tkfont.families(root))
self._mono = ("Consolas" if "Consolas" in fams
              else "Cascadia Mono" if "Cascadia Mono" in fams else "Courier New")
```

- [ ] **步骤 2：token 取色与渲染重写（删 8 向描边）**

`_accent` 替换为：

```python
def _tokens(self) -> dict:
    key = self.cfg["theme"] if self.cfg["theme"] in THEMES else "midnight"
    return THEMES[key]
```

`_render_main` 整体替换为（`ht()` 描边辅助删除）：

```python
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
                  width=self._win_w - 2 * lay["margin"])
```

`_render_exploit` 不变（红字常量保留），仅 `scale_fonts(w)` 调用改为 `scale_fonts(w, self._mono)`。

- [ ] **步骤 3：数值文案与占位恢复**

`_update_display` 中三处改动：

```python
ic("today", font=scale_fonts(self._win_w, self._mono)["huge"])  # 从占位态恢复大字号
...
ic("sv0", text=f"{month_earned:,.2f}")            # 原 f"{month_earned:,.2f} 元"
ic("sv2", text=f"{self.pss:.4f}")                 # 原 f"{self.pss:.4f} 元/秒"
```

（单位已移入标签「本月已赚（元）/ 秒薪（元）」；`sv1` 的 "3 天"/"今天发薪" 不变。）

- [ ] **步骤 4：烘焙调用带主题 + 回退背景按主题加载**

`_rebake_background` 中：

```python
data = make_bg.bake_glass(src, (w, h), [lay["main"], lay["stats"]],
                          self.cfg["theme"] if self.cfg["theme"] in THEMES else "midnight")
```

（`lay = compute_layout(w, h)` 移到 if/else 之前共用——原代码只在 else 分支算。）

`_build_ui` 无 Pillow 回退分支中：

```python
bg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "assets", f"bg_{self.cfg['theme'] if self.cfg['theme'] in THEMES else 'midnight'}.png")
```

（替换原 `bg.png` 行；文件不存在时保持 `self._bg_photo = None` 走兜底色。）

`_on_theme_change` 尾部（保存成功后）追加无 Pillow 分支的背景重载：

```python
if self.overtime_start is None:
    if not self._can_resize_bg:
        self._reload_fallback_bg()
    self._render_main()
    self._update_display(datetime.now())
```

新增方法（`_rebake_background` 后）：

```python
def _reload_fallback_bg(self) -> None:
    """无 Pillow 回退：按主题重载预烘焙背景。"""
    key = self.cfg["theme"] if self.cfg["theme"] in THEMES else "midnight"
    bg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "assets", f"bg_{key}.png")
    if os.path.exists(bg_path):
        self._bg_photo = tk.PhotoImage(file=bg_path)
        self._bg_size = (self._bg_photo.width(), self._bg_photo.height())
```

（`_build_ui` 回退分支改为直接调 `self._reload_fallback_bg()` + 按其尺寸设 geometry，消除重复。）

- [ ] **步骤 5：主题菜单三选项**

`_build_menu` 中：`apple_menu` 的颜色改从 token 取（`master` 之外新增 `t` 参数或直接读 `self._tokens()`，注意 `__init__` 里 `_build_menu` 在 cfg 加载后调用，可用）；主题循环替换为：

```python
for key in THEMES:
    m_theme.add_radiobutton(label=THEMES[key]["label"], value=key,
                            variable=self.theme_var, command=self._on_theme_change)
```

`self.theme_var` 初值：`self.cfg["theme"] if self.cfg["theme"] in THEMES else "midnight"`。菜单/子菜单对象各存引用（`self._menu_bar / self._theme_menu / self._menu_set`）供任务 4 换肤。

- [ ] **步骤 6：冒烟运行**

运行：`python test_redesign.py` → `ALL OK`；`python app.py`（人工看一眼三主题切换、缩放、数字不抖）。
预期：窗口正常显示、主题菜单三项可切换、切换即重烘焙。

- [ ] **步骤 7：Commit**

```bash
git add app.py
git commit -m "feat: themed canvas render, mono digits, no text halo"
```

---

### 任务 4：弹窗与菜单 token 化

**文件：**
- 修改：`app.py`（_make_spin/_time_picker/_open_settings/_open_ask_dialog/_restyle_menu）

- [ ] **步骤 1：菜单随主题换肤**

`_build_menu` 尾部与 `_on_theme_change` 中各调一次：

```python
def _restyle_menu(self) -> None:
    t = self._tokens()
    for m in (self._menu_bar, self._menu_set, self._theme_menu):
        if m is not None:
            m.configure(bg=t["menu_bg"], fg=t["menu_fg"],
                        activebackground=t["menu_active_bg"],
                        activeforeground=t["menu_active_fg"],
                        disabledforeground=t["menu_disabled"])
```

（`apple_menu()` 内部静态色删除，创建后统一 `_restyle_menu()`。）

- [ ] **步骤 2：设置弹窗换肤**

`_open_settings`/`_make_spin`/`_time_picker`/`_time_picker` 内所有 `DLG_BG/INK/SUB/LINE/BLUE/#E9E9EB/#FFFFFF` 字面色替换为 token：

- 弹窗与表单底：`t = self._tokens()` → `dlg.configure(bg=t["dlg_bg"])`、`tk.Frame(..., bg=t["dlg_bg"])`、标签 `fg=t["ink"]`；
- 月薪 Entry / Spinbox：`bg=t["field_bg"], fg=t["field_fg"], insertbackground=t["field_fg"], highlightbackground=t["line"], highlightcolor=t["accent"], buttonbackground=t["btn2_bg"]`；
- 「显示」Checkbutton：`bg=t["dlg_bg"], fg=t["sub"], activebackground=t["dlg_bg"], activeforeground=t["sub"]`；
- 保存按钮：`bg=t["btn_bg"], fg=t["btn_fg"], activebackground=t["btn_active"], activeforeground=t["btn_fg"]`；
- 错误标签：`fg=t["err"]`。

`_make_spin`/`_time_picker` 增加 `t: dict` 参数（调用处传 `self._tokens()`），内部同上取色。

- [ ] **步骤 3：下班询问弹窗换肤**

`_open_ask_dialog`：底 `t["dlg_bg"]`、标题 `t["ink"]`、「加班」= 主按钮 token、「不加班」= `btn2_bg/btn2_fg`（active 用同色系加深：`btn_active`/btn2 无 active token 时直接沿用 `btn2_bg`，加 `activebackground=t["btn2_bg"]`）。

- [ ] **步骤 4：确认结束加班按钮与收尾**

`_render_exploit` 的「结束加班」按钮保持 `EXPLOIT_ACCENT` 暗红底白字（规格 §4.4，不动）。
删除已无引用的旧颜色常量（若任务 2 临时保留的话）：`INK/LABEL_INK/SUB/DLG_BG/LINE/BLUE/MENU_DISABLED/GLASS_FALLBACK`（先 `grep -n "INK\|DLG_BG\|BLUE\|GLASS_FALLBACK" app.py` 确认零引用）。

- [ ] **步骤 5：冒烟 + 测试**

运行：`python test_redesign.py` → `ALL OK`；`python app.py` 逐主题打开设置弹窗与下班询问（把系统时间临时调过下班点或等真下班）检查可读性。

- [ ] **步骤 6：Commit**

```bash
git add app.py
git commit -m "feat: themed dialogs and menus via token"
```

---

### 任务 5：资产、文档与回归

**文件：**
- 修改：`README.md`
- 生成：`assets/bg_midnight.png / bg_paper.png / bg_glass.png / bg_exploit.png`
- 删除：`assets/bg.png`

- [ ] **步骤 1：重新生成资产**

```bash
python make_bg.py
```
预期输出：`OK bg_midnight.png, bg_paper.png, bg_glass.png, bg_exploit.png (348, 452)`；`assets/bg.png` 已被删除。

- [ ] **步骤 2：README 主题表更新**

「主题（3 + 1）」表替换为：

```markdown
## 主题（3 + 1）

| 主题 | 说明 |
|---|---|
| midnight 暗夜玻璃 | 默认；壁纸压暗 + 暗玻璃面板，冰蓝数字 #7DB8FF |
| paper 纯净亮色 | 壁纸强白化 + 近实白卡片，天空蓝数字 #0A84FF |
| glass 经典白玻璃 | 白玻璃面板 + 深蓝数字 #0066D6；旧 mint/amber/sky 配置自动迁移到本主题 |
| exploit 暗黑压榨 | 仅加班期间强制生效（红字黑底），与主题选择无关，点「结束加班」恢复 |
```

README 其余提及「薄荷绿/暖阳橙/天空蓝」处（简介、config 表 `theme` 行）同步改为三主题说法；「更换壁纸」一节的 `python make_bg.py` 说明改为生成三主题文件。

- [ ] **步骤 3：回归**

```bash
python money.py        # 预期 72 asserts OK
python test_redesign.py  # 预期 ALL OK
```

- [ ] **步骤 4：手动验收清单**

1. 三主题各切换一次并重启程序，主题保持；
2. 用旧 theme=mint 的 config 启动 → 自动落在「经典白玻璃」；
3. 每主题下主窗口/设置弹窗文字可读（含报错文案）；
4. 拖拽缩放窗口 → 松手重烘焙，面板与文字不错位、无描边光晕残留；
5. 进入加班（时间调过下班点）→ 暗红压榨画布；结束加班 → 恢复当前主题；
6. free 模式下「标记今天休息」菜单三主题均可用。

- [ ] **步骤 5：Commit**

```bash
git add README.md assets/
git commit -m "docs: three-theme readme + regenerated assets"
```
