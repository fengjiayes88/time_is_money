"""make_bg.py — 背景烘焙工具（壁纸 → 毛玻璃/暗黑背景 PNG）。

- CLI：`python make_bg.py` 按默认窗口尺寸重新生成 assets/bg.png 与 assets/bg_exploit.png；
- app.py 在窗口缩放时会实时调用 bake_glass()/bake_dark() 重烘焙（防抖后触发），
  因此「任意拖动缩放」需要 Pillow；未安装时 app 回退为固定尺寸 + 预生成背景。
"""

import io
import os

from PIL import Image, ImageDraw, ImageFilter, ImageOps

BASE = os.path.dirname(os.path.abspath(__file__))

# —— 主界面玻璃参数 ——
BLUR = 5            # 毛玻璃模糊半径（低值 = 壁纸图案透出更清晰）
GLASS_WHITE = 0.12  # 玻璃白色叠加强度（越低越透明）
RADIUS = 24          # 面板圆角
SCRIM_TOP = 150      # 顶部暗色渐变高度（保证白色标题可读）
SCRIM_BOTTOM = 120   # 底部暗色渐变高度（保证状态行可读）
SCRIM_ALPHA = 110    # 渐变最深处透明度（0-255）

# —— 加班暗黑参数 ——
DARK_BLUR = 10       # 暗黑模式模糊半径
DARK_ALPHA = 0.58    # 暗黑模式整体压暗强度（0-1）


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    # compress_level=1：编码速度优先（实时重烘焙用），体积换速度
    img.save(buf, format="PNG", compress_level=1)
    return buf.getvalue()


def _fit(src: str, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(Image.open(src).convert("RGB"), size)


def _add_scrims(img: Image.Image) -> None:
    """图顶/底叠加黑色→透明渐变，让浮在照片区的白字/状态字可读。"""
    w, h = img.size
    overlay = Image.new("L", (1, h), 0)
    px = overlay.load()
    for y in range(min(SCRIM_TOP, h)):
        px[0, y] = int(SCRIM_ALPHA * (1 - y / SCRIM_TOP))
    for y in range(min(SCRIM_BOTTOM, h)):
        px[0, h - 1 - y] = int(SCRIM_ALPHA * (1 - y / SCRIM_BOTTOM))
    overlay = overlay.resize((w, h))
    img.paste(Image.new("RGB", (w, h), (0, 0, 0)), (0, 0), overlay)


def bake_glass(src: str, size: tuple[int, int],
               panels: list[tuple[int, int, int, int]]) -> bytes:
    """主界面背景：壁纸 + 顶底渐变 + 毛玻璃面板（模糊 + 白色叠加 + 高光描边）。"""
    base = _fit(src, size)
    _add_scrims(base)
    glass = Image.blend(base.filter(ImageFilter.GaussianBlur(BLUR)),
                        Image.new("RGB", base.size, (255, 255, 255)),
                        GLASS_WHITE)
    mask = Image.new("L", base.size, 0)
    d = ImageDraw.Draw(mask)
    for box in panels:
        d.rounded_rectangle(box, radius=RADIUS, fill=255)
    base.paste(glass, (0, 0), mask)
    outline = ImageDraw.Draw(base)  # 玻璃边缘 1px 高光
    for box in panels:
        outline.rounded_rectangle(box, radius=RADIUS,
                                  outline=(255, 255, 255), width=1)
    return _png_bytes(base)


def bake_dark(src: str, size: tuple[int, int]) -> bytes:
    """加班暗黑背景：壁纸模糊 + 整体压暗（保持暗黑压榨氛围）。"""
    base = _fit(src, size).filter(ImageFilter.GaussianBlur(DARK_BLUR))
    return _png_bytes(Image.blend(base, Image.new("RGB", size, (0, 0, 0)),
                                  DARK_ALPHA))


def main() -> None:
    import app  # 布局比例的唯一来源（CLI 延迟导入，避免与 app 的懒加载成环）
    size = (app.DEFAULT_WIN_W, app.DEFAULT_WIN_H)
    lay = app.compute_layout(*size)
    src_main = os.path.join(BASE, "assets", "wallpaper.jpg")
    src_exp = os.path.join(BASE, "assets", "wallpaper_exploit.jpg")
    open(os.path.join(BASE, "assets", "bg.png"), "wb").write(
        bake_glass(src_main, size, [lay["main"], lay["stats"]]))
    if os.path.exists(src_exp):
        open(os.path.join(BASE, "assets", "bg_exploit.png"), "wb").write(
            bake_dark(src_exp, size))
        print(f"OK assets/bg.png + assets/bg_exploit.png {size}")
    else:
        print(f"OK assets/bg.png {size}（缺 assets/wallpaper_exploit.jpg，未生成暗黑背景）")


if __name__ == "__main__":
    main()
