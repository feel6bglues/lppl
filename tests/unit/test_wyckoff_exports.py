import unittest

from src import wyckoff


class WyckoffExportTests(unittest.TestCase):
    def test_new_engine_and_config_exports_exist(self) -> None:
        self.assertTrue(hasattr(wyckoff, "DataEngine"))
        self.assertTrue(hasattr(wyckoff, "WyckoffConfig"))
        self.assertTrue(hasattr(wyckoff, "load_config"))

    def test_new_model_exports_exist(self) -> None:
        self.assertTrue(hasattr(wyckoff, "BCResult"))
        self.assertTrue(hasattr(wyckoff, "DailyRuleResult"))
        self.assertTrue(hasattr(wyckoff, "PreprocessingResult"))
        self.assertTrue(hasattr(wyckoff, "VisualEvidence"))
        self.assertTrue(hasattr(wyckoff, "ChartManifest"))

    def test_old_state_manager_remains_default_and_multimodal_alias_exists(self) -> None:
        self.assertTrue(hasattr(wyckoff, "StateManager"))
        self.assertTrue(hasattr(wyckoff, "MultimodalStateManager"))


if __name__ == "__main__":
    unittest.main()
