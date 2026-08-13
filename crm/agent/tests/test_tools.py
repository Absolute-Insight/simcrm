# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Tests for the capability layer.

The behavioural tests hit the database on purpose. The invariant test parses the
module with ``ast`` rather than grepping its text -- the docstring names the forbidden
APIs in order to warn about them, so a substring check would fail on the warning.
"""

from __future__ import annotations

import ast
from pathlib import Path

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from crm.agent import tools

TOOLS_SOURCE = frappe.get_app_path("crm", "agent", "tools.py")


def _frappe_calls(path: str) -> set[str]:
	"""Attribute names of every ``frappe.<name>(...)`` call in a module."""
	tree = ast.parse(Path(path).read_text())
	names = set()
	for node in ast.walk(tree):
		if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
			target = node.func.value
			if isinstance(target, ast.Name) and target.id == "frappe":
				names.add(node.func.attr)
	return names


def _call_keywords(path: str) -> set[str]:
	tree = ast.parse(Path(path).read_text())
	return {keyword.arg for node in ast.walk(tree) if isinstance(node, ast.Call) for keyword in node.keywords}


class ReadRecordTest(IntegrationTestCase):
	def test_unsupported_doctype_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			tools.read_record("User", "Administrator")

	def test_missing_record_raises_does_not_exist(self):
		with self.assertRaises(frappe.DoesNotExistError):
			tools.read_record("CRM Deal", "CRM-DEAL-does-not-exist")


class PermissionInvariantTest(UnitTestCase):
	def test_reads_use_the_permission_checked_api(self):
		"""``get_list`` applies permissions; ``get_all`` does not. Assert the choice."""
		calls = _frappe_calls(TOOLS_SOURCE)
		self.assertIn("get_list", calls)
		self.assertNotIn("get_all", calls)

	def test_nothing_bypasses_permissions(self):
		self.assertNotIn("ignore_permissions", _call_keywords(TOOLS_SOURCE))
