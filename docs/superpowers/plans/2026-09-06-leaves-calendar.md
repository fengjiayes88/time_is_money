# 休假类型（调休/请假）+ 设置日历 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 休假标记升级为「调休/请假」双类型（leaves 字典，两种模式通用），设置弹窗加当月日历多选控件，调休重算秒薪、请假扣日薪并在倒计时下方显示损失。

**架构：** money.py 公式层从「假期数值」改为「leaves 字典」驱动（D = base − 调休数，请假不进分母），新增 `daily_salary`；app.py 数据层迁移 + 菜单子菜单 + 日历控件 + sub 行优先级显示。

**技术栈：** Python 3.11 stdlib（tkinter / calendar / datetime），零第三方依赖。

**规格：** `docs/superpowers/specs/2026-09-06-leaves-calendar-design.md`（§2 计薪语义表是本计划的最高准绳）

**全局约束（逐字）：**
- 调休：当天 0 收入，D = base − 调休数（秒薪重算），月底实收 = 月薪；
- 请假：当天 0 收入，**D 不变**（秒薪不动），月底实收 = 月薪 − 日薪 × 请假数，日薪 = 月薪 ÷ D；
- leaves 两种模式通用，只保留当月；`free_holidays` 迁移为调休；`monthly_holidays` 退役；
- weekend 模式周末格不可标（周末本就休息，防错误扣钱）；
- 日历点选草稿制：保存设置才生效；
- 秒薪按整月重算（改 leaves 影响当月全部已过日期的已赚累计）。

---

## 文件结构

- 修改：`money.py` — 公式层（is_workday/month_paid_days/per_second_salary/validate 换 leaves 签名 + 新增 daily_salary）+ 自检断言重写
- 修改：`app.py` — config 迁移、缓存、菜单子菜单、sub 行显示、设置日历控件
- 修改：`README.md` — 公式/配置表/自检数/菜单说明
- 不动：`make_bg.py`、`test_redesign.py`（回归网）、`assets/`

---

### 任务 0：分支

- [ ] `git checkout -b feat/leaves-calendar`（自 main @ 1d0ac02）

---

### 任务 1：money.py 公式层（TDD，先改断言）

**文件：** 修改 `money.py`

- [ ] **步骤 1：重写自检断言（RED）**

`__main__` 自检整体重写。新基准：10000 元，2024-06（30 天，周末 10 天，base=20），09:00–18:00（32400 秒/日）。逐节要点：

- §A 基础：`month_paid_days(2024,6,{})`（weekend）= 20；`per_second_salary(10000,2024,6,{},"09:00","18:00")` ≈ 10000/(20×32400)；
- §B 调休：leaves = `{"2024-06-05":"调休","2024-06-06":"调休"}` → D=18，秒薪 ≈ 10000/(18×32400)（等于旧 holidays=2 的数值）；`is_workday(date(2024,6,5), leaves)` False；
- §C 请假：leaves = 5 个请假 ISO（如 6/10–6/14）→ `month_paid_days` 仍 20；`is_workday` 全 False；日薪 = `daily_salary(10000,2024,6,leaves,...)` ≈ 10000/20 = 500；`earned_this_month(pss, datetime(2024,6,30,18,0), ...)` ≈ 10000×15/20 = 7500（损失 2500 = 日薪×5）；
- §D free 模式：`month_paid_days(2024,6,{},"free")` = 30；周末未标 = 工作日（is_workday(6/1, {}, "free") True）；标 2 天调休 → D=28；标周六请假 → 该周六 False 且 D=29；
- §E 混合：调休 2 + 请假 3（不同日期）→ D=18；is_workday 全 False；月底实收 = 10000×15/18；
- §F validate：合法 leaves → `[]`；`leaves="x"` 报错；`{"2024-06-05":"病假"}` 报错；`{"2024-6-5":"调休"}`（非两位/无零填充 ISO）报错；调休吃满一个月（2023-02 全部 base 天）→ D≤0 报错；payday/salary/时间旧规则保留（各一条）；
- §G 保留回归：A4 发薪日 clamp、A5 截断边界、A8 加班、月天数/周末数基础函数——把原断言中的 `holidays=2` 改为 `leaves={}`、`free_holidays` 改为 leaves dict，期望值相应改（如 §5.1 原期望 18 天 → 新基准 20 天）。

