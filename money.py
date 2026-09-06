"""money.py — time_is_money 纯薪资/日期/时间逻辑模块（BATCH-001）。

约束（见 pi-tasks/time-is-money/batches/BATCH-001.md 与 MASTER_PLAN §4 A1–A8）：
- 仅标准库 datetime / calendar / math；零文件 IO、零全局可变状态、零 UI；
- 不 import tkinter / winsound / threading / subprocess / os / json；
- 所有 assert 自检位于 `if __name__ == "__main__":` 守卫内，
  `import money` 无任何副作用与输出。

语义锚点（MASTER_PLAN）：
- A1 周末 = 周六+周日（weekday() >= 5）；weekend 模式工作日 = 周一至周五
- A1b free 自由假期模式：仅被标记日期休息，周末照常上班
- A2 每月假期仅进秒薪分母（口径随模式）；计薪天数 ≤ 0 时报错
- A3 同一天 HH:MM 且 start < end
- A4 payday 超月天数取月末 clamp
- A5 今日计薪：t<start → 0；start≤t<end → t−start；t≥end → 封顶
- A6 本月已赚 = 1 日至昨日工作日整日 + 今日 A5 截断
- A8 压榨 origin = max(overtime_start 当日下班时刻, overtime_start)
"""

import calendar
import math
from datetime import date, datetime, time, timedelta

