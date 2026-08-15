# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The module's import direction is an invariant, so assert it rather than document it.

`errors` <- `config`/`schemas`/`context` <- `client` <- `tools`/`api`. No module may
import one to its right. This is what keeps the pure layers testable without a site and
keeps the transport the only place that knows a model exists -- both properties the rest
of the suite silently relies on, and neither one visible in a diff that breaks it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import frappe
from frappe.tests import UnitTestCase

PACKAGE = "crm.agent"

# Module -> the sibling agent modules it is allowed to import. Anything absent from a
# module's set is a violation, so adding a dependency means editing this map in review.
ALLOWED_SIBLING_IMPORTS = {
	"errors": set(),
	"config": set(),
	"schemas": {"errors"},
	"context": set(),
	"client": {"config", "errors", "schemas"},
	"tools": set(),
	# actions is the write-tier proposal layer: drafts only. It may reach the
	# client but never frappe (test_actions enforces the frappe ban on top).
	"actions": {"client", "config", "context", "schemas"},
	"api": {"actions", "client", "config", "context", "errors", "schemas", "tools"},
	"install": set(),
	# The deterministic tier: signals and predict must work with the agent
	# disabled, so neither may import client (or anything that knows a model
	# exists). config is allowed because the admin-tunable signal thresholds
	# live on the same Single -- it reads settings, it does not know a model
	# exists. predict reuses signals' activity query and its thresholds.
	"signals": {"config"},
	"predict": {"signals"},
}


def _sibling_imports(module: str) -> set[str]:
	"""Agent-package modules imported by ``crm/agent/<module>.py``."""
	source = Path(frappe.get_app_path("crm", "agent", f"{module}.py")).read_text()
	found: set[str] = set()
	for node in ast.walk(ast.parse(source)):
		if isinstance(node, ast.ImportFrom):
			if node.module == PACKAGE:
				found.update(alias.name for alias in node.names)
			elif (node.module or "").startswith(f"{PACKAGE}."):
				found.add(node.module[len(PACKAGE) + 1 :].split(".")[0])
		elif isinstance(node, ast.Import):
			for alias in node.names:
				if alias.name.startswith(f"{PACKAGE}."):
					found.add(alias.name[len(PACKAGE) + 1 :].split(".")[0])
	return {name for name in found if name in ALLOWED_SIBLING_IMPORTS}


class LayeringTest(UnitTestCase):
	def test_no_module_imports_one_to_its_right(self):
		for module, allowed in ALLOWED_SIBLING_IMPORTS.items():
			with self.subTest(module=module):
				unexpected = _sibling_imports(module) - allowed
				self.assertEqual(
					unexpected,
					set(),
					f"crm/agent/{module}.py imports {sorted(unexpected)}, which the layering "
					f"rule does not allow. Permitted: {sorted(allowed) or 'nothing'}.",
				)

	def test_the_pure_layers_import_no_frappe(self):
		"""``context`` and ``errors`` stay importable with no site at all -- that is what
		makes the prompt builder and the exception types usable from any tier later."""
		for module in ("errors", "context"):
			with self.subTest(module=module):
				source = Path(frappe.get_app_path("crm", "agent", f"{module}.py")).read_text()
				imported = set()
				for node in ast.walk(ast.parse(source)):
					if isinstance(node, ast.Import):
						imported.update(alias.name.split(".")[0] for alias in node.names)
					elif isinstance(node, ast.ImportFrom) and node.level == 0:
						imported.add((node.module or "").split(".")[0])
				self.assertNotIn("frappe", imported)

	def test_the_walker_sees_an_illegal_import(self):
		"""Guards the guard: a map-driven check that never fails is worth nothing."""
		self.assertIn("client", _sibling_imports("api"))
		self.assertEqual(_sibling_imports("errors"), set())