- [ ] **步骤 2：运行确认失败**

运行：`python money.py`
预期：断言失败（旧签名 holidays int）

- [ ] **步骤 3：实现新公式层**

模块头 `__all__` 增加 `"daily_salary"`、`"LEAVE_TYPES"`；常量 `LEAVE_TYPES = ("调休", "请假")`。

```python
def _month_leave_count(y: int, m: int, leaves, leave_type: str) -> int:
    """当月指定类型的休假日数（key 非当月字符串或 value 非法的条目忽略）。"""
    if not isinstance(leaves, dict):
        return 0
    prefix = f"{y:04d}-{m:02d}-"
    return sum(1 for k, v in leaves.items()
               if isinstance(k, str) and k.startswith(prefix) and v == leave_type)


def is_workday(d: date, leaves=None, mode: str = "weekend") -> bool:
    """工作日判定：任何休假日（调休/请假）→ False；
    weekend：周一至周五；free：周末照常上班（A1/A1b）。"""
    if isinstance(leaves, dict) and leaves.get(d.isoformat()) in LEAVE_TYPES:
        return False
    if mode == "free":
        return True
    return d.weekday() < 5


def month_paid_days(y: int, m: int, leaves, mode: str = "weekend") -> int:
    """当月应出勤天数 D（规格 §2）：base − 调休数。
    调休进分母（重算秒薪），请假不进（扣日薪语义）。
    base：weekend = 月天数 − 周末数；free = 月天数。"""
    leaves = leaves if isinstance(leaves, dict) else {}
    t = _month_leave_count(y, m, leaves, "调休")
    if mode == "free":
        return month_days(y, m) - t
    return month_days(y, m) - month_weekend_days(y, m) - t


def daily_salary(salary, y: int, m: int, leaves, start_hm: str, end_hm: str,
                 mode: str = "weekend") -> float:
    """日薪 = 月薪 / D（= 秒薪 × 日工作秒数）。"""
    return per_second_salary(salary, y, m, leaves, start_hm, end_hm, mode) \
        * daily_work_seconds(start_hm, end_hm)
```

`per_second_salary` 参数 `holidays: int` → `leaves`，分母用 `month_paid_days(y, m, leaves, mode)`，错误文案改「应出勤天数 ≤ 0」。`today_paid_seconds` / `earned_today` / `month_paid_seconds` / `earned_this_month` 的 `free_holidays=frozenset()` 参数改为 `leaves=None`，传给 `is_workday`。

`validate(salary, start_hm, end_hm, leaves, payday, mode="weekend", today=None)`：
- 删除 holidays 数值校验；
- 新增：`leaves` 非 dict → 「leaves 必须是字典」；逐条：key 非 str 或 `date.fromisoformat(k)` 抛错 → 「leaves 日期键必须是 ISO 日期：{k!r}」；value 不在 `LEAVE_TYPES` → 「leaves 类型必须是 调休/请假：{k!r}」；
- A2 检查：相邻三月 `month_paid_days(y, m, leaves, mode) <= 0` → 报错（leaves 非 dict 时传 `{}` 只查 base）。

模块 docstring 语义锚点同步（A1b 改述、A2 改为「调休进分母/请假扣日薪」、新增日薪锚点）。

- [ ] **步骤 4：运行验证通过**

运行：`python money.py`
预期：全部断言 OK（数量 = 重写后实际值，记录之）

- [ ] **步骤 5：Commit**

```bash
git add money.py && git commit -m "feat!: leave types (调休/请假) drive salary math via leaves dict"
```

---

### 任务 2：config 迁移 + 数据层

**文件：** 修改 `app.py`

- [ ] **步骤 1：DEFAULT_CONFIG 与迁移**

`DEFAULT_CONFIG` 删除 `"monthly_holidays"`、`"free_holidays"`，新增 `"leaves": {}`（放在 `holiday_mode` 之后）。`load_config` 在 money.validate 调用前迁移：

```python
        loaded["leaves"] = {}
        for d in (data.get("free_holidays") or []):  # 旧自由假日 → 调休
            if isinstance(d, str):
                loaded["leaves"][d] = "调休"
        if isinstance(data.get("leaves"), dict):      # 新字段优先
            loaded["leaves"].update(data["leaves"])
```

