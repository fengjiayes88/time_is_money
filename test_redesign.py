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
        # 平均亮度 = 各通道像素值总和 / 像素数（histogram 无 getdata 废弃告警）
        hist = img.histogram()  # RGB: 256 bin × 3 通道
        avgs[theme] = sum((i % 256) * n for i, n in enumerate(hist)) \
            / (size[0] * size[1] * 3)
    assert avgs["midnight"] < avgs["glass"] < avgs["paper"], avgs
    print("bake OK", {k: round(v) for k, v in avgs.items()})


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
        base["theme"] = ["midnight"]  # 不可哈希 JSON 值：应回退 midnight 而非 TypeError 穿透
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(base, fh)
        cfg, _ = app.load_config(p)
        assert cfg["theme"] == "midnight", cfg["theme"]
    print("migration OK")


def check_theme_key():
    """_theme_key() 直接断言：合法键透传，任意非法字符串/None 回退 midnight。

    仅读 self.cfg["theme"]，用桩对象免建 Tk 实例。入参不变式由 load_config
    归一化保证（不可哈希 JSON 值已在 migration 检查中覆盖，不进本契约）。
    """
    import app

    class _Stub:
        cfg = {}

    stub = _Stub()
    cases = (
        ("midnight", "midnight"),
        ("paper", "paper"),
        ("glass", "glass"),
        ("mint", "midnight"),   # 旧键在运行期不再映射（仅 load_config 迁移）
        ("nope", "midnight"),
        (None, "midnight"),
        ("", "midnight"),
    )
    for value, want in cases:
        stub.cfg["theme"] = value
        got = app.PayClockApp._theme_key(stub)
        assert got == want, (value, got, want)
    print("theme_key OK")


if __name__ == "__main__":
    check_migration()
    check_theme_key()
    check_bake()
    print("ALL OK")
