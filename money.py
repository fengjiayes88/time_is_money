"""money.py — time_is_money 纯薪资/日期/时间逻辑模块（BATCH-001）。

约束（见 pi-tasks/time-is-money/batches/BATCH-001.md 与 MASTER_PLAN §4 A1–A8）：
- 仅标准库 datetime / calendar / math / re；零文件 IO、零全局可变状态、零 UI；
- 不 import tkinter / winsound / threading / subprocess / os / json；
- 所有 assert 自检位于 `if __name__ == "__main__":` 守卫内，
  `import money` 无任何副作用与输出。

语义锚点（MASTER_PLAN + leaves 规格 §2/§12）：
- A1 周末 = 周六+周日（weekday() >= 5）；weekend 模式工作日 = 周一至周五
- A1b free 自由假期模式：周末照常上班，仅 leaves 标记日休息（调休/请假均休息）
- A1c 法定节假日表（2026，国办发明电〔2025〕7号）：weekend 模式下法定节休视为公休、
  补班周末视为工作日；free 模式不受节日表影响（自由排班自行决定）
- A2 调休进秒薪分母（重算秒薪、月薪守恒）；请假不进分母（扣当日日薪）；D ≤ 0 报错
- A2b 日薪 = 月薪 / D（D = 应出勤天数 = base − 调休数）
- A3 同一天 HH:MM 且 start < end
- A4 payday 超月天数取月末 clamp
- A5 今日计薪：t<start → 0；start≤t<end → t−start；t≥end → 封顶
- A6 本月已赚 = 1 日至昨日工作日整日 + 今日 A5 截断
- A8 压榨 origin = max(overtime_start 当日下班时刻, overtime_start)
"""

import calendar
import math
import re
from datetime import date, datetime, time, timedelta

__all__ = [
    "validate",
    "LEAVE_TYPES",
    "month_days",
    "month_weekend_days",
    "month_base_workdays",
    "fixed_rest_iso",
    "month_paid_days",
    "daily_salary",
    "daily_work_seconds",
    "is_workday",
    "per_second_salary",
    "today_paid_seconds",
    "earned_today",
    "month_paid_seconds",
    "earned_this_month",
    "next_payday",
    "days_until_payday",
    "overtime_seconds",
    "exploited_amount",
]


# ---------------------------------------------------------------------------
# 内部解析工具
# ---------------------------------------------------------------------------

def _parse_hm_minutes(hm: str) -> int:
    """严格解析 "HH:MM"（两位小时/分钟），返回当日分钟数；不合法抛 ValueError。"""
    if not isinstance(hm, str):
        raise ValueError(f"时间必须是 HH:MM 字符串，收到 {hm!r}")
    parts = hm.split(":")
    if len(parts) != 2:
        raise ValueError(f"时间必须是 HH:MM 格式，收到 {hm!r}")
    hh, mm = parts
    if len(hh) != 2 or len(mm) != 2 or not hh.isascii() or not mm.isascii() \
            or not hh.isdigit() or not mm.isdigit():
        raise ValueError(f"时间必须是两位数字 HH:MM，收到 {hm!r}")
    h, m = int(hh), int(mm)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"时间数值越界（0≤HH≤23, 0≤MM≤59），收到 {hm!r}")
    return h * 60 + m


