"""养护资金金额口径测试。

覆盖：
- 已用金额 / 剩余额度 / 超支结论的 v1、v2 口径；
- 列表、详情、概览三处同源一致；
- 确认批复时按当时口径冻结留档，后续不被改写；
- 存量历史记录回填剩余额度，口径冲突以台账为准。
"""
from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.main import app
from app.services import fund_finance as finance
from app.store import store


class FinanceCaliberTest(unittest.TestCase):
    def test_v1_and_v2_used_amount(self) -> None:
        entry = {finance.APPROVED_KEY: 100, finance.SETTLED_KEY: 70, finance.PENDING_KEY: 20}
        # 旧口径：已用只算已结算
        self.assertEqual(finance.used_amount(entry, caliber=finance.CALIBER_V1), 70.0)
        self.assertEqual(finance.remaining_amount(entry, caliber=finance.CALIBER_V1), 30.0)
        # 新口径：待结算计入已用
        self.assertEqual(finance.used_amount(entry), 90.0)
        self.assertEqual(finance.remaining_amount(entry), 10.0)
        self.assertFalse(finance.is_overspent(entry))

        over = {finance.APPROVED_KEY: 100, finance.SETTLED_KEY: 90, finance.PENDING_KEY: 20}
        self.assertTrue(finance.is_overspent(over))
        self.assertEqual(finance.remaining_amount(over), -10.0)

    def test_dirty_amount_is_zero(self) -> None:
        self.assertEqual(finance.to_amount("8万元"), 0.0)
        self.assertEqual(finance.to_amount(None), 0.0)
        self.assertEqual(finance.to_amount(" 12.5 "), 12.5)


class ReconcileLegacyTest(unittest.TestCase):
    def setUp(self) -> None:
        # 每个用例独立构造一批存量记录，避免与全局 store 互相干扰
        self.rows = [
            {
                "id": 1, "status": "已批复",
                "资金编号": "F-1", "批复金额": 500000.0,
                "已用金额": 420000.0, "列支待结算": 50000.0,
                "剩余额度": "8万元",  # 旧台账脏值：口径冲突时不采信
            },
            {
                "id": 2, "status": "执行中",
                "资金编号": "F-2", "批复金额": 300000.0,
                "已用金额": 260000.0, "列支待结算": 60000.0,
                "剩余额度": 40000.0,  # 旧口径值：只减已结算
            },
            {
                "id": 3, "status": "待审批",
                "资金编号": "F-3", "批复金额": 100000.0,
                "已用金额": 0.0,
            },
        ]

    def test_backfill_recomputes_and_freezes_v1_snapshot(self) -> None:
        changed = finance.reconcile_legacy(self.rows)
        self.assertEqual(changed, 3)

        approved = self.rows[0]
        # 已用金额按新口径重算：420000 + 50000
        self.assertEqual(approved[finance.USED_KEY], 470000.0)
        # 剩余额度回填：以台账批复金额冲减，旧的「8万元」不采信
        self.assertEqual(approved[finance.REMAINING_KEY], 30000.0)
        snapshot = approved[finance.SNAPSHOT_KEY]
        self.assertEqual(snapshot[finance.APPROVED_KEY], 500000.0)
        self.assertEqual(snapshot["口径版本"], finance.CALIBER_V1)

        executing = self.rows[1]
        self.assertEqual(executing[finance.USED_KEY], 320000.0)
        self.assertEqual(executing[finance.REMAINING_KEY], -20000.0)
        self.assertTrue(executing["abnormal"])  # 超支结论随金额重算
        self.assertEqual(executing[finance.SNAPSHOT_KEY]["口径版本"], finance.CALIBER_V1)

        # 待审批不补批复留档
        self.assertNotIn(finance.SNAPSHOT_KEY, self.rows[2])

    def test_reconcile_is_idempotent_and_snapshot_never_rewritten(self) -> None:
        finance.reconcile_legacy(self.rows)
        first_snapshot = dict(self.rows[0][finance.SNAPSHOT_KEY])
        # 模拟口径调整后再次回填
        self.assertEqual(finance.reconcile_legacy(self.rows), 0)
        self.assertEqual(self.rows[0][finance.SNAPSHOT_KEY], first_snapshot)


class ApiConsistencyTest(unittest.TestCase):
    """列表、详情、概览三处金额必须同源对得上。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_summary_matches_list_and_detail(self) -> None:
        listing = self.client.get("/api/fund").json()["items"]
        by_id = {int(item["id"]): item for item in listing}

        for row in listing:
            detail = self.client.get(f"/api/fund/{row['id']}").json()
            for field in ("批复金额", "已用金额", "剩余额度", "超支结论"):
                self.assertEqual(detail[field], row[field], f"id={row['id']} 字段 {field} 列表/详情不一致")
            by_id[int(row["id"])] = detail

        summary = self.client.get("/api/fund/summary").json()
        overview = self.client.get("/api/overview").json()["fund"]
        # 概览卡片与资金页汇总必须一致
        self.assertEqual(overview, summary)

        approved = [row for row in by_id.values() if row["资金状态"] in finance.APPROVED_STATUSES]
        self.assertEqual(summary["批复总额"], round(sum(row["批复金额"] for row in approved), 2))
        self.assertEqual(summary["已用金额"], round(sum(row["已用金额"] for row in approved), 2))
        self.assertEqual(summary["剩余额度"], round(sum(row["剩余额度"] for row in approved), 2))
        self.assertEqual(summary["超支项目"], sum(1 for row in approved if row["超支结论"] == "超支"))

    def test_seed_legacy_snapshot_is_v1_and_amounts_use_v2(self) -> None:
        # FUND-0002：旧脏剩余「8万元」，新口径剩余应为 30000
        detail = self.client.get("/api/fund/2").json()
        self.assertEqual(detail["批复留档金额"], 500000.0)
        self.assertEqual(detail["批复口径版本"], "v1（旧口径）")
        self.assertEqual(detail["已用金额"], 470000.0)
        self.assertEqual(detail["剩余额度"], 30000.0)

    def test_approval_freezes_snapshot_and_is_immutable(self) -> None:
        # id=1 待审批：提交审批进入已批复，应冻结 v2 留档
        resp = self.client.post("/api/fund/1/actions", json={"values": {"action": "提交审批"}})
        self.assertTrue(resp.json()["ok"])
        detail = self.client.get("/api/fund/1").json()
        self.assertEqual(detail["批复口径版本"], "v2（当前口径）")
        self.assertEqual(detail["批复留档金额"], 100000.0)

        # 再次确认批复，留档不被改写
        resp = self.client.post("/api/fund/1/actions", json={"values": {"action": "确认批复"}})
        self.assertTrue(resp.json()["ok"])
        detail_again = self.client.get("/api/fund/1").json()
        self.assertEqual(detail_again["批复留档金额"], 100000.0)
        self.assertEqual(detail_again["批复口径版本"], "v2（当前口径）")

        # 直接校验台账：留档只有一份
        entry = store.find("fund", 1)
        self.assertIsNotNone(entry)
        snapshots = [k for k in entry if k == finance.SNAPSHOT_KEY]
        self.assertEqual(len(snapshots), 1)

    def test_export_route_not_captured_by_detail(self) -> None:
        resp = self.client.get("/api/fund/export")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["module"], "fund")


if __name__ == "__main__":
    unittest.main()
