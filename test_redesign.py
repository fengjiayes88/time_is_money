"""test_redesign.py — 重设计自检：主题迁移 + tag 契约 + 压榨流程。运行：python test_redesign.py"""
import json
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def check_migration():
    import app
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "config.json")
        base = dict(app.DEFAULT_CONFIG)
        for legacy, want in (("midnight", "dark"), ("paper", "light"),
                             ("glass", "light"), ("mint", "light"),
                             ("amber", "light"), ("sky", "light")):
            base["theme"] = legacy
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(base, fh)
            cfg, warn = app.load_config(p)
            assert cfg["theme"] == want, (legacy, cfg["theme"])
        base["theme"] = "nope"
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(base, fh)
        cfg, _ = app.load_config(p)
        assert cfg["theme"] == "dark", cfg["theme"]
        base["theme"] = ["dark"]  # 不可哈希 JSON 值：应回退 dark 而非 TypeError 穿透
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(base, fh)
        cfg, _ = app.load_config(p)
        assert cfg["theme"] == "dark", cfg["theme"]
    print("migration OK")


def check_theme_key():
    """_theme_key() 直接断言：合法键透传，任意非法字符串/None 回退 dark。

    仅读 self.cfg["theme"]，用桩对象免建 Tk 实例。入参不变式由 load_config
    归一化保证（不可哈希 JSON 值已在 migration 检查中覆盖，不进本契约）。
    """
    import app

    class _Stub:
        cfg = {}

    stub = _Stub()
    cases = (
        ("dark", "dark"),
        ("light", "light"),
        ("midnight", "dark"),      # 旧键在运行期不再映射，回退默认 dark（仅 load_config 迁移）
        ("nope", "dark"),
        (None, "dark"),
        ("", "dark"),
    )
    for value, want in cases:
        stub.cfg["theme"] = value
        got = app.PayClockApp._theme_key(stub)
        assert got == want, (value, got, want)
    print("theme_key OK")


def check_config_validation():
    """config 信任边界：NaN 月薪与非当前模式 leaves 非法数据必须触发整表重置。"""
    import app
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "config.json")

        def write(mutate):
            data = json.loads(json.dumps(app.DEFAULT_CONFIG))
            mutate(data)
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(data, fh)  # allow_nan 默认 True：可落盘 NaN 字面量

        def bad_other_mode(data):
            data["holiday_mode"] = "free"
            data["leaves"] = {"weekend": {"2026-9-8": "调休"}, "free": {}}

        def bad_other_mode_value(data):
            data["holiday_mode"] = "free"
            data["leaves"] = {"weekend": {"2026-09-08": "病假"}, "free": {}}

        for name, mutate in (("NaN 月薪", lambda d: d.update(monthly_salary=float("nan"))),
                             ("异模式非法键", bad_other_mode),
                             ("异模式非法值", bad_other_mode_value)):
            write(mutate)
            cfg, warn = app.load_config(p)
            assert warn, f"{name} 应触发整表重置"
    print("config validation OK")


def check_tags_contract():
    """渲染层与更新层的 tag 契约：_update_display/_set_status 引用的 tag 必须真实存在。"""
    import tkinter as tk
    import app
    root = tk.Tk()
    root.withdraw()
    result = {}

    def probe():
        try:
            appv = app.PayClockApp(root)
            appv._update_display(datetime.now())
            appv._set_status("selftest")  # status 占据 date 行，先写一条再验契约
            for tag in ("date", "cap", "amt_int", "cd", "mark_c",
                        "sl0", "sl1", "sl2", "sv0", "sv1", "sv2"):
                assert appv.canvas.find_withtag(tag), f"tag 缺失: {tag}"
                assert appv.canvas.itemcget(tag, "text") != "", f"tag 内容为空: {tag}"
            assert appv.canvas.find_withtag("amt_dec"), "tag 缺失: amt_dec"
            assert appv.canvas.itemcget("amt_dec", "text").startswith("."), "小数部应以点开头"
            assert appv._status_msg == "selftest"
            appv._clear_status()
            assert appv.canvas.itemcget("date", "text") != ""  # 清除后恢复日期行
            result["ok"] = True
        except Exception as e:
            result["err"] = e
        finally:
            root.destroy()

    root.after(300, probe)  # 在首个 tick(1000ms) 前探针并销毁，不触发下班询问
    root.mainloop()
    if "err" in result:
        raise AssertionError(f"tag 契约失败: {result['err']}")
    print("tags contract OK")