`money.validate(loaded["monthly_salary"], loaded["work_start"], loaded["work_end"], loaded["leaves"], loaded["payday"], loaded["holiday_mode"])`（参数随新签名）。

- [ ] **步骤 2：月度缓存与标记动作**

`__init__` 加 `self.daily = 0.0`。`_refresh_month_cache` 改为：

```python
    def _refresh_month_cache(self, now: datetime) -> None:
        prefix = f"{now.year:04d}-{now.month:02d}-"
        self.cfg["leaves"] = {k: v for k, v in self.cfg.get("leaves", {}).items()
                              if isinstance(k, str) and k.startswith(prefix)}
        mode = self.cfg["holiday_mode"]
        self.pss = money.per_second_salary(
            self.cfg["monthly_salary"], now.year, now.month, self.cfg["leaves"],
            self.cfg["work_start"], self.cfg["work_end"], mode)
        self.daily = money.daily_salary(
            self.cfg["monthly_salary"], now.year, now.month, self.cfg["leaves"],
            self.cfg["work_start"], self.cfg["work_end"], mode)
```

`_toggle_today_holiday` 整体替换为：

```python
    def _mark_today(self, leave_type: str) -> None:
        today = datetime.now().date()
        if self.cfg["holiday_mode"] == "weekend" and today.weekday() >= 5:
            self._set_status("周末本就休息，无需标记")
            return
        candidate = {**self.cfg, "leaves": {**self.cfg.get("leaves", {}),
                                           today.isoformat(): leave_type}}
        if not save_config(candidate):
            self._set_status("警告：config.json 写入失败")
            return
        self.cfg.update(candidate)
        self._refresh_month_cache(datetime.now())
        self._update_today_menu()
        self._update_display(datetime.now())
        self._set_status(f"已标记今天{leave_type}")

    def _unmark_today(self) -> None:
        key = datetime.now().date().isoformat()
        if key not in self.cfg.get("leaves", {}):
            return
        candidate = {**self.cfg,
                     "leaves": {k: v for k, v in self.cfg["leaves"].items() if k != key}}
        if not save_config(candidate):
            self._set_status("警告：config.json 写入失败")
            return
        self.cfg.update(candidate)
        self._refresh_month_cache(datetime.now())
        self._update_today_menu()
        self._update_display(datetime.now())
        self._set_status("已取消今天的休假标记")
```

- [ ] **步骤 3：Commit**

```bash
git add app.py && git commit -m "feat: leaves config model with legacy free_holidays migration"
```

---

### 任务 3：菜单子菜单 + sub 行显示

**文件：** 修改 `app.py`

- [ ] **步骤 1：菜单**

`_build_menu` 中「标记今天休息」command 替换为 cascade：

```python
        m_today = apple_menu(menubar)
        m_today.add_command(label="调休", command=lambda: self._mark_today("调休"))
        m_today.add_command(label="请假", command=lambda: self._mark_today("请假"))
        m_today.add_command(label="取消标记", command=self._unmark_today)
        menubar.add_cascade(label="标记今天", menu=m_today)
        self._today_menu = m_today
```

`__init__` 菜单引用初始化处加 `self._today_menu = None`。`_restyle_menu` 的元组加入 `self._today_menu`。`_update_holiday_menu` 整体替换为：

```python
    def _update_today_menu(self) -> None:
        """今天已标记 → 「取消标记」可用；未标记 → 禁用（调休/请假随时可点）。"""
        marked = datetime.now().date().isoformat() in self.cfg.get("leaves", {})
        self._today_menu.entryconfig(2, state="normal" if marked else "disabled")
```

全部 `_update_holiday_menu()` 调用点（`_build_menu` 尾部、rollover、save 等）改为 `_update_today_menu()`。

- [ ] **步骤 2：sub 行优先级**

`_update_display` 中 `ic("sub", text=self._off_work_text(now, we))` 一行替换为：

```python
        today_type = leaves.get(now.date().isoformat())
        if today_type == "请假":
            sub_text = f"请假中 · 今天没了 {self.daily:,.2f} 元"
        elif today_type == "调休":
            sub_text = "调休中 · 今日不计薪，秒薪已上调"
        else:
            sub_text = self._off_work_text(now, we)
        ic("sub", text=sub_text)
```

（`leaves = cfg.get("leaves", {})` 在函数前部取出；`_off_work_text` 本身不动——请假/调休已在上方优先命中，不会走到它。）

