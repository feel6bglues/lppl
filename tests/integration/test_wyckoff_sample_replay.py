import unittest
from pathlib import Path

from src.data.manager import DataManager
from src.wyckoff import WyckoffAnalyzer, WyckoffPhase


class WyckoffSampleReplayIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        required_files = [
            Path("/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sh/lday/sh600859.day"),
            Path("/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sz/lday/sz002216.day"),
            Path("/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sz/lday/sz300442.day"),
        ]
        if not all(path.exists() for path in required_files):
            raise unittest.SkipTest("missing local TDX stock files for sample replay")

        cls.data_manager = DataManager()
        cls.analyzer = WyckoffAnalyzer(lookback_days=120)

    def _analyze_until(self, symbol: str, as_of: str):
        df = self.data_manager.get_data(symbol)
        self.assertIsNotNone(df, f"failed to load data for {symbol}")
        sliced = df[df["date"] <= as_of].copy()
        self.assertGreaterEqual(len(sliced), 100, f"insufficient replay rows for {symbol} @ {as_of}")
        return self.analyzer.analyze(sliced, symbol=symbol, period="日线", multi_timeframe=True)

    def test_replay_wangfujing_matches_markdown_bias(self) -> None:
        report = self._analyze_until("600859.SH", "2026-04-03")

        self.assertEqual(report.structure.phase, WyckoffPhase.MARKDOWN)
        self.assertIn("空仓观望", report.trading_plan.direction)

    def test_replay_sanquan_keeps_no_trade_zone_after_spring_rally(self) -> None:
        report = self._analyze_until("002216.SZ", "2026-04-03")

        self.assertIsNotNone(report.structure.bc_point)
        self.assertAlmostEqual(report.structure.bc_point.price, 13.27, delta=0.35)
        self.assertEqual(report.structure.phase, WyckoffPhase.MARKUP)
        self.assertIn("空仓观望", report.trading_plan.direction)
        self.assertIn("No Trade Zone", report.trading_plan.current_qualification)

    def test_replay_runze_stays_out_due_to_weak_rr(self) -> None:
        report = self._analyze_until("300442.SZ", "2026-04-03")

        self.assertEqual(report.structure.phase, WyckoffPhase.MARKDOWN)
        self.assertIn("空仓观望", report.trading_plan.direction)
        self.assertLess(report.risk_reward.reward_risk_ratio, 2.5)

    def test_sanquan_continuity_replays_key_daily_transitions(self) -> None:
        expected = {
            "2026-03-20": (WyckoffPhase.ACCUMULATION, "空仓观望", "Phase B/Phase C"),
            "2026-03-23": (WyckoffPhase.ACCUMULATION, "空仓观望", "Spring"),
            "2026-03-24": (WyckoffPhase.ACCUMULATION, "空仓观望", "Spring"),
            "2026-03-26": (WyckoffPhase.MARKUP, "空仓观望", "Markup"),
            "2026-03-30": (WyckoffPhase.MARKUP, "空仓观望", "LPS"),
            "2026-04-03": (WyckoffPhase.MARKUP, "空仓观望", "No Trade Zone"),
        }

        for as_of, (phase, direction, keyword) in expected.items():
            report = self._analyze_until("002216.SZ", as_of)
            self.assertEqual(report.structure.phase, phase, as_of)
            self.assertIn(direction, report.trading_plan.direction, as_of)
            combined = f"{report.signal.description} {report.trading_plan.current_qualification} {report.trading_plan.trigger_condition}"
            self.assertIn(keyword, combined, as_of)

    def test_sanquan_document_alignment_on_right_side_execution_days(self) -> None:
        expected = {
            "2026-03-25": (WyckoffPhase.MARKUP, "做多", "SOS"),
            "2026-04-08": (WyckoffPhase.MARKUP, "持有", "Lack of Supply"),
            "2026-04-13": (WyckoffPhase.MARKUP, "买入", "Test"),
            "2026-04-14": (WyckoffPhase.MARKUP, "买入", "Shakeout"),
            "2026-04-24": (WyckoffPhase.MARKUP, "持有", "BUEC"),
            "2026-04-29": (WyckoffPhase.MARKUP, "持有", "Phase E"),
        }

        for as_of, (phase, direction, keyword) in expected.items():
            report = self._analyze_until("002216.SZ", as_of)
            self.assertEqual(report.structure.phase, phase, as_of)
            combined = " ".join(
                [
                    report.signal.description,
                    report.trading_plan.current_qualification,
                    report.trading_plan.direction,
                    report.trading_plan.trigger_condition,
                ]
            )
            self.assertIn(direction, combined, as_of)
            self.assertIn(keyword, combined, as_of)

    def test_runze_continuity_replays_uncertain_then_markdown(self) -> None:
        expected = {
            "2026-03-30": (WyckoffPhase.UNKNOWN, "空仓观望", "不确定"),
            "2026-03-31": (WyckoffPhase.UNKNOWN, "空仓观望", "不确定"),
            "2026-04-03": (WyckoffPhase.MARKDOWN, "空仓观望", "Markdown"),
        }

        for as_of, (phase, direction, keyword) in expected.items():
            report = self._analyze_until("300442.SZ", as_of)
            self.assertEqual(report.structure.phase, phase, as_of)
            self.assertIn(direction, report.trading_plan.direction, as_of)
            combined = f"{report.signal.description} {report.trading_plan.current_qualification} {report.trading_plan.trigger_condition}"
            self.assertIn(keyword, combined, as_of)

    def test_wangfujing_continuity_stays_markdown(self) -> None:
        for as_of in ("2026-03-20", "2026-04-03"):
            report = self._analyze_until("600859.SH", as_of)
            self.assertEqual(report.structure.phase, WyckoffPhase.MARKDOWN, as_of)
            self.assertIn("空仓观望", report.trading_plan.direction, as_of)

    def test_wangfujing_late_april_stays_markdown(self) -> None:
        for as_of in ("2026-04-23", "2026-04-24", "2026-04-27", "2026-04-28", "2026-04-29"):
            report = self._analyze_until("600859.SH", as_of)
            self.assertEqual(report.structure.phase, WyckoffPhase.MARKDOWN, as_of)
            self.assertIn("Markdown", report.signal.description, as_of)

    def test_runze_late_april_rebound_stays_conservative(self) -> None:
        for as_of in ("2026-04-23", "2026-04-24", "2026-04-27", "2026-04-28", "2026-04-29"):
            report = self._analyze_until("300442.SZ", as_of)
            self.assertEqual(report.structure.phase, WyckoffPhase.UNKNOWN, as_of)
            self.assertIn("空仓观望", report.trading_plan.direction, as_of)

    def test_runze_april_seventh_downgrades_to_sc_candidate_unknown(self) -> None:
        report = self._analyze_until("300442.SZ", "2026-04-07")
        self.assertEqual(report.structure.phase, WyckoffPhase.UNKNOWN)
        combined = " ".join(
            [
                report.signal.description,
                report.trading_plan.current_qualification,
                report.trading_plan.trigger_condition,
            ]
        )
        self.assertIn("SC", combined)
        self.assertIn("空仓观望", report.trading_plan.direction)


if __name__ == "__main__":
    unittest.main()
