"""养护资金业务规则：金额口径、批复留档与状态流转都收在这一处。"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "fund"
REQUIRED_FIELDS = ["资金编号", "费用类别", "项目名称"]
STATUS_ORDER = ["待审批", "已批复", "执行中", "已超支"]
ACTION_RULES = {"提交审批": "已批复", "确认批复": "执行中", "标记超支": "已超支"}
NEGATIVE_ACTIONS = []

# 金额口径版本：已用金额、剩余额度的算法调整时升版，批复留档里记录当时所用版本
CALIBER_VERSION = "2026.09"
# 已走完批复的状态：处于这些状态的记录在台账里必须能查到批复留档
APPROVED_STATUSES = {"已批复", "执行中", "已超支"}


def _to_amount(value: Any) -> float:
    """把台账里的取值统一折算成两位小数的金额；空值与占位文本按 0 计。"""
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0


def compute_amounts(entry: dict[str, Any]) -> dict[str, Any]:
    """金额口径的唯一出处：已用金额、剩余额度与超支结论都从这里出。

    剩余额度 = 批复金额 - 已用金额；剩余额度为负即判定超支。
    列表、详情、概览卡片与导出统一复用这一份，避免各处自算口径打架。
    """
    approved = _to_amount(entry.get("批复金额"))
    used = _to_amount(entry.get("已用金额"))
    remaining = round(approved - used, 2)
    return {
        "批复金额": approved,
        "已用金额": used,
        "剩余额度": remaining,
        "是否超支": remaining < 0,
    }


class FundService:
    def __init__(self) -> None:
        # 服务就绪先做一次存量迁移：按当前口径重算台账、补建历史批复留档
        self._reconcile_ledger()

    # ---- 金额展示：列表、详情、概览卡片统一从同一口径取数 ----

    def present_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        """返回按统一口径补齐金额字段的记录副本，不改写台账原文之外的字段。"""
        presented = dict(entry)
        presented.update(compute_amounts(entry))
        return presented

    def summary(self) -> dict[str, Any]:
        """概览卡片汇总：与列表、详情共用 compute_amounts，保证数字对得上。"""
        amounts = [compute_amounts(row) for row in store.rows(MODULE)]
        return {
            "批复总额": round(sum(item["批复金额"] for item in amounts), 2),
            "已用金额": round(sum(item["已用金额"] for item in amounts), 2),
            "剩余额度": round(sum(item["剩余额度"] for item in amounts), 2),
            "超支项目": sum(1 for item in amounts if item["是否超支"]),
        }

    # ---- 存量迁移：重算剩余额度、补建并回填批复留档 ----

    def _reconcile_ledger(self) -> None:
        """按当前口径重算台账剩余额度，并补齐存量批复留档。

        口径冲突时以台账为准：批复留档里的批复金额只读不改，
        留档与台账上的已用金额、剩余额度一律按台账取值重算后回填。
        """
        for row in store.rows(MODULE):
            amounts = compute_amounts(row)
            row["剩余额度"] = amounts["剩余额度"]
            archives = row.setdefault("批复留档", [])
            if row.get("status") in APPROVED_STATUSES and not archives:
                archives.append(self._snapshot(row, amounts, source="存量回填"))
            for archived in archives:
                # 历史批复记录按新口径回填：批复金额留档不动，其余以台账为准重算
                archived["已用金额"] = amounts["已用金额"]
                archived["剩余额度"] = amounts["剩余额度"]
                archived["口径版本"] = CALIBER_VERSION

    def _snapshot(self, entry: dict[str, Any], amounts: dict[str, Any], *, source: str) -> dict[str, Any]:
        """留档一条批复记录：批复金额定格在批复当时，之后任何重算都不改写。"""
        return {
            "批复金额": _to_amount(entry.get("批复金额")),
            "已用金额": amounts["已用金额"],
            "剩余额度": amounts["剩余额度"],
            "口径版本": CALIBER_VERSION,
            "留档日期": date.today().isoformat(),
            "来源": source,
        }

    # ---- 列表 / 详情 / 登记 / 动作 ----

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("资金编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self.present_entry(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self.present_entry(entry) if entry is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return self.present_entry(entry), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"资金记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于养护资金可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        if action == "提交审批":
            # 批复即留档：把当时的批复金额定格下来，后续口径重算一律不改写
            amounts = compute_amounts(entry)
            entry.setdefault("批复留档", []).append(self._snapshot(entry, amounts, source="批复留档"))
        return self.present_entry(entry), f"资金记录已{action}"