- [ ] **步骤 3：验证 + Commit**

运行：`python money.py`、`python test_redesign.py`、GUI 冒烟（withdraw + after 模式）：菜单三项存在、weekend 模式周末调用 `_mark_today("调休")` 后 leaves 无变化且状态行出现提示。

```bash
git add app.py && git commit -m "feat: mark-today submenu and leave status line"
```

---

### 任务 4：设置弹窗日历控件

**文件：** 修改 `app.py`

- [ ] **步骤 1：日历控件方法**

`PayClockApp` 新增（设置弹窗方法区）：

```python
    def _build_calendar(self, parent, draft: dict, mode: str) -> tk.Frame:
        """当月日历多选：单击循环 计薪→调休→请假→计薪。草稿写入 draft（原地）。"""
        import calendar as _cal
        t = self._tokens()
        now = datetime.now()
        y, m = now.year, now.month
        today_iso = now.date().isoformat()
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
                fixed = (mode == "weekend" and date(y, m, day).weekday() >= 5)
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
```

（`date` 已在 app.py 导入？若无则 `from datetime import date` 并入现有 datetime 导入行。）

- [ ] **步骤 2：接入设置弹窗**

`_open_settings`：删除「额外假期（天/月）」row(4) + `hol_spin/_hol_var` 创建；在原位置放日历（跨两列）：

```python
        self._leaves_draft = dict(self.cfg.get("leaves", {}))
        self._cal_holder = tk.Frame(form, bg=t["dlg_bg"])
        self._cal_holder.grid(row=4, column=0, columnspan=2, pady=(2, 6))
        self._rebuild_calendar()
```

新增（mode 切换时重建日历，weekend 禁用格随草稿模式变化）：

```python
    def _rebuild_calendar(self) -> None:
        for w in self._cal_holder.winfo_children():
            w.destroy()
        self._cal_holder.grid_columnconfigure(6, weight=1)
        self._build_calendar(self._cal_holder, self._leaves_draft,
                             self._mode_var.get())
```

`_on_mode_change` 中 `self._hol_label.configure(...)` 删除，改为 `self._rebuild_calendar()`。`_on_save`：删除 `holidays = int(self._hol_var.get())` 读取；构造 candidate 前加：

```python
        prefix = datetime.now().strftime("%Y-%m-")
        leaves = {k: v for k, v in self._leaves_draft.items()
                  if isinstance(k, str) and k.startswith(prefix)}
        candidate = {**self.cfg, "monthly_salary": salary, "work_start": ws,
                     "work_end": we, "holiday_mode": mode, "leaves": leaves,
                     "payday": payday}
```

（删除旧 candidate 中的 `monthly_holidays` 键。）`money.validate(salary, ws, we, leaves, payday, mode)`。设置弹窗标题不变；`dlg_status` 错误显示逻辑不变。

- [ ] **步骤 3：验证 + Commit**

运行：`python money.py`、`python test_redesign.py`、GUI 冒烟：打开设置 → 日历渲染（今天描边）→ 点击循环三态 → 切换休假方式日历重建 → 保存后 `config.json` 的 leaves 落盘 → 重开弹窗状态保持。

```bash
git add app.py && git commit -m "feat: month calendar multi-select for leaves in settings"
```

---

### 任务 5：README + 回归

**文件：** 修改 `README.md`

- [ ] **步骤 1：README 同步**

- 「核心公式」节：秒薪分母改 D（base − 调休数，请假不进分母）；新增日薪公式与请假损失公式；今日/本月已赚中「工作日」口径改为 leaves；
- 「配置说明」表：删 `monthly_holidays`、`free_holidays` 行，新增 `leaves`（当月 ISO 日期 → 调休/请假，两模式通用，跨月自动清）；`holiday_mode` 行说明微调；
- 菜单描述：「标记今天休息」→「标记今天 ▸ 调休/请假/取消标记（两种模式可用；weekend 模式周末无需标记）」；
- 「已知限制」：删「自由假期逐日手动标记」旧述，补「日历仅当月」；
- 「自检」节：断言数量改为任务 1 的实际值（`python money.py` 输出）。

- [ ] **步骤 2：回归**

```bash
python money.py          # 全部断言 OK
python test_redesign.py  # ALL OK
python make_bg.py        # 资产无变化（可选）
```

