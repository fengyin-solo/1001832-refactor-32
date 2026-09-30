"""养护资金业务规则：状态流转、字段校验、筛选与金额口径。

金额（批复金额、已用金额、剩余额度、超支结论、批复留档）一律由
``fund_finance`` 统一计算，本服务不重复实现任何金额公式。
"""
from __future__ import annotations

from typing import Any

from app.services import fund_finance as finance
from app.store import store

MODULE = "fund"
REQUIRED_FIELDS = ["资金编号", "费用类别", "项目名称"]
STATUS_ORDER = ["待审批", "已批复", "执行中", "已超支"]
ACTION_RULES = {"提交审批": "已批复", "确认批复": "执行中", "标记超支": "已超支"}
NEGATIVE_ACTIONS = ["标记超支"]


class FundService:
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
        page_rows = rows[start:start + size]
        return [finance.present(row) for row in page_rows], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return finance.present(entry, detail=True)

    def summary(self) -> dict[str, Any]:
        """资金口径汇总：资金页统计卡与概览卡片共用同一份结果。"""
        return finance.summarize(store.rows(MODULE))

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        # 批复金额与列支明细是台账事实，登记时写入；没有给的按 0
        entry[finance.APPROVED_KEY] = finance.to_amount(values.get(finance.APPROVED_KEY))
        entry[finance.SETTLED_KEY] = finance.to_amount(values.get(finance.SETTLED_KEY))
        entry[finance.PENDING_KEY] = finance.to_amount(values.get(finance.PENDING_KEY))
        entry["审批人员"] = values.get("审批人员")
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        finance.refresh_row(entry)
        entry[finance.RECONCILED_KEY] = True
        rows.append(entry)
        return finance.present(entry, detail=True), []

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

        # 进入已批复及之后状态且尚无留档时，按当前口径冻结批复金额；
        # 已有留档（含历史 v1 留档）原样保留，绝不被新口径改写。
        if target in finance.APPROVED_STATUSES:
            finance.freeze_approval(entry)
        if action == "标记超支":
            # 人工标记与统一超支结论保持一致
            entry["abnormal"] = True

        # 状态流转后金额仍按当前口径重算；超支结论认金额或人工超支标记
        finance.refresh_row(entry)
        return finance.present(entry, detail=True), f"资金记录已{action}"
