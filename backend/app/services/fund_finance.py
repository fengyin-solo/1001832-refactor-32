"""养护资金金额口径的唯一出处。

列表、详情、概览卡片、导出看到的「批复金额 / 已用金额 / 剩余额度 / 超支结论」
全部由本模块计算，任何页面都不允许自己另算一份，避免三处口径打架。

口径分版本留痕：

- ``v1``（旧口径）：已用金额只统计「列支已结算」，剩余额度 = 批复金额 - 已用金额；
- ``v2``（当前口径）：已用金额 = 列支已结算 + 列支待结算，剩余额度同样按批复金额冲减。

口径再调整时，只改这里的常量与 ``used_amount``：

- 新发生的「确认批复」按当前口径冻结批复留档；
- 已批复记录的已用金额、剩余额度、超支结论一律按当前口径重算；
- 历史批复留档（``approval_snapshot``）按批复当时那一版永久冻结，不被改写。
"""
from __future__ import annotations

from datetime import date
from typing import Any

# ---- 口径版本 -------------------------------------------------------------
CALIBER_V1 = "v1"
CALIBER_V2 = "v2"
CURRENT_CALIBER = CALIBER_V2
CALIBER_LABELS = {CALIBER_V1: "v1（旧口径）", CALIBER_V2: "v2（当前口径）"}

# 旧口径下批复留档的统一时间标识：存量数据没有批复日期，只标记为历史批复
LEGACY_APPROVAL_DATE = "历史批复"

# 已批复及之后的状态：这些记录才参与「批复总额」汇总
APPROVED_STATUSES = ("已批复", "执行中", "已超支")

# ---- 台账字段名（只此一份定义，别处不要写字面量） --------------------------
APPROVED_KEY = "批复金额"
SETTLED_KEY = "列支已结算"
PENDING_KEY = "列支待结算"
USED_KEY = "已用金额"
REMAINING_KEY = "剩余额度"
SNAPSHOT_KEY = "approval_snapshot"
RECONCILED_KEY = "_fund_reconciled"

_EPSILON = 1e-9


def to_amount(value: Any) -> float:
    """把台账里的金额安全转成数值；空值、脏字符串、非数字一律按 0 处理。"""
    if value is None or isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0


def _text(value: Any) -> str | None:
    """展示用文本：空白统一归一成 None，前端好显示占位符。"""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def approved_amount(entry: dict[str, Any]) -> float:
    """批复金额以台账登记值为准（口径冲突时的权威那一份）。"""
    return to_amount(entry.get(APPROVED_KEY))


def settled_spending(entry: dict[str, Any]) -> float:
    """已结算列支：台账列支明细。"""
    return to_amount(entry.get(SETTLED_KEY))


def pending_spending(entry: dict[str, Any]) -> float:
    """待结算列支：台账列支明细，v2 口径新纳入已用金额的部分。"""
    return to_amount(entry.get(PENDING_KEY))


def used_amount(entry: dict[str, Any], *, caliber: str = CURRENT_CALIBER) -> float:
    """已用金额：v1 只算已结算；v2 起把待结算一并计入。"""
    settled = settled_spending(entry)
    if caliber == CALIBER_V1:
        return settled
    return settled + pending_spending(entry)


def remaining_amount(entry: dict[str, Any], *, caliber: str = CURRENT_CALIBER) -> float:
    """剩余额度 = 批复金额 - 已用金额；已用金额随当前口径走。"""
    return approved_amount(entry) - used_amount(entry, caliber=caliber)


def is_overspent(entry: dict[str, Any]) -> bool:
    """超支结论的唯一判定：金额超过批复金额，或已人工标记/流转到已超支。

    金额口径是主依据；人工「标记超支」是业务上的超支确认，结论同样认账，
    避免出现状态已是「已超支」、结论却写「正常」的自相矛盾。
    """
    if entry.get("status") == "已超支" or entry.get("abnormal"):
        return True
    return used_amount(entry) > approved_amount(entry) + _EPSILON


def approval_snapshot(entry: dict[str, Any]) -> dict[str, Any] | None:
    """读取批复留档；留档一旦写入即冻结，后续任何重算都不改它。"""
    snapshot = entry.get(SNAPSHOT_KEY)
    return snapshot if isinstance(snapshot, dict) and snapshot else None


def freeze_approval(entry: dict[str, Any]) -> dict[str, Any]:
    """确认批复时冻结一版留档（金额取当时台账批复金额，口径取当前版本）。

    已经有留档的记录直接原样返回，保证重复动作不会改写历史。
    """
    snapshot = approval_snapshot(entry)
    if snapshot is not None:
        return snapshot
    snapshot = {
        APPROVED_KEY: round(approved_amount(entry), 2),
        "口径版本": CURRENT_CALIBER,
        "批复时间": date.today().isoformat(),
    }
    entry[SNAPSHOT_KEY] = snapshot
    return snapshot


def refresh_row(entry: dict[str, Any]) -> dict[str, Any]:
    """按当前口径把派生数值回写到台账，并同步超支异常标记。

    台账权威事实（批复金额、列支明细、批复留档）不动；
    已用金额、剩余额度属于派生值，任何时候都以这里重算的为准。
    """
    entry[USED_KEY] = round(used_amount(entry), 2)
    entry[REMAINING_KEY] = round(remaining_amount(entry), 2)
    # 金额超限强制标异常；未超限时保留人工已确认的超支标记
    if used_amount(entry) > approved_amount(entry) + _EPSILON:
        entry["abnormal"] = True
    return entry


