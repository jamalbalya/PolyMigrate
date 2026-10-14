"""Unit tests for fail-closed boolean output detection in composed migration adapters."""
import ast
import unittest

from polymigrate.migration.boolean_output import has_boolean_print_expression


class BooleanOutputTests(unittest.TestCase):
    def test_direct_comparison_print_is_detected(self):
        self.assertTrue(has_boolean_print_expression(ast.parse("print(count > 1)")))

    def test_boolean_alias_print_is_detected(self):
        self.assertTrue(has_boolean_print_expression(ast.parse("enabled = count > 1\nprint(enabled)")))

    def test_boolean_alias_chain_print_is_detected(self):
        self.assertTrue(has_boolean_print_expression(ast.parse("enabled = count > 1\nother = enabled\nprint(other)")))

    def test_boolean_condition_used_only_for_control_flow_is_allowed(self):
        tree = ast.parse("count = 2\nif count > 1:\n    print('many')\n")
        self.assertFalse(has_boolean_print_expression(tree))

    def test_non_boolean_output_is_allowed(self):
        self.assertFalse(has_boolean_print_expression(ast.parse("count = 2\nprint(count + 1)")))


if __name__ == "__main__":
    unittest.main()
