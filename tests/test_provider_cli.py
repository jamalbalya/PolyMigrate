"""Tests for the provider diagnostics command."""
import unittest
from io import StringIO
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

from polymigrate.cli import main
from polymigrate.ai.registry import ProviderRegistry


class ProviderCLITests(unittest.TestCase):
    def test_providers_command_is_offline_and_safe_when_unconfigured(self):
        stdout, stderr = StringIO(), StringIO()
        with patch("polymigrate.cli.build_provider_registry", return_value=(ProviderRegistry(), ())), redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(["providers"])
        self.assertEqual(result, 0)
        self.assertIn("No AI providers configured", stdout.getvalue())
        self.assertNotIn("api_key", stdout.getvalue().lower())
        self.assertEqual(stderr.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