def reconcile_legacy(rows: list[dict[str, Any]]) -> int:
    """存量历史记录的一次性回填（幂等，可重复执行）。

    回填规则：

    1. 金额字段净化：台账里登记了合法数值的以台账为准，脏值按 0 处理；
    2. 历史「已用金额」视为「列支已结算」；台账若已有列支明细，以明细为准；
    3. 历史已批复记录补一版 v1 批复留档，金额取台账批复金额；
    4. 已用金额、剩余额度按当前新口径重算并回填，覆盖历史脏值/旧口径值；
    5. 口径冲突时一律以台账登记的批复金额、列支明细为准，不采信旧的剩余额度。
    """
    changed = 0
    for row in rows:
        if row.get(RECONCILED_KEY):
            continue

        # 批复金额：台账那一份为准，净化为数值
        row[APPROVED_KEY] = round(approved_amount(row), 2)

        # 列支已结算：台账已有明细就以明细为准；否则沿用历史已用金额
        if row.get(SETTLED_KEY) is None:
            row[SETTLED_KEY] = round(to_amount(row.get(USED_KEY)), 2)
        else:
            row[SETTLED_KEY] = round(to_amount(row.get(SETTLED_KEY)), 2)

        # 列支待结算：旧台账没有该字段，历史记录补 0
        row[PENDING_KEY] = round(to_amount(row.get(PENDING_KEY)), 2)

        # 历史已批复记录：按旧口径 v1 补冻结留档
        if row.get("status") in APPROVED_STATUSES and approval_snapshot(row) is None:
            row[SNAPSHOT_KEY] = {
                APPROVED_KEY: row[APPROVED_KEY],
                "口径版本": CALIBER_V1,
                "批复时间": LEGACY_APPROVAL_DATE,
            }

        refresh_row(row)
        row[RECONCILED_KEY] = True
        changed += 1
    return changed


# ---- 统一展示投影：列表 / 详情 / 导出唯一出口 ------------------------------
# 列表列（详情是列表字段的超集）
LIST_FIELDS = [
    "资金编号", "费用类别", "项目名称",
    APPROVED_KEY, USED_KEY, REMAINING_KEY, "超支结论",
    "审批人员", "资金状态",
]
DETAIL_FIELDS = LIST_FIELDS + [
    SETTLED_KEY, PENDING_KEY,
    "批复留档金额", "批复口径版本", "批复时间",
]


def present(entry: dict[str, Any], *, detail: bool = False) -> dict[str, Any]:
    """把台账记录投影成对外展示结构。

    列表和详情共用本函数，详情只是多几个留档/明细字段，
    因此同一条记录在列表页与详情页上的金额必然一致。
    """
    snapshot = approval_snapshot(entry)
    data: dict[str, Any] = {
        "id": entry.get("id"),
        "资金编号": _text(entry.get("资金编号")),
        "费用类别": _text(entry.get("费用类别")),
        "项目名称": _text(entry.get("项目名称")),
        APPROVED_KEY: round(approved_amount(entry), 2),
        USED_KEY: round(used_amount(entry), 2),
        REMAINING_KEY: round(remaining_amount(entry), 2),
        "超支结论": "超支" if is_overspent(entry) else "正常",
        "审批人员": _text(entry.get("审批人员")),
        "资金状态": _text(entry.get("status")),
        "status": entry.get("status"),
    }
    if detail:
        data[SETTLED_KEY] = round(settled_spending(entry), 2)
        data[PENDING_KEY] = round(pending_spending(entry), 2)
        data["批复留档金额"] = round(to_amount(snapshot.get(APPROVED_KEY)), 2) if snapshot else None
        data["批复口径版本"] = (
            CALIBER_LABELS.get(str(snapshot.get("口径版本")), str(snapshot.get("口径版本")))
            if snapshot else None
        )
        data["批复时间"] = snapshot.get("批复时间") if snapshot else None
    return data


# ---- 概览汇总：概览卡片与资金页统计卡共用 ----------------------------------
STAT_LABELS = ("批复总额", "已用金额", "剩余额度", "超支项目")


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """资金口径汇总。

    批复总额 / 已用金额 / 剩余额度只统计已批复及之后的记录
    （待审批的预算还不算批复资金）；超支项目按统一超支结论计数。

    剩余额度汇总值等于各已批复记录投影剩余额度之和，
    保证「详情页与概览卡片的剩余额度」同源一致。
    """
    approved_rows = [row for row in rows if row.get("status") in APPROVED_STATUSES]
    approved_total = round(sum(approved_amount(row) for row in approved_rows), 2)
    used_total = round(sum(used_amount(row) for row in approved_rows), 2)
    remaining_total = round(sum(remaining_amount(row) for row in approved_rows), 2)
    overspent_total = sum(1 for row in approved_rows if is_overspent(row))
    return {
        "批复总额": approved_total,
        "已用金额": used_total,
        "剩余额度": remaining_total,
        "超支项目": overspent_total,
        "caliber": CURRENT_CALIBER,
    }
