import unittest
from unittest.mock import patch

from src.cli.main import dispatch_subcommand, main


class CliEntrypointTests(unittest.TestCase):
    def test_dispatch_subcommand_routes_legacy_wyckoff(self) -> None:
        with patch("src.cli.wyckoff_analysis.main", return_value=None) as mock_main:
            result = dispatch_subcommand(["wyckoff", "--symbol", "000001.SH"])

        self.assertEqual(result, 0)
        mock_main.assert_called_once_with()

    def test_dispatch_subcommand_routes_multimodal_wyckoff(self) -> None:
        with patch("src.cli.wyckoff_multimodal_analysis.main", return_value=None) as mock_main:
            result = dispatch_subcommand(["wyckoff-multimodal", "--symbol", "000300.SH"])

        self.assertEqual(result, 0)
        mock_main.assert_called_once_with()

    def test_main_uses_dispatch_before_lppl_flow(self) -> None:
        with patch("src.cli.main.dispatch_subcommand", return_value=0) as mock_dispatch:
            result = main(["wyckoff-multimodal", "--symbol", "000300.SH"])

        self.assertEqual(result, 0)
        mock_dispatch.assert_called_once_with(["wyckoff-multimodal", "--symbol", "000300.SH"])


if __name__ == "__main__":
    unittest.main()
