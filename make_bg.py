"""make_bg.py — 背景烘焙工具（壁纸 → 毛玻璃/暗黑背景 PNG）。

- CLI：`python make_bg.py` 按默认窗口尺寸重新生成 assets/bg_midnight.png / bg_paper.png /
  bg_glass.png 与 assets/bg_exploit.png；
- app.py 在窗口缩放时会实时调用 bake_glass()/bake_dark() 重烘焙（防抖后触发），
  因此「任意拖动缩放」需要 Pillow；未安装时 app 回退为固定尺寸 + 预生成背景。
"""

import io
import os

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

BASE = os.path.dirname(os.path.abspath(__file__))

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


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    # compress_level=1：编码速度优先（实时重烘焙用），体积换速度
    img.save(buf, format="PNG", compress_level=1)
    return buf.getvalue()


def _fit(src: str, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(Image.open(src).convert("RGB"), size)


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


def _paste_panel(base: Image.Image, glass: Image.Image, box, p: dict,
                 radius: int = RADIUS) -> None:
    mask = Image.new("L", base.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
    if "shadow_alpha" in p:  # paper：面板下柔和投影
        sh = Image.new("L", base.size, 0)
        ImageDraw.Draw(sh).rounded_rectangle(
            (box[0], box[1] + 6, box[2], box[3] + 6), radius=radius, fill=p["shadow_alpha"])
        sh = sh.filter(ImageFilter.GaussianBlur(12))
        base.paste(Image.new("RGB", base.size, (20, 24, 34)), (0, 0), sh)
    base.paste(glass, (0, 0), mask)
    d = ImageDraw.Draw(base)
    d.rounded_rectangle(box, radius=radius, outline=p["edge"], width=1)
    if "hilite" in p:  # 上缘内高光（x 两端内收 radius，y = 面板顶 +2）
        d.line((box[0] + radius, box[1] + 2, box[2] - radius, box[1] + 2),
               fill=p["hilite"], width=1)


def bake_glass(src: str, size: tuple[int, int],
               panels: list[tuple[int, int, int, int]],
               theme: str = "glass", fast: bool = False) -> bytes:
    """主界面背景：按主题烘焙三套材质之一。

    fast=True 走 1/3 线性尺度快速管线（拖动实时预览用），结果双线性放大、
    1px 描边在全尺寸补画；停稳后的全质量烘焙用默认 fast=False。
    """
    w, h = size
    S = 3 if fast else 1
    if S > 1:
        size = (max(RADIUS, w // S), max(RADIUS, h // S))
        panels = [(x0 // S, y0 // S, x1 // S, y1 // S) for x0, y0, x1, y1 in panels]
    p = THEME_BAKE[theme]
    base = _fit(src, size)
    if theme == "midnight":
        base = ImageEnhance.Brightness(base).enhance(p["brightness"])
        _radial_vignette(base, p["vignette_alpha"])
        glass = base.filter(ImageFilter.GaussianBlur(max(2, p["panel_blur"] // S)))
    elif theme == "paper":
        base = base.filter(ImageFilter.GaussianBlur(max(2, p["blur"] // S)))
        base = Image.blend(base, Image.new("RGB", size, (255, 255, 255)), p["wash"])
        glass = base
    else:  # glass
        _band_scrims(base, p["top_bottom_alpha"])
        glass = base.filter(ImageFilter.GaussianBlur(max(2, p["panel_blur"] // S)))
    glass = Image.blend(glass, Image.new("RGB", size, p["tint"]),
                        p["tint_alpha"] / 255)
    radius = max(4, RADIUS // S)
    for box in panels:
        _paste_panel(base, glass, box, p, radius)
    if S > 1:
        base = base.resize((w, h), Image.BILINEAR)
        d = ImageDraw.Draw(base)  # 1px 描边在全尺寸补画，避免放大发虚
        for x0, y0, x1, y1 in panels:
            d.rounded_rectangle((x0, y0, x1, y1), radius=RADIUS,
                                outline=p["edge"], width=1)
    return _png_bytes(base)


def bake_dark(src: str, size: tuple[int, int]) -> bytes:
    """加班暗黑背景：模糊压暗 + 8% 暗红（三主题通用）。"""
    base = _fit(src, size).filter(ImageFilter.GaussianBlur(10))
    base = Image.blend(base, Image.new("RGB", size, (0, 0, 0)), 0.58)
    return _png_bytes(Image.blend(base, Image.new("RGB", size, (60, 0, 0)), 0.08))


def main() -> None:
    import app  # 布局比例的唯一来源（CLI 延迟导入，避免与 app 的懒加载成环）
    size = (app.DEFAULT_WIN_W, app.DEFAULT_WIN_H)
    lay = app.compute_layout(*size)
    src_main = os.path.join(BASE, "assets", "wallpaper.jpg")
    names = []
    for theme in app.THEMES:
        if theme not in THEME_BAKE:
            continue  # 过渡期 app.THEMES 可能还是旧键（键迁移后不再发生）
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
    if names and any(n.startswith("bg_") and n != "bg_exploit.png"
                     for n in names) and os.path.exists(old):
        os.remove(old)  # 只有生成过主题替代文件才退役旧背景
    print(f"OK {', '.join(names)} {size}")


if __name__ == "__main__":
    main()