def _hm_to_time(hm: str) -> time:
    """把 "HH:MM" 解析为 datetime.time。"""
    minutes = _parse_hm_minutes(hm)
    return time(minutes // 60, minutes % 60)


def _adjacent_months(anchor: date) -> list[tuple[int, int]]:
    """返回 (上月, 当月, 下月) 的 (年, 月) 列表。"""
    prev_y, prev_m = (anchor.year - 1, 12) if anchor.month == 1 else (anchor.year, anchor.month - 1)
    next_y, next_m = (anchor.year + 1, 1) if anchor.month == 12 else (anchor.year, anchor.month + 1)
    return [(prev_y, prev_m), (anchor.year, anchor.month), (next_y, next_m)]


def _payday_in_month(y: int, m: int, payday: int) -> int:
    """A4：payday 超过当月天数时 clamp 到月末。"""
    return min(payday, month_days(y, m))


# ---------------------------------------------------------------------------
# 基础日历/时间函数
# ---------------------------------------------------------------------------

def month_days(y: int, m: int) -> int:
    """当月天数。"""
    return calendar.monthrange(y, m)[1]


def month_weekend_days(y: int, m: int) -> int:
    """当月周六+周日总数（A1）。"""
    return sum(1 for d in range(1, month_days(y, m) + 1)
               if date(y, m, d).weekday() >= 5)


# ---------------------------------------------------------------------------
# 法定节假日表（按年组织；缺失年份不识别节日，退化为纯周末口径）
# ---------------------------------------------------------------------------

def _date_range(y: int, m1: int, d1: int, m2: int, d2: int) -> list[date]:
    """闭区间 [y-m1-d1, y-m2-d2] 的日期列表。"""
    start = date(y, m1, d1)
    return [start + timedelta(i) for i in range((date(y, m2, d2) - start).days + 1)]


# 放假区间 (月, 日, 月, 日)；来源：国办发明电〔2025〕7号（2026 年安排）
_STATUTORY_SPANS = {
    2026: [(1, 1, 1, 3), (2, 15, 2, 23), (4, 4, 4, 6), (5, 1, 5, 5),
           (6, 19, 6, 21), (9, 25, 9, 27), (10, 1, 10, 7)],
}

# 法定调休补班的周末（按工作日对待）
_STAT_WORK = {
    2026: frozenset({"2026-01-04", "2026-02-14", "2026-02-28",
                     "2026-05-09", "2026-09-20", "2026-10-10"}),
}

_STAT_REST = {year: frozenset(d.isoformat() for m1, d1, m2, d2 in spans
                              for d in _date_range(year, m1, d1, m2, d2))
              for year, spans in _STATUTORY_SPANS.items()}


def _stat_rest_iso(d: date) -> bool:
    """d 是否为法定节休（仅限已收录年份，当前为 2026）。"""
    return d.isoformat() in _STAT_REST.get(d.year, frozenset())


def daily_work_seconds(start_hm: str, end_hm: str) -> int:
    """每日工作秒数 = (end − start) 秒（A3：同一天，start < end）。"""
    return (_parse_hm_minutes(end_hm) - _parse_hm_minutes(start_hm)) * 60


LEAVE_TYPES = ("调休", "请假")


def _month_leave_count(y: int, m: int, leaves, leave_type: str) -> int:
    """当月指定类型的休假日数（key 非当月字符串或 value 非法的条目忽略）。"""
    if not isinstance(leaves, dict):
        return 0
    prefix = f"{y:04d}-{m:02d}-"
    return sum(1 for k, v in leaves.items()
               if isinstance(k, str) and k.startswith(prefix) and v == leave_type)


def is_workday(d: date, leaves=None, mode: str = "weekend") -> bool:
    """工作日判定：任何休假日（调休/请假）→ False；
    weekend：周一至五 + 法定补班周末 − 法定节休；
    free：周末照常上班且不识别节日表（A1/A1b/A1c）。"""
    if isinstance(leaves, dict) and leaves.get(d.isoformat()) in LEAVE_TYPES:
        return False
    if mode == "free":
        return True
    if _stat_rest_iso(d):
        return False
    if d.weekday() >= 5:
        return d.isoformat() in _STAT_WORK.get(d.year, frozenset())
    return True


def month_base_workdays(y: int, m: int, mode: str = "weekend") -> int:
    """模式基准工作日数（不含任何 leaves）。

    weekend：周一至五 + 法定补班周末 − 法定节休；free：月天数（周末照常上班，
    节日不特判——自由排班自行决定，规格 §12.3）。
    """
    if mode == "free":
        return month_days(y, m)
    work = _STAT_WORK.get(y, frozenset())
    n = 0
    for i in range(1, month_days(y, m) + 1):
        d = date(y, m, i)
        if _stat_rest_iso(d):
            continue
        if d.weekday() >= 5 and d.isoformat() not in work:
            continue
        n += 1
    return n


def fixed_rest_iso(y: int, m: int, mode: str = "weekend") -> frozenset:
    """当月「固定公休」ISO 日期集合（不含任何 leaves）。

    weekend：非基准工作日（周末非补班 + 法定节休）；free：空集（全可标）。
    app 日历据此渲染不可修改的公休格（规格 §12.2）。
    """
    if mode == "free":
        return frozenset()
    rest = _STAT_REST.get(y, frozenset())
    work = _STAT_WORK.get(y, frozenset())
    out = []
    for i in range(1, month_days(y, m) + 1):
        d = date(y, m, i)
        iso = d.isoformat()
        if iso in rest or (d.weekday() >= 5 and iso not in work):
            out.append(iso)
    return frozenset(out)


def month_paid_days(y: int, m: int, leaves, mode: str = "weekend") -> int:
    """当月应出勤天数 D（规格 §2）：base − 调休数。

    调休进分母（重算秒薪），请假不进（扣日薪语义）。
    base：weekend = month_base_workdays（扣周末与法定节休、含补班周末）；
    free = 月天数。
    """
    leaves = leaves if isinstance(leaves, dict) else {}
    t = _month_leave_count(y, m, leaves, "调休")
    return month_base_workdays(y, m, mode) - t


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------

def validate(salary, start_hm, end_hm, leaves, payday, mode: str = "weekend",
             today: date | None = None) -> list[str]:
    """规则校验（规格 §2/§4 与 config schema 约束）；返回错误文案列表，空列表 = 合法。

    today 仅用于「当月及相邻月」分母检查（A2），缺省取本地今天，
    使校验可确定性复现。
    """
    errors: list[str] = []

    if isinstance(salary, bool) or not isinstance(salary, (int, float)) \
            or not math.isfinite(salary) or salary <= 0:
        errors.append("月薪必须是大于 0 的数字")

    for label, hm in (("上班时间", start_hm), ("下班时间", end_hm)):
        try:
            _parse_hm_minutes(hm)
        except ValueError as exc:
            errors.append(f"{label}{exc}")

    try:
        if _parse_hm_minutes(start_hm) >= _parse_hm_minutes(end_hm):
            errors.append("上班时间必须早于下班时间（同一天 start < end）")
    except ValueError:
        pass  # 格式错误已在上面逐项报告

    if not isinstance(leaves, dict):
        errors.append("leaves 必须是字典（ISO 日期 → 调休/请假）")
    else:
        for k, v in leaves.items():
            if not isinstance(k, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", k):
                errors.append(f"leaves 日期键必须是 ISO 日期（YYYY-MM-DD）：{k!r}")
                continue
            try:
                date.fromisoformat(k)
            except ValueError:
                errors.append(f"leaves 日期键不是有效日期：{k!r}")
            if v not in LEAVE_TYPES:
                errors.append(f"leaves 类型必须是 调休/请假：{k!r}")

    if isinstance(payday, bool) or not isinstance(payday, int) or not (1 <= payday <= 31):
        errors.append("发薪日必须是 1–31 的整数")

    # A2：当月及相邻月应出勤天数（D）必须 > 0；相邻月无 leaves 条目 → D = base
    anchor = today if today is not None else date.today()
    safe_leaves = leaves if isinstance(leaves, dict) else {}
    for y, m in _adjacent_months(anchor):
        if month_paid_days(y, m, safe_leaves, mode) <= 0:
            errors.append(f"{y}-{m:02d} 应出勤天数（月天数-公休/调休）<= 0，无法计算秒薪")

    return errors


# ---------------------------------------------------------------------------
# 秒薪与累计
# ---------------------------------------------------------------------------

def per_second_salary(salary, y: int, m: int, leaves, start_hm: str, end_hm: str,
                      mode: str = "weekend") -> float:
    """秒薪 = 月薪 / (应出勤天数 D × 每日工作秒数)（规格 §2）。

    D = base − 调休数（请假不进分母）；D ≤ 0 抛 ValueError。
    """
    denominator = month_paid_days(y, m, leaves, mode) \
        * daily_work_seconds(start_hm, end_hm)
    if denominator <= 0:
        raise ValueError(
            f"计薪分母 ≤ 0（{y}-{m:02d}，应出勤天数 ≤ 0），无法计算秒薪")
    return salary / denominator


def daily_salary(salary, y: int, m: int, leaves, start_hm: str, end_hm: str,
                 mode: str = "weekend") -> float:
    """日薪 = 月薪 / D（= 秒薪 × 日工作秒数）（A2b）。"""
    return per_second_salary(salary, y, m, leaves, start_hm, end_hm, mode) \
        * daily_work_seconds(start_hm, end_hm)


def today_paid_seconds(now: datetime, start_hm: str, end_hm: str,
                       leaves=None, mode: str = "weekend") -> int:
    """今日已计薪秒数（A5）：休息日 → 0；否则 clamp(now 时刻 − start, 0, 每日秒数)。"""
    if not is_workday(now.date(), leaves, mode):
        return 0
    start_s = _parse_hm_minutes(start_hm) * 60
    cap = daily_work_seconds(start_hm, end_hm)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = int((now - midnight).total_seconds())
    return max(0, min(cap, elapsed - start_s))


def earned_today(pss: float, now: datetime, start_hm: str, end_hm: str,
                 leaves=None, mode: str = "weekend") -> float:
    """今日已赚 = 秒薪 × 今日已计薪秒数。"""
    return pss * today_paid_seconds(now, start_hm, end_hm, leaves, mode)


def month_paid_seconds(now: datetime, start_hm: str, end_hm: str,
                       leaves=None, mode: str = "weekend") -> int:
    """本月截至当前累计计薪秒数（A6）：1 日至昨日工作日各计整日 + 今日 A5 截断。"""
    daily = daily_work_seconds(start_hm, end_hm)
    total = 0
    d = now.date().replace(day=1)
    while d < now.date():
        if is_workday(d, leaves, mode):
            total += daily
        d += timedelta(days=1)
    return total + today_paid_seconds(now, start_hm, end_hm, leaves, mode)


def earned_this_month(pss: float, now: datetime, start_hm: str, end_hm: str,
                      leaves=None, mode: str = "weekend") -> float:
    """本月已赚 = 秒薪 × 本月累计计薪秒数（A6）。"""
    return pss * month_paid_seconds(now, start_hm, end_hm, leaves, mode)


# ---------------------------------------------------------------------------
# 发薪日与加班压榨
# ---------------------------------------------------------------------------

def next_payday(today: date, payday: int) -> date:
    """下一个发薪日（A4 clamp）：today.day == 有效发薪日 → 今天；未到 → 本月；已过 → 下月。"""
    this_dom = _payday_in_month(today.year, today.month, payday)
    if today.day == this_dom:
        return today
    if today.day < this_dom:
        return date(today.year, today.month, this_dom)
    if today.month == 12:
        ny, nm = today.year + 1, 1
    else:
        ny, nm = today.year, today.month + 1
    return date(ny, nm, _payday_in_month(ny, nm, payday))


def days_until_payday(today: date, payday: int) -> int:
    """距发薪日天数（当天 = 0）。"""
    return (next_payday(today, payday) - today).days


def overtime_seconds(now: datetime, end_hm: str, overtime_start: datetime) -> int:
    """加班累计秒数（A8）：origin = max(overtime_start 当日下班时刻, overtime_start)；
    返回 max(0, now − origin)；now 跨 0 点照常累计。"""
    shift_end = datetime.combine(overtime_start.date(), _hm_to_time(end_hm))
    origin = max(shift_end, overtime_start)
    return max(0, int((now - origin).total_seconds()))


def exploited_amount(pss: float, now: datetime, end_hm: str, overtime_start: datetime) -> float:
    """老板压榨金额 = 秒薪 × 加班累计秒数。"""
    return pss * overtime_seconds(now, end_hm, overtime_start)


# ---------------------------------------------------------------------------
# 自检（仅在脚本直跑时执行；import money 无副作用、无输出）
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    def _run_self_checks() -> int:
        """自检清单（leaves 语义版）：调休/请假/双模式/validate/回归；返回断言数。"""
        passed = 0

        def check(cond, msg=""):
            nonlocal passed
            assert cond, msg
            passed += 1

        s_day = daily_work_seconds("09:00", "18:00")
        pss = per_second_salary(10000, 2024, 6, {}, "09:00", "18:00")
        n_june = month_paid_days(2024, 6, {})
        denom = n_june * s_day

        # ---- §A 基准（weekend 无标记）：D = 30 − 10 = 20 ----
        check(n_june == 20, "2024-06 无标记应出勤应为 20（30−10 周末）")
        check(s_day == 32400, "09:00–18:00 每日工作秒数应为 32400")
        check(denom == 648000, "分母应为 20×32400 = 648000")
        check(math.isclose(pss, 10000 / 648000, rel_tol=1e-9), "秒薪应 ≈ 10000/648000")
        check(month_days(2024, 6) == 30, "2024-06 应 30 天")
        check(month_weekend_days(2024, 6) == 10, "2024-06 周末应 10 天")
        check(month_days(2024, 2) == 29, "2024-02 闰年应 29 天")
        check(month_weekend_days(2024, 2) == 8, "2024-02 闰年周末应 8 天")
        check(month_days(2023, 2) == 28, "2023-02 应 28 天")
        check(month_weekend_days(2023, 2) == 8, "2023-02 周末应 8 天")
        check(month_days(2024, 1) == 31, "2024-01 应 31 天")
        check(month_weekend_days(2024, 1) == 8, "2024-01 周末应 8 天")
        check(is_workday(date(2024, 6, 1)) is False, "2024-06-01 周六非工作日（weekend）")
        check(is_workday(date(2024, 6, 3)) is True, "2024-06-03 周一是工作日（weekend）")

        # ---- §B 调休：进分母（秒薪重算，月薪守恒）----
        tiao2 = {"2024-06-05": "调休", "2024-06-06": "调休"}
        check(month_paid_days(2024, 6, tiao2) == 18, "2 天调休 → D 应 18")
        pss_t = per_second_salary(10000, 2024, 6, tiao2, "09:00", "18:00")
        check(math.isclose(pss_t, 10000 / (18 * 32400), rel_tol=1e-9),
              "调休后秒薪应 ≈ 10000/(18×32400)")
        check(pss_t > pss, "调休天数越多秒薪应越高")
        check(is_workday(date(2024, 6, 5), tiao2) is False, "调休日应非工作日")
        check(is_workday(date(2024, 6, 7), tiao2) is True, "未标记周五应仍为工作日")
        check(math.isclose(pss_t * 18 * 32400, 10000, rel_tol=1e-9),
              "调休语义下满勤月实收应守恒月薪")

        # ---- §C 请假：不进分母（秒薪不动，扣日薪）----
        qing5 = {f"2024-06-{d:02d}": "请假" for d in (10, 11, 12, 13, 14)}
        check(month_paid_days(2024, 6, qing5) == 20, "请假不减应出勤 D（应仍为 20）")
        check(all(is_workday(date(2024, 6, d), qing5) is False
                  for d in (10, 11, 12, 13, 14)), "5 个请假日均应非工作日")
        daily = daily_salary(10000, 2024, 6, qing5, "09:00", "18:00")
        check(math.isclose(daily, 500, rel_tol=1e-9), "日薪应 = 10000/20 = 500")
        check(math.isclose(daily, pss * s_day, rel_tol=1e-9), "日薪应 = 秒薪×日秒")
        check(earned_today(pss, datetime(2024, 6, 10, 12, 0, 0), "09:00", "18:00", qing5)
              == 0.0, "请假日 earned_today 应为 0")
        check(month_paid_seconds(datetime(2024, 6, 30, 18, 0, 0), "09:00", "18:00", qing5)
              == 15 * 32400, "请假 5 天的 6 月应只计 15 个整日")
        earned_q = earned_this_month(pss, datetime(2024, 6, 30, 18, 0, 0),
                                     "09:00", "18:00", qing5)
        check(math.isclose(earned_q, 10000 * 15 / 20, rel_tol=1e-9),
              "月底实收应 = 月薪×15/20 = 7500")
        check(math.isclose(10000 - earned_q, daily * 5, rel_tol=1e-9),
              "请假损失应 = 日薪×请假天数")

        # ---- §D free 模式（周末照常上班）----
        check(month_paid_days(2024, 6, {}, "free") == 30, "free 无标记 D 应为 30")
        pss_free = per_second_salary(10000, 2024, 6, {}, "09:00", "18:00", mode="free")
        check(math.isclose(pss_free, 10000 / (30 * 32400), rel_tol=1e-9),
              "free 秒薪应 ≈ 10000/(30×32400)")
        check(pss_free < pss, "free 计薪天数更多秒薪应更小")
        check(is_workday(date(2024, 6, 1), {}, "free") is True,
              "free 模式未标记周六应为工作日")
        check(month_paid_days(2024, 6, tiao2, "free") == 28, "free 2 天调休 → D 应 28")
        check(is_workday(date(2024, 6, 1), {"2024-06-01": "请假"}, "free") is False,
              "free 模式标记周六请假应休息")
        check(month_paid_days(2024, 6, {"2024-06-01": "请假"}, "free") == 30,
              "free 模式周六请假不减 D（应仍为 30）")
        check(today_paid_seconds(datetime(2024, 6, 1, 12, 0, 0), "09:00", "18:00",
                                 {}, "free") == 10800,
              "free 未标记周六 12:00 应计 10800 秒")
        check(today_paid_seconds(datetime(2024, 6, 1, 12, 0, 0), "09:00", "18:00",
                                 {"2024-06-01": "请假"}, "free") == 0,
              "free 请假周六应计 0 秒")

        # ---- §E 混合（调休 2 + 请假 3）----
        mix = {"2024-06-05": "调休", "2024-06-06": "调休",
               "2024-06-10": "请假", "2024-06-11": "请假", "2024-06-12": "请假"}
        check(month_paid_days(2024, 6, mix) == 18, "调休2+请假3 → D 应 18（请假不进 D）")
        check(all(is_workday(date(2024, 6, d), mix) is False
                  for d in (5, 6, 10, 11, 12)), "5 个休假日均应非工作日")
        pss_m = per_second_salary(10000, 2024, 6, mix, "09:00", "18:00")
        earned_m = earned_this_month(pss_m, datetime(2024, 6, 30, 18, 0, 0),
                                     "09:00", "18:00", mix)
        check(math.isclose(earned_m, 10000 * 15 / 18, rel_tol=1e-9),
              "月底实收应 = 月薪×15/18")
        check(math.isclose(10000 - earned_m, (10000 / 18) * 3, rel_tol=1e-9),
              "混合损失应 = 日薪×请假 3 天")

        # ---- §F validate（leaves 规则 + A2 分母）----
        check(validate(10000, "09:00", "18:00", {}, 15, today=date(2024, 6, 10)) == [],
              "合法配置应返回 []")
        check(len(validate(10000, "09:00", "18:00", "x", 15)) > 0, "leaves 非字典应报错")
        check(len(validate(10000, "09:00", "18:00", {"2024-06-05": "病假"}, 15)) > 0,
              "leaves 非法类型应报错")
        check(len(validate(10000, "09:00", "18:00", {"2024-6-5": "调休"}, 15)) > 0,
              "leaves 非零填充日期应报错")
        check(len(validate(10000, "09:00", "18:00", {"20240605": "调休"}, 15)) > 0,
              "leaves 基本格式日期应报错")
        check(len(validate(10000, "09:00", "18:00", {"bad": "调休"}, 15)) > 0,
              "leaves 非日期键应报错")
        feb2023 = {f"2023-02-{d:02d}": "调休" for d in range(1, 29)
                   if date(2023, 2, d).weekday() < 5}
        raised = False
        try:
            per_second_salary(10000, 2023, 2, feb2023, "09:00", "18:00")
        except ValueError:
            raised = True
        check(raised, "调休吃满应出勤致 D=0 应抛 ValueError")
        check(len(validate(10000, "09:00", "18:00", feb2023, 15,
                           today=date(2023, 2, 15))) > 0,
              "validate 应对当月 D ≤ 0 返回非空")
        check(len(validate(0, "09:00", "18:00", {}, 15)) > 0, "salary=0 应报错")
        check(len(validate(float("nan"), "09:00", "18:00", {}, 15)) > 0, "salary=NaN 应报错")
        check(len(validate(float("inf"), "09:00", "18:00", {}, 15)) > 0, "salary=inf 应报错")
        check(len(validate(10000, "18:00", "09:00", {}, 15)) > 0, "start≥end 应报错")
        check(len(validate(10000, "09:00", "09:00", {}, 15)) > 0, "start==end 应报错")
        check(len(validate(10000, "9:00", "18:00", {}, 15)) > 0, "『9:00』格式错应报错")
        check(len(validate(10000, "09:00", "18:00", {}, 0)) > 0, "payday=0 应报错")
        check(len(validate(10000, "09:00", "18:00", {}, 32)) > 0, "payday=32 应报错")

        # ---- §G 回归（A4 发薪日 / A5 截断 / A8 加班 / 跨月）----
        check(next_payday(date(2024, 6, 10), 15) == date(2024, 6, 15), "6/10 → 6/15")
        check(days_until_payday(date(2024, 6, 10), 15) == 5, "距 6/15 应 5 天")
        check(next_payday(date(2024, 6, 15), 15) == date(2024, 6, 15), "当天即发薪日")
        check(days_until_payday(date(2024, 6, 15), 15) == 0, "当天应为 0 天")
        check(next_payday(date(2024, 6, 20), 15) == date(2024, 7, 15), "6/20 → 7/15")
        check(days_until_payday(date(2024, 6, 20), 15) == 25, "距 7/15 应 25 天")
        check(next_payday(date(2024, 4, 15), 31) == date(2024, 4, 30), "payday=31 → 4/30 clamp")
        check(next_payday(date(2024, 2, 15), 31) == date(2024, 2, 29), "payday=31 → 闰 2/29 clamp")
        check(next_payday(date(2023, 2, 15), 31) == date(2023, 2, 28), "payday=31 → 平 2/28 clamp")
        check(next_payday(date(2024, 4, 30), 31) == date(2024, 4, 30),
              "clamp 月末当天应视为发薪日")
        check(today_paid_seconds(datetime(2024, 6, 3, 8, 0, 0), "09:00", "18:00") == 0,
              "08:00 早于 start 应为 0")
        check(today_paid_seconds(datetime(2024, 6, 3, 9, 0, 0), "09:00", "18:00") == 0,
              "整 09:00 应为 0")
        check(today_paid_seconds(datetime(2024, 6, 3, 12, 0, 0), "09:00", "18:00") == 10800,
              "12:00 应已计 10800 秒")
        check(today_paid_seconds(datetime(2024, 6, 3, 18, 0, 0), "09:00", "18:00") == 32400,
              "18:00 整应封顶 32400 秒")
        check(today_paid_seconds(datetime(2024, 6, 3, 20, 0, 0), "09:00", "18:00") == 32400,
              "20:00 应封顶 32400 秒")
        check(today_paid_seconds(datetime(2024, 6, 1, 12, 0, 0), "09:00", "18:00") == 0,
              "weekend 周六任意时刻应为 0")
        check(math.isclose(earned_today(pss, datetime(2024, 6, 3, 12, 0, 0),
                                        "09:00", "18:00"),
                           pss * 10800, rel_tol=1e-9), "earned_today = pss×今日秒数")
        check(month_paid_seconds(datetime(2024, 6, 3, 12, 0, 0), "09:00", "18:00") == 10800,
              "6/3 12:00 应只含今日 10800 秒")
        check(month_paid_seconds(datetime(2024, 6, 10, 9, 0, 0), "09:00", "18:00") == 5 * 32400,
              "6/10 09:00 应为上周一至周五 5 整日")
        check(month_paid_seconds(datetime(2024, 7, 1, 10, 0, 0), "09:00", "18:00") == 3600,
              "7/1（周一）10:00 应只含今日 3600 秒")
        check(math.isclose(earned_this_month(pss, datetime(2024, 6, 10, 9, 0, 0),
                                             "09:00", "18:00"),
                           pss * 5 * 32400, rel_tol=1e-9), "earned_this_month = pss×本月秒数")
        check(overtime_seconds(datetime(2024, 6, 3, 19, 0, 30), "18:00",
                               datetime(2024, 6, 3, 18, 0, 30)) == 3600,
              "origin=18:00:30 → 1 小时后 3600 秒")
        check(overtime_seconds(datetime(2024, 6, 3, 21, 0, 0), "18:00",
                               datetime(2024, 6, 3, 20, 0, 0)) == 3600,
              "origin 取激活时刻 20:00")
        check(overtime_seconds(datetime(2024, 6, 3, 19, 0, 0), "18:00",
                               datetime(2024, 6, 3, 20, 0, 0)) == 0, "now < origin 应为 0")
        check(overtime_seconds(datetime(2024, 6, 4, 0, 30, 0), "18:00",
                               datetime(2024, 6, 3, 23, 30, 0)) == 3600,
              "origin 跨 0 点应照常累计")
        check(math.isclose(exploited_amount(pss, datetime(2024, 6, 3, 19, 0, 30), "18:00",
                                            datetime(2024, 6, 3, 18, 0, 30)),
                           pss * 3600, rel_tol=1e-9), "压榨金额 = pss×加班秒数")
        pss_jan = per_second_salary(10000, 2024, 1, {}, "09:00", "18:00")
        pss_feb = per_second_salary(10000, 2024, 2, {}, "09:00", "18:00")
        check(math.isclose(pss_jan, 10000 / ((31 - 8) * 32400), rel_tol=1e-9),
              "1 月分母应为 (31−8)×32400")
        check(math.isclose(pss_feb, 10000 / ((29 - 8) * 32400), rel_tol=1e-9),
              "2 月分母应为 (29−8)×32400")
        check(pss_jan < pss_feb, "月天数切换后秒薪应随之变化")
        check(today_paid_seconds(datetime(2024, 7, 1, 0, 0, 0), "09:00", "18:00") == 0,
              "1 号 00:00 当日截断值应为 0")
        check(month_paid_seconds(datetime(2024, 7, 1, 0, 0, 0), "09:00", "18:00") == 0,
              "1 号 00:00 本月秒数应为 0")
        check(math.isclose(pss * denom, 10000, rel_tol=1e-9), "秒薪×分母应还原月薪")

        # ---- §H 2026 法定节假日（国办发明电〔2025〕7号，weekend 模式）----
        check(is_workday(date(2026, 10, 1), {}, "weekend") is False,
              "2026-10-01 国庆（周四）应为法定节休")
        check(is_workday(date(2026, 9, 25), {}, "weekend") is False,
              "2026-09-25 中秋（周五）应为法定节休")
        check(is_workday(date(2026, 2, 16), {}, "weekend") is False,
              "2026-02-16 春节（周一）应为法定节休")
        check(is_workday(date(2026, 10, 10), {}, "weekend") is True,
              "2026-10-10 周六补班应为工作日")
        check(is_workday(date(2026, 2, 14), {}, "weekend") is True,
              "2026-02-14 周六补班应为工作日")
        check(month_base_workdays(2026, 10, "weekend") == 18,
              "2026-10 base 应 18（22 平日 − 5 平日节休 + 1 补班周六）")
        check(month_paid_days(2026, 10, {"2026-10-13": "调休"}, "weekend") == 17,
              "2026-10 加 1 天调休 → D 应 17")
        check(is_workday(date(2026, 10, 1), {}, "free") is True,
              "free 模式法定节休照常为可工作日（自由排班）")
        check(month_paid_days(2026, 10, {}, "free") == 31,
              "free 模式 10 月 D 应 31（节日不特判）")
        check(is_workday(date(2027, 10, 1), {}, "weekend") is True,
              "2027 无节日表：10-01 周五应为普通工作日")
        check(month_base_workdays(2027, 10, "weekend") == 21,
              "2027-10 base 应 21（31 − 10 周末，无节休无补班）")
        fixed_oct = fixed_rest_iso(2026, 10, "weekend")
        check(len(fixed_oct) == 13,
              "2026-10 固定公休应 13 天（9 周末 − 1 补班 + 5 平日节休）")
        check(fixed_rest_iso(2026, 10, "free") == frozenset(),
              "free 模式无固定公休")
        check("2026-10-01" in fixed_oct and "2026-10-03" in fixed_oct
              and "2026-10-10" not in fixed_oct,
              "固定公休应含 10-01/10-03、不含补班的 10-10")

        return passed

    _total = _run_self_checks()
    print(f"{_total} asserts OK")
