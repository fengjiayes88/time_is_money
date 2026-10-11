# 规格说明：休假类型（调休/请假）+ 设置日历多选

日期：2026-09-06
状态：设计已获用户批准（本文件为落地细节，待用户审查）
前置：三主题重设计已完成（main @ 1d0ac02）

## 1. 背景与用户需求（原话归纳）

1. 设置中自由假期选择改为**当月日历控件，多选日期**；
2. 菜单「标记今天休息」后日历同步显示；
3. 「标记今天休息」**两种假期模式都可用**（本月可能额外休假）；
4. 休假分为**调休**与**请假**：
   - 调休 → 本月秒薪按本月实际工作日**重算**（月薪总额不变）；
   - 请假 → 倒计时下方显示「请假中 · 今天没了 {日薪} 元」，日薪按本月上班天数算（**扣钱**）。

## 2. 计薪语义（核心，已确认）

设 `base` = 模式基准工作日数：weekend = 当月天数 − 周末数；free = 当月天数（周末照常上班）。
设 `T` = 当月调休天数，`Q` = 当月请假天数（leaves 字典统计）。

| 量 | 公式 |
|---|---|
| 应出勤天数 D | `base − T`（**调休进分母、请假不进**） |
| 秒薪 | `月薪 / (D × 日工作秒数)`，D ≤ 0 报错 |
| 日薪 | `月薪 / D`（= 秒薪 × 日工作秒数） |
| 调休日/请假日 | 当天不计薪（is_workday = False），已赚 0 |
| 本月底实收 | `月薪 × (D − Q) / D` = `月薪 − 日薪 × Q`（请假扣钱 ✓，调休保月薪 ✓） |

即：**调休重算秒薪、保月薪总额；请假不动画法、扣当日日薪。**

## 3. 数据模型（config.json）

- 新增 `"leaves": {"2026-09-08": "调休", "2026-09-15": "请假"}`：
  key = 当月 ISO 日期，value ∈ {"调休", "请假"}；**两种模式通用**；只保留当月（跨月自动清，沿袭 free_holidays 的前缀过滤）；
- `free_holidays` **废弃**：load_config 迁移 → `leaves[date] = "调休"`（旧自由假日语义 = 保月薪的休息日），迁移后不再写回 free_holidays 键；
- `monthly_holidays` **废弃**：从 DEFAULT_CONFIG 删除（load_config 只读已知键，旧配置中的该字段自然被忽略）；
- `holiday_mode` 保留：weekend = 周末公休；free = 周末照常上班。仅决定 `base`。

## 4. money.py 改造（公式层）

签名变更（内部项目，直接破坏性更新；`__all__` 同步）：

| 函数 | 新签名/行为 |
|---|---|
| `is_workday(d, leaves=None, mode="weekend")` | `d.isoformat() in leaves` → False（调休/请假都不上班）；否则 weekend = weekday<5，free = True |
| `month_paid_days(y, m, leaves, mode="weekend")` | D = `base − 调休数`（请假不减 D）。base：weekend = 月天数−周末数，free = 月天数 |
| `per_second_salary(salary, y, m, leaves, start_hm, end_hm, mode)` | 分母 = D × 日秒；D ≤ 0 抛 ValueError |
| `daily_salary(salary, y, m, leaves, start_hm, end_hm, mode)` **新增** | 月薪 / D |
| `today_paid_seconds(now, start, end, leaves, mode)` | free_holidays 参数换 leaves |
| `earned_today` / `month_paid_seconds` / `earned_this_month` | 同上换 leaves |
| `validate(salary, start_hm, end_hm, leaves, payday, mode="weekend", today=None)` | 移除 holidays 数值校验；新增：leaves 必须是 dict、value ∈ {"调休","请假"}、key 必须是合法 ISO 日期；A2 检查改为相邻月 D > 0（只按调休数减） |

- leaves 容错：`month_leaves_of_type(y, m, leaves, type)` 内部辅助：统计当月指定类型天数（key 非当月 ISO 或 value 非法的条目忽略）；
- 跨月/相邻月 A2 检查：相邻月没有 leaves 条目（app 只存当月），按 D = base 检查；
- 不变：`month_days` / `month_weekend_days` / `daily_work_seconds` / `next_payday` / `days_until_payday` / `overtime_seconds` / `exploited_amount` / `_parse_hm_minutes` 等；
- 自检断言全部重写适配新签名与新语义（调休升秒薪保总额、请假扣日薪、daily_salary、双模式双类型 is_workday、validate 新规则），README 的断言数量改为实际值。

## 5. 设置弹窗：日历控件（app.py，tk Canvas/Frame 手搓，零第三方依赖）

- 触发：设置弹窗中，原「额外假期（天/月）」Spinbox 行替换为月历（两种模式都显示）；
- 结构：`一 二 三 四 五 六 日` 表头 + 当月日期网格（`calendar.monthcalendar` 布局，前后空位留白）；
- 每格 = tk Button（flat、width 3）：
  - **计薪日**：`field_bg` 底 `ink` 字；
  - **周末固定休息**（仅 weekend 模式）：`dlg_bg` 底 `menu_disabled` 字，**不可点**；
  - **调休**：`btn_bg` 底 `btn_fg` 字；
  - **请假**：`err` 底白字；
  - **今天**：`highlightthickness=2` + `highlightbackground=accent` 描边（状态色叠加其上）；