__all__ = [
    "validate",
    "month_days",
    "month_weekend_days",
    "month_paid_days",
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


def daily_work_seconds(start_hm: str, end_hm: str) -> int:
    """每日工作秒数 = (end − start) 秒（A3：同一天，start < end）。"""
    return (_parse_hm_minutes(end_hm) - _parse_hm_minutes(start_hm)) * 60


def is_workday(d: date, free_holidays=frozenset(), mode: str = "weekend") -> bool:
    """工作日判定。

    weekend（默认）：周一至周五（A1）；
    free（A1b）：自由假期模式，仅被标记日期休息，周末照常上班。
    """
    if mode == "free":
        return d.isoformat() not in free_holidays
    return d.weekday() < 5


def month_paid_days(y: int, m: int, holidays: int, mode: str = "weekend") -> int:
    """当月计薪天数（A2，口径随模式）。

    weekend：月天数 − 月周末数 − 每月假期；free：月天数 − 自由假期天数。
    """
    if mode == "free":
        return month_days(y, m) - holidays
    return month_days(y, m) - month_weekend_days(y, m) - holidays


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------

def validate(salary, start_hm, end_hm, holidays, payday, mode: str = "weekend",
             today: date | None = None) -> list[str]:
    """规则校验（A2/A3 与 config schema 约束）；返回错误文案列表，空列表 = 合法。

    today 仅用于「当月及相邻月」分母检查（A2），缺省取本地今天，
    使校验可确定性复现。
    """
    errors: list[str] = []

    if isinstance(salary, bool) or not isinstance(salary, (int, float)) or salary <= 0:
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

    if isinstance(holidays, bool) or not isinstance(holidays, int) or not (0 <= holidays <= 28):
        errors.append("每月假期必须是 0–28 的整数")

    if isinstance(payday, bool) or not isinstance(payday, int) or not (1 <= payday <= 31):
        errors.append("发薪日必须是 1–31 的整数")

    # A2：当月及相邻月计薪天数（口径随 mode）必须 > 0
    if isinstance(holidays, int) and not isinstance(holidays, bool) and 0 <= holidays <= 28:
        anchor = today if today is not None else date.today()
        for y, m in _adjacent_months(anchor):
            if month_paid_days(y, m, holidays, mode) <= 0:
                errors.append(f"{y}-{m:02d} 计薪天数（月天数-公休/假期）<= 0，无法计算秒薪")

    return errors


# ---------------------------------------------------------------------------
# 秒薪与累计
# ---------------------------------------------------------------------------

def per_second_salary(salary, y: int, m: int, holidays: int, start_hm: str, end_hm: str,
                      mode: str = "weekend") -> float:
    """秒薪 = 月薪 / (当月计薪天数 × 每日工作秒数)（S6/A2，口径随 mode）。

    分母 ≤ 0 时抛 ValueError。
    """
    denominator = month_paid_days(y, m, holidays, mode) \
        * daily_work_seconds(start_hm, end_hm)
    if denominator <= 0:
        raise ValueError(
            f"计薪分母 ≤ 0（{y}-{m:02d}，holidays={holidays}），无法计算秒薪")
    return salary / denominator


def today_paid_seconds(now: datetime, start_hm: str, end_hm: str,
                       free_holidays=frozenset(), mode: str = "weekend") -> int:
    """今日已计薪秒数（A5）：休息日 → 0；否则 clamp(now 时刻 − start, 0, 每日秒数)。"""
    if not is_workday(now.date(), free_holidays, mode):
        return 0
    start_s = _parse_hm_minutes(start_hm) * 60
    cap = daily_work_seconds(start_hm, end_hm)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = int((now - midnight).total_seconds())
    return max(0, min(cap, elapsed - start_s))


def earned_today(pss: float, now: datetime, start_hm: str, end_hm: str,
                 free_holidays=frozenset(), mode: str = "weekend") -> float:
    """今日已赚 = 秒薪 × 今日已计薪秒数。"""
    return pss * today_paid_seconds(now, start_hm, end_hm, free_holidays, mode)


def month_paid_seconds(now: datetime, start_hm: str, end_hm: str,
                       free_holidays=frozenset(), mode: str = "weekend") -> int:
    """本月截至当前累计计薪秒数（A6）：1 日至昨日工作日各计整日 + 今日 A5 截断。"""
    daily = daily_work_seconds(start_hm, end_hm)
    total = 0
    d = now.date().replace(day=1)
    while d < now.date():
        if is_workday(d, free_holidays, mode):
            total += daily
        d += timedelta(days=1)
    return total + today_paid_seconds(now, start_hm, end_hm, free_holidays, mode)


def earned_this_month(pss: float, now: datetime, start_hm: str, end_hm: str,
                      free_holidays=frozenset(), mode: str = "weekend") -> float:
    """本月已赚 = 秒薪 × 本月累计计薪秒数（A6）。"""
    return pss * month_paid_seconds(now, start_hm, end_hm, free_holidays, mode)


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
        """BATCH-001 §5 assert 自检清单，逐项覆盖；返回通过的断言数。"""
        passed = 0

        def check(cond, msg=""):
            nonlocal passed
            assert cond, msg
            passed += 1

        # ---- §5.1 秒薪（基准：10000 元，2024-06，holidays=2，09:00–18:00）----
        s_day = daily_work_seconds("09:00", "18:00")
        n_june = month_days(2024, 6) - month_weekend_days(2024, 6) - 2
        denom = n_june * s_day
        pss = per_second_salary(10000, 2024, 6, 2, "09:00", "18:00")
        check(n_june == 18, "2024-06 计薪天数应为 18")
        check(s_day == 32400, "09:00–18:00 每日工作秒数应为 32400")
        check(denom == 583200, "分母应为 583200")
        check(math.isclose(pss, 10000 / 583200, rel_tol=1e-9), "秒薪应 ≈ 10000/583200")
        pss5 = per_second_salary(10000, 2024, 6, 5, "09:00", "18:00")
        check(pss5 > pss, "holidays=5 秒薪应严格大于 holidays=2（S3 假期只进分母）")

        # ---- §5.2 周末判定 / 月天数 / 月周末数 ----
        check(is_workday(date(2024, 6, 1)) is False, "2024-06-01 周六非工作日")
        check(is_workday(date(2024, 6, 3)) is True, "2024-06-03 周一是工作日")
        check(month_days(2024, 6) == 30, "2024-06 应 30 天")
        check(month_weekend_days(2024, 6) == 10, "2024-06 周末应 10 天")
        check(month_days(2024, 2) == 29, "2024-02 闰年应 29 天")
        check(month_weekend_days(2024, 2) == 8, "2024-02 周末应 8 天")
        check(month_days(2023, 2) == 28, "2023-02 应 28 天")
        check(month_weekend_days(2023, 2) == 8, "2023-02 周末应 8 天")
        check(month_days(2024, 1) == 31, "2024-01 应 31 天")
        check(month_weekend_days(2024, 1) == 8, "2024-01 周末应 8 天")

        # ---- §5.3 当月工作秒数 ----
        check((month_days(2024, 6) - month_weekend_days(2024, 6) - 2)
              * daily_work_seconds("09:00", "18:00") == 18 * 32400,
              "当月工作秒数应为 N×S = 583200")
        check(math.isclose(pss * denom, 10000, rel_tol=1e-9), "秒薪×分母应还原月薪")

        # ---- §5.4 今日已赚（A5）----
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
              "周六任意时刻应为 0")
        check(math.isclose(earned_today(pss, datetime(2024, 6, 3, 12, 0, 0), "09:00", "18:00"),
                           pss * 10800, rel_tol=1e-9), "earned_today = pss×今日秒数")
        check(earned_today(pss, datetime(2024, 6, 1, 12, 0, 0), "09:00", "18:00") == 0.0,
              "周六 earned_today 应为 0.0")

        # ---- §5.5 本月已赚（A6）----
        check(month_paid_seconds(datetime(2024, 6, 3, 12, 0, 0), "09:00", "18:00") == 10800,
              "6/3 12:00 应只含今日 10800 秒（6/1、6/2 周末不计）")
        check(month_paid_seconds(datetime(2024, 6, 10, 9, 0, 0), "09:00", "18:00") == 5 * 32400,
              "6/10 09:00 应为上周一至周五 5 整日 + 今日 0")
        check(month_paid_seconds(datetime(2024, 7, 1, 10, 0, 0), "09:00", "18:00") == 3600,
              "7/1（周一）10:00 应只含今日 3600 秒")
        check(math.isclose(earned_this_month(pss, datetime(2024, 6, 10, 9, 0, 0), "09:00", "18:00"),
                           pss * 5 * 32400, rel_tol=1e-9), "earned_this_month = pss×本月秒数")

        # ---- §5.6 加班压榨（A8，end=18:00）----
        check(overtime_seconds(datetime(2024, 6, 3, 19, 0, 30), "18:00",
                               datetime(2024, 6, 3, 18, 0, 30)) == 3600,
              "激活晚 30 秒，origin=18:00:30 → 1 小时后 3600 秒")
        check(overtime_seconds(datetime(2024, 6, 3, 21, 0, 0), "18:00",
                               datetime(2024, 6, 3, 20, 0, 0)) == 3600,
              "应用晚启动，origin 取激活时刻 20:00")
        check(overtime_seconds(datetime(2024, 6, 3, 19, 0, 0), "18:00",
                               datetime(2024, 6, 3, 20, 0, 0)) == 0,
              "now < origin 应为 0")
        check(overtime_seconds(datetime(2024, 6, 4, 0, 30, 0), "18:00",
                               datetime(2024, 6, 3, 23, 30, 0)) == 3600,
              "origin 跨 0 点应照常累计")
        check(math.isclose(exploited_amount(pss, datetime(2024, 6, 3, 19, 0, 30), "18:00",
                                           datetime(2024, 6, 3, 18, 0, 30)),
                           pss * 3600, rel_tol=1e-9), "压榨金额 = pss×加班秒数")

        # ---- §5.7 发薪日倒计时（A4）----
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

        # ---- §5.8 跨月/边界 ----
        pss_jan = per_second_salary(10000, 2024, 1, 2, "09:00", "18:00")
        pss_feb = per_second_salary(10000, 2024, 2, 2, "09:00", "18:00")
        check(math.isclose(pss_jan, 10000 / ((31 - 8 - 2) * 32400), rel_tol=1e-9),
              "1 月分母应为 (31−8−2)×32400")
        check(math.isclose(pss_feb, 10000 / ((29 - 8 - 2) * 32400), rel_tol=1e-9),
              "2 月分母应为 (29−8−2)×32400")
        check(pss_jan < pss_feb, "月天数切换后秒薪应随之变化")
        check(today_paid_seconds(datetime(2024, 7, 1, 0, 0, 0), "09:00", "18:00") == 0,
              "1 号 00:00 当日截断值应为 0")
        check(month_paid_seconds(datetime(2024, 7, 1, 0, 0, 0), "09:00", "18:00") == 0,
              "1 号 00:00 本月秒数（≤ 当日截断值）应为 0")
        raised = False
        try:
            per_second_salary(10000, 2023, 2, 28, "09:00", "18:00")
        except ValueError:
            raised = True
        check(raised, "holidays 过大致分母 ≤ 0 应抛 ValueError")
        check(len(validate(10000, "09:00", "18:00", 28, 15,
                           today=date(2023, 2, 15))) > 0,
              "validate 应对分母 ≤ 0 返回非空")

        # ---- §5.9 validate ----
        check(validate(10000, "09:00", "18:00", 2, 15, today=date(2024, 6, 10)) == [],
              "合法配置应返回 []")
        check(len(validate(0, "09:00", "18:00", 2, 15)) > 0, "salary=0 应报错")
        check(len(validate(10000, "18:00", "09:00", 2, 15)) > 0, "start≥end 应报错")
        check(len(validate(10000, "09:00", "09:00", 2, 15)) > 0, "start==end 应报错")
        check(len(validate(10000, "9:00", "18:00", 2, 15)) > 0, "『9:00』格式错应报错")
        check(len(validate(10000, "09:00", "18:00", -1, 15)) > 0, "holidays=-1 应报错")
        check(len(validate(10000, "09:00", "18:00", 29, 15)) > 0, "holidays=29 应报错")
        check(len(validate(10000, "09:00", "18:00", 2, 0)) > 0, "payday=0 应报错")
        check(len(validate(10000, "09:00", "18:00", 2, 32)) > 0, "payday=32 应报错")

        # ---- §5.10 自由假期模式（free：当月任选 N 天休息，周末照常上班）----
        pss_free = per_second_salary(10000, 2024, 6, 2, "09:00", "18:00", mode="free")
        check(math.isclose(pss_free, 10000 / (28 * 32400), rel_tol=1e-9),
              "free 模式分母应为 (30−2)×32400")
        check(pss_free < pss, "free 模式计薪天数更多，秒薪应更小")
        check(month_paid_days(2024, 6, 2, "free") == 28, "free 模式计薪天数应为 28")
        check(month_paid_days(2024, 6, 2) == 18, "weekend 模式计薪天数应为 18")
        check(is_workday(date(2024, 6, 1), frozenset(), "free") is True,
              "free 模式周六（未标记）应为工作日")
        sat = frozenset({"2024-06-01"})
        check(is_workday(date(2024, 6, 1), sat, "free") is False,
              "free 模式被标记周六应休息")
        check(is_workday(date(2024, 6, 3), sat, "free") is True,
              "free 模式未标记周一应上班")
        check(today_paid_seconds(datetime(2024, 6, 1, 12, 0, 0), "09:00", "18:00",
                                 frozenset(), "free") == 10800,
              "free 模式未标记周六 12:00 应计 10800 秒")
        check(today_paid_seconds(datetime(2024, 6, 1, 12, 0, 0), "09:00", "18:00",
                                 sat, "free") == 0,
              "free 模式被标记周六应计 0 秒")
        check(month_paid_seconds(datetime(2024, 6, 3, 12, 0, 0), "09:00", "18:00",
                                 frozenset(), "free") == 2 * 32400 + 10800,
              "free 模式本月秒数应含 6/1、6/2 整日 + 今日截断")
        check(validate(10000, "09:00", "18:00", 2, 15, mode="free",
                       today=date(2024, 6, 10)) == [], "free 模式合法配置应返回 []")
        check(len(validate(10000, "09:00", "18:00", 28, 15, mode="free",
                           today=date(2023, 2, 15))) > 0,
              "free 模式 2 月休 28 天分母 ≤ 0 应报错")

        return passed

    _total = _run_self_checks()
    print(f"{_total} asserts OK")