def check_exploit_flow():
    """压榨流程：接受加班 → 红色压榨画布（cap 换语义 + 结束按钮），
    结束加班回主画布；全程不依赖背景烘焙。"""
    from datetime import datetime
    import tkinter as tk
    import app
    app.save_config = lambda cfg: True
    app.winsound.PlaySound = lambda *a, **k: None
    root = tk.Tk()
    root.withdraw()
    try:
        appv = app.PayClockApp(root)
        appv._on_accept_overtime()
        assert appv.overtime_start is not None
        assert appv.canvas.itemcget("cap", "text") == "老板压榨金额（元）", "应渲染压榨画布"
        assert appv._end_btn is not None, "结束加班按钮应存在"
        appv._update_display(datetime.now())  # 压榨分支更新不得异常/冻结
        over = app.money.overtime_seconds(
            datetime.now(), appv.cfg["work_end"], appv.overtime_start)
        assert over >= 0
        appv._on_end_overtime()
        assert appv.overtime_start is None
        assert appv.canvas.itemcget("cap", "text") == "今日已赚（元）", "结束加班应回主画布"
    finally:
        root.destroy()
    print("exploit flow OK")


def check_dpi_font_proportion():
    """DPI 修复回归：字号按逻辑宽度取值，scale≠1 时与 100% 版式比例一致。"""
    import tkinter as tk
    import app
    root = tk.Tk()
    root.withdraw()
    try:
        appv = app.PayClockApp(root)
        base = appv._make_fonts()
        appv._fonts = None
        appv._scale = 1.25
        appv._win_w = round(app.DEFAULT_WIN_W * 1.25)
        appv._win_h = round(app.DEFAULT_WIN_H * 1.25)
        scaled = appv._make_fonts()
        for key in ("int", "dec", "date", "cap", "cd", "stat_value"):
            assert base[key][1] == scaled[key][1], (key, base[key], scaled[key])
    finally:
        root.destroy()
    print("dpi font proportion OK")


def check_save_blocks_cross_mode_brick():
    """保存点校验两模式：异模式 leaves 吃光应出勤天数必须拒绝保存
    （否则重启时 load_config 整表重置，连月薪一起丢）。"""
    from datetime import date
    import tkinter as tk
    import app
    import money
    saved = []
    app.save_config = lambda cfg: (saved.append(cfg), True)[1]
    root = tk.Tk()
    root.withdraw()
    try:
        appv = app.PayClockApp(root)
        appv._open_settings()
        # 当前模式 free；把 weekend 组所有工作日标成调休 → weekend D=0
        y, m = date.today().year, date.today().month
        wds = [d.isoformat()
               for d in (date(y, m, i) for i in range(1, money.month_days(y, m) + 1))
               if money.is_workday(d, {}, "weekend")]
        appv._mode_var.set("free")
        appv._leaves_draft["weekend"] = {d: "调休" for d in wds}
        appv._on_save(appv.settings_dialog)
        assert saved == [], "异模式 D=0 必须拒绝保存"
        assert appv.settings_dialog.winfo_exists(), "失败时设置弹窗应保留"
        assert "保存失败" in appv._dlg_status.cget("text")
        # 清掉后应能正常保存
        appv._leaves_draft["weekend"] = {}
        appv._on_save(appv.settings_dialog)
        assert saved, "合法配置应保存成功"
    finally:
        root.destroy()
    print("cross-mode brick guard OK")


def check_overtime_button_no_leak():
    """加班视图缩放重渲染不泄漏 Button 控件（canvas.delete 不销毁 widget）。"""
    import tkinter as tk
    import app
    app.save_config = lambda cfg: True
    app.winsound.PlaySound = lambda *a, **k: None
    root = tk.Tk()
    root.withdraw()
    try:
        appv = app.PayClockApp(root)
        appv._on_accept_overtime()
        for _ in range(50):
            appv._render()
        kids = appv.canvas.winfo_children()
        assert len(kids) == 1, f"应只有 1 个按钮，实际 {len(kids)}"
        appv._on_end_overtime()
        for _ in range(10):
            appv._render()
        assert len(appv.canvas.winfo_children()) == 1, "退出后也不应再增加"
    finally:
        root.destroy()
    print("overtime button no-leak OK")


def check_tick_error_surfaces():
    """tick 异常不再静默：状态行给出提示，恢复后自动撤下。"""
    import tkinter as tk
    import app
    root = tk.Tk()
    root.withdraw()
    try:
        appv = app.PayClockApp(root)
        good = appv.cfg["work_start"]
        appv.cfg["work_start"] = "9:00"  # 非法 HH:MM：每 tick 均在 money 层抛 ValueError
        appv._tick()
        assert appv._status_msg == app._TICK_ERROR, appv._status_msg
        appv.cfg["work_start"] = good
        appv._tick()
        assert appv._status_msg is None, "恢复后提示应撤下"
        assert appv._tick_errored is False
    finally:
        root.destroy()
    print("tick error surfacing OK")


if __name__ == "__main__":
    check_migration()
    check_theme_key()
    check_config_validation()
    check_tags_contract()
    check_exploit_flow()
    check_dpi_font_proportion()
    check_save_blocks_cross_mode_brick()
    check_overtime_button_no_leak()
    check_tick_error_surfaces()
    print("ALL OK")