- [ ] **步骤 3：手动验收清单（留给人）**

1. weekend 模式：日历标工作日调休 → 秒薪上调、状态「调休中」；标请假 → 「请假中 · 今天没了 XX 元」，XX = 月薪/D；
2. free 模式：日历多选含周末 → 秒薪按 (月天数 − 调休数) 重算；
3. 菜单标记今天（两模式）、weekend 周末标记被拒并提示；
4. 旧 config（free_holidays/monthly_holidays）迁移；日历草稿保存/取消；重启保持；
5. 三主题下设置弹窗日历颜色可读。

- [ ] **步骤 4：Commit**

```bash
git add README.md && git commit -m "docs: leaves/calendar formulas and config reference"
```

---

### 任务 6：money.py 法定节假日表（TDD）

**文件：** 修改 `money.py`

- [ ] **步骤 1：新断言（RED）**

自检新增 §H（2026 法定节假日，weekend 模式）：
- `is_workday(date(2026,10,1), {}, "weekend")` False（国庆，周四）；`date(2026,9,25)` False（中秋周五）；`date(2026,2,16)` False（春节周一）
- 补班周末：`is_workday(date(2026,10,10), {}, "weekend")` True（周六补班）；`date(2026,2,14)` True
- `month_base_workdays(2026,10,{})` = 18（22 个平日 − 5 个平日节休 + 1 个补班周六）；`month_paid_days(2026,10,{"2026-10-13":"调休"},"weekend")` = 17
- free 模式不受节日影响：`is_workday(date(2026,10,1), {}, "free")` True；`month_paid_days(2026,10,{},"free")` = 31
- 缺失年份退化：`is_workday(date(2027,10,1), {}, "weekend")` True（2027 无表，周五普通工作日）；`month_base_workdays(2027,10,{})` = 31 − 8 个周末（2027-10 周末：2,3,9,10,16,17,23,24,30,31 → 10 天 → 21？实现者按 calendar 实算，断言值以实现时真实日历为准，此处意图=「无节休、无补班，纯周末口径」）
- 2024/2023 旧断言不变（无 2024 表 → 行为与任务 1 完全一致，防回归）

- [ ] **步骤 2：运行 RED**（`AttributeError: month_base_workdays`）

- [ ] **步骤 3：实现**

```python
# 2026 年法定节假日（国办发明电〔2025〕7号）。按年组织；缺失年份只认周末。
_STATUTORY_2026_REST = frozenset(
    d.isoformat() for r in ((1, 1, 3), (2, 15, 23), (4, 4, 6), (5, 1, 5),
                            (6, 19, 21), (9, 25, 27), (10, 1, 7))
    for d in (date(2026, a, b) + timedelta(i) for i in range(c - b + 1))
    for a, b, c in [r]) if False else frozenset()
```

（上面生成器写法易错——实现时用显式辅助函数生成区间，保持零 IO；参考：）

```python
def _date_range(y, m1, d1, m2, d2):
    start = date(y, m1, d1)
    return [start + timedelta(i) for i in range((date(y, m2, d2) - start).days + 1)]

_STAT_REST = frozenset(
    iso for year, spans in {
        2026: [(1,1,1,3), (2,15,2,23), (4,4,4,6), (5,1,5,5),
               (6,19,6,21), (9,25,9,27), (10,1,10,7)],
    }.items() for a, b, c, d in spans for iso in
    [x.isoformat() for x in _date_range(year, a, b, year, c, d)])

_STAT_WORK = frozenset({"2026-01-04", "2026-02-14", "2026-02-28",
                        "2026-05-09", "2026-09-20", "2026-10-10"})

def _stat_rest_iso(d: date) -> bool:
    return d.isoformat() in _STAT_REST

def month_base_workdays(y: int, m: int, mode: str = "weekend") -> int:
    """模式基准工作日数（不含任何 leaves）。weekend 扣周末与法定节休、加补班周末；free = 月天数。"""
    if mode == "free":
        return month_days(y, m)
    n = 0
    for i in range(1, month_days(y, m) + 1):
        d = date(y, m, i)
        iso = d.isoformat()
        if _stat_rest_iso(d):
            continue
        if d.weekday() >= 5 and iso not in _STAT_WORK:
            continue
        n += 1
    return n
```