- **单击循环**：计薪 → 调休 → 请假 → 计薪（weekend 模式周末格无响应）；
- 草稿机制：点选只改弹窗内草稿 dict（复制当前 `cfg["leaves"]`），**点「保存设置」才生效**（沿袭现有模态保存交互）；取消/关闭即弃；
- 「保存设置」校验：草稿 → 写入 candidate["leaves"]，仅保留当月、value 白名单；
- 弹窗加高（日历约 6 行 × 26px），`resizable(False, False)` 不变。

## 6. 菜单（app.py）

- 「标记今天休息」command → cascade **「标记今天」**，子项：**调休 / 请假 / 取消标记**；
- **两种模式都可用**（不再有 free 门控）；`_update_holiday_menu` 相应简化：仅按今天是否已标记切换「取消标记」disabled 态（今天无标记时两个标记项可用）；
- **守卫：weekend 模式下今天是周六/日时，标记动作无效**（周末本就休息，若入 leaves 会被错误计入扣钱数 Q）——状态行提示「周末本就休息，无需标记」；free 模式周末是工作日，标记有效；
- 标记动作 = 直接改 `cfg["leaves"][今天]` → 落盘 → `_refresh_month_cache` → 更新显示；取消 = 移除 key；
- 与日历同步：日历草稿在打开时从 cfg 复制，菜单标记后再打开设置即为最新 ✓。

## 7. 主界面显示（app.py）

`_update_display` 的 sub 行（倒计时位置）优先级：

1. 今天 `leaves[今天] == "请假"` → `请假中 · 今天没了 {日薪:,.2f} 元`（日薪 = `money.daily_salary(...)`，月度缓存随 leaves 重算）；
2. 今天 `leaves[今天] == "调休"` → `调休中 · 今日不计薪，秒薪已上调`；
3. 其余 → 现有逻辑（休息日 / 加班中 / 已下班 / HH:MM:SS 倒计时）。

状态行 `_set_status` 与日历/tag 机制不变。

## 8. app.py 其他

- `_refresh_month_cache`：pss 与日薪都按 leaves 重算；leaves 只保留当月（key 前缀过滤，沿袭）；
- `_toggle_today_holiday` → `_mark_today(leave_type)` / `_unmark_today()`；
- load_config 迁移：`free_holidays` → `leaves`（"调休"）；`monthly_holidays` 自然忽略；
- 未配置态（无 config.json）默认 `leaves = {}`。

## 9. 明确不做（YAGNI）

- 跨月标记（leaves 只存当月；下月自动清空）；
- 法定节假日/调休表、加班费系数、历史统计；
- 第三方日历库；年月切换（日历固定显示当月）；
- 调休/请假的上限数量校验（A2 分母 ≤ 0 已由 validate 与 per_second_salary 兜底）。

## 10. 验证

1. `python money.py` → 全部断言 OK（数量以重写后实际为准，README 同步）；
2. `python test_redesign.py` → ALL OK（回归：迁移/主题/tag 契约/烘焙）；
3. `python make_bg.py` → 资产无变化；
4. 手动验收：
   - weekend 模式：日历标一个工作日调休 → 秒薪上调、月薪总额守恒；标请假 → 倒计时行显示「没了 XX 元」，日薪 = 月薪/D；
   - free 模式：日历多选若干天（含周末）→ 秒薪按 (月天数 − 标记数) 重算；
   - 菜单「标记今天 ▸ 调休/请假/取消」两模式可用且与日历状态一致；weekend 模式周六点标记 → 无效并提示；
   - 旧 config（含 free_holidays/monthly_holidays）启动迁移正常；
   - 保存/取消日历草稿行为正确；重启后 leaves 保持。

## 11. 风险与对策

- 72 条断言重写工作量大且是唯一公式回归网 → 断言逐条对应新语义，先改 money.py 断言（RED）再改实现（TDD）；
- 日历控件状态着色依赖主题 token → 全部从 `_tokens()` 取，切换主题后重开弹窗生效（弹窗打开期间切主题沿袭现有"静态上色"行为，不重涂）；
- 请假语义与部分用户直觉（请假也该重算秒薪）可能冲突 → 本规格已在 §2 明确「请假不进分母、扣日薪」，实现前经用户确认。

## 12. 修订（2026-09-06 用户确认）：固定公休日历 + 分模式标记

1. **法定节假日表（money.py）**：嵌入 2026 年官方安排（国办发明电〔2025〕7号）：
   - 放假：元旦 1/1–1/3；春节 2/15–2/23；清明 4/4–4/6；劳动节 5/1–5/5；端午 6/19–6/21；中秋 9/25–9/27；国庆 10/1–10/7
   - 调休补班周末（按工作日）：1/4、2/14、2/28、5/9、9/20、10/10
   - 表按年组织；缺失年份退化为只认周末（README 已知限制）；2027 待官方公布后补录
2. **weekend 模式**：base 工作日 = 周一至五 + 补班周末 − 法定节休；`is_workday` 同口径；日历固定公休格 = 周末（非补班）+ 法定节休，灰色不可点；补班周末显示为可点工作日；工作日照旧可标调休/请假
3. **free 模式**：日历所有格子可选（含周末/节日），不显示固定公休；D = 月天数 − 调休数（不变）
4. **分模式存储**：config `leaves` = `{"weekend": {...}, "free": {...}}`，两模式标记互不影响；money 只接收当前模式的 dict；迁移：旧 flat leaves / free_holidays → free 组（调休）
5. **守卫扩展**：weekend 模式标记今天，周末与法定节休都拒绝（「公休日本就休息」）
6. **不变**：调休/请假语义（§2）、日历草稿制与三态循环、sub 行显示、D ≤ 0 校验
