import importlib
import os
import unittest
from unittest.mock import patch

import src.constants as constants


class ConstantsConfigTests(unittest.TestCase):
    def test_environment_variables_override_default_paths(self) -> None:
        env = {
            "LPPL_TDX_DATA_DIR": "/tmp/tdx",
            "LPPL_VERIFY_OUTPUT_DIR": "/tmp/verify",
            "LPPL_PLOTS_DIR": "/tmp/verify/plots-custom",
            "LPPL_REPORTS_DIR": "/tmp/verify/reports-custom",
            "LPPL_SUMMARY_DIR": "/tmp/verify/summary-custom",
            "LPPL_RAW_DIR": "/tmp/verify/raw-custom",
        }

        with patch.dict(os.environ, env, clear=False):
            reloaded = importlib.reload(constants)

        self.assertEqual(reloaded.TDX_DATA_DIR, "/tmp/tdx")
        self.assertEqual(reloaded.VERIFY_OUTPUT_DIR, "/tmp/verify")
        self.assertEqual(reloaded.PLOTS_OUTPUT_DIR, "/tmp/verify/plots-custom")
        self.assertEqual(reloaded.REPORTS_OUTPUT_DIR, "/tmp/verify/reports-custom")
        self.assertEqual(reloaded.SUMMARY_OUTPUT_DIR, "/tmp/verify/summary-custom")
        self.assertEqual(reloaded.RAW_OUTPUT_DIR, "/tmp/verify/raw-custom")

        importlib.reload(constants)


if __name__ == "__main__":
    unittest.main()