（模块头部保留 `_STAT_REST`/`_STAT_WORK` 两个常量；供 app 用的接口：`fixed_rest_iso(y, m, mode)` 返回该月固定公休 ISO 集合——weekend = 全部 `非 base 工作日`，free = 空集。）

- `month_paid_days` 的 base 从 `月天数−周末数` / `月天数` 改为 `month_base_workdays(y, m, mode)`；
- `is_workday` weekend 分支改为：`(_stat_rest_iso(d) → False)`；`(weekday>=5 且非补班) → False`；其余 True；
- `month_weekend_days` 保留（其余引用不动）。

- [ ] **步骤 4：GREEN**（`python money.py` → 全部 OK，含 §A–§G 旧断言不回归——2024/2023 无表行为不变）

- [ ] **步骤 5：Commit** `git add money.py && git commit -m "feat: 2026 statutory holiday table in salary base (TDD)"`

---

### 任务 7：分模式 leaves + 固定公休日历

**文件：** 修改 `app.py`

- [ ] **步骤 1：config 嵌套与迁移**

`DEFAULT_CONFIG["leaves"]` → `{"weekend": {}, "free": {}}`。`load_config` 迁移：

```python
        loaded["leaves"] = {"weekend": {}, "free": {}}
        legacy = {}
        fh = data.get("free_holidays", [])
        if not isinstance(fh, list):
            raise ValueError("bad free_holidays")
        for d in fh:
            if isinstance(d, str):
                legacy[d] = "调休"
        raw = data.get("leaves")
        if isinstance(raw, dict):
            if "weekend" in raw or "free" in raw:      # 新嵌套形态
                for mode in ("weekend", "free"):
                    if isinstance(raw.get(mode), dict):
                        loaded["leaves"][mode].update(raw[mode])
            else:                                       # 本分支早期 flat 形态 → free 组
                loaded["leaves"]["free"].update(raw)
        loaded["leaves"]["free"].update(legacy)         # 旧自由假日最后放，不覆盖已有
```

`money.validate(..., loaded["leaves"][loaded["holiday_mode"]], ...)`（校验当前模式的 dict）。

- [ ] **步骤 2：缓存与标记按模式**

`_refresh_month_cache`：`leaves = self.cfg["leaves"].get(mode, {})`（两模式各自当月前缀过滤）；pss/daily 用 active dict。`_mark_today`：操作 `candidate["leaves"][mode]`；守卫扩展——weekend 模式下今天为周末**或法定节休**（`money.fixed_rest_iso(ym, "weekend")` 含今天）→ 「公休日本就休息，无需标记」。`_unmark_today` 同理按模式删 key。

- [ ] **步骤 3：日历**

`_build_calendar`：`fixed_iso = money.fixed_rest_iso(y, m, mode)`；格子的 `fixed = iso in fixed_iso`（free 模式 = 空集 → 全可点）；已标记读取 `draft[mode]`。`_open_settings`：`self._leaves_draft = {m: dict(v) for m, v in self.cfg.get("leaves", {}).items()}`；`_rebuild_calendar` 传 draft + mode。`_on_save`：两个模式 dict 都做当月前缀过滤写回 candidate["leaves"]（未编辑的mode原样保留过滤结果）。

- [ ] **步骤 4：sub 行**

`_update_display` 的 `leaves = cfg["leaves"].get(mode, {})` 取今天类型（其余优先级不变）。

- [ ] **步骤 5：验证 + Commit**

money 87+新增 asserts OK；test_redesign ALL OK；GUI 冒烟：weekend 日历 9 月应禁用 {5,6,12,13,19,25,26,27}（9/20 补班可点）；free 全可点；两模式标记互不影响（free 标周六 → 切 weekend 该格显示公休非标记；切回 free 标记仍在）；保存后 config 嵌套落盘。

```bash
git add app.py && git commit -m "feat: per-mode leaves storage + fixed statutory rest in calendar"
```

---

### 任务 8：README + 回归（补充）

- [ ] README：核心公式节补「weekend base 扣除法定节休、补班周末计入」与 2026 表说明；已知限制补「节日表仅 2026，其他年份只认周末，2027 待官方公布」；自检数更新。
- [ ] 回归：money / test_redesign / make_bg 全绿。
- [ ] Commit：`git add README.md && git commit -m "docs: statutory holidays and per-mode leaves"`
