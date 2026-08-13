# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Tests for the capability layer.

The behavioural tests hit the database on purpose. The invariant tests parse the
module with ``ast`` rather than grepping its text -- the docstring names the sensitive
APIs in order to explain them, so a substring check would fail on the explanation.
"""

from __future__ import annotations

import ast
from pathlib import Path

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from crm.agent import tools

TOOLS_SOURCE = Path(frappe.get_app_path("crm", "agent", "tools.py")).read_text()

# Every ``frappe.*`` callable this module is allowed to reach. ``get_all`` ignores
# permissions, so it is on the list only because ``read_thread`` fetches a record's
# Communications behind an explicit parent-record gate -- see the comment on that call.
# Anything not named here has to be argued for in review before it can be added.
ALLOWED_FRAPPE_CALLS = frozenset(
	{
		"get_list",
		"get_all",
		"get_meta",
		"throw",
		"DoesNotExistError",
	}
)


def _dotted_name(node: ast.expr) -> str | None:
	"""``frappe.db.sql`` -> ``"frappe.db.sql"``; anything not a plain chain -> ``None``."""
	parts: list[str] = []
	while isinstance(node, ast.Attribute):
		parts.append(node.attr)
		node = node.value
	if not isinstance(node, ast.Name):
		return None
	parts.append(node.id)
	return ".".join(reversed(parts))


def _frappe_calls(source: str) -> set[str]:
	"""Every ``frappe...(...)`` call in ``source``, as the part after ``frappe.``.

	The whole attribute chain is walked, so ``frappe.db.sql`` reports as ``db.sql``
	rather than being skipped: an earlier version tested ``node.func.value`` for
	``ast.Name``, which is an ``ast.Attribute`` for exactly the nested bypasses
	(``frappe.db.get_all``, ``frappe.db.sql``) the check exists to catch.
	"""
	names = set()
	for node in ast.walk(ast.parse(source)):
		if not isinstance(node, ast.Call):
			continue
		dotted = _dotted_name(node.func)
		if dotted and dotted.startswith("frappe."):
			names.add(dotted[len("frappe.") :])
	return names


def _call_keywords(source: str) -> set[str]:
	"""Keyword argument names passed to any call, including via ``**{"literal": ...}``."""
	names = set()
	for node in ast.walk(ast.parse(source)):
		if not isinstance(node, ast.Call):
			continue
		for keyword in node.keywords:
			if keyword.arg is not None:
				names.add(keyword.arg)
			elif isinstance(keyword.value, ast.Dict):
				names.update(k.value for k in keyword.value.keys if isinstance(k, ast.Constant))
	return names


class ReadRecordTest(IntegrationTestCase):
	def test_unsupported_doctype_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			tools.read_record("User", "Administrator")

	def test_missing_record_raises_does_not_exist(self):
		with self.assertRaises(frappe.DoesNotExistError):
			tools.read_record("CRM Deal", "CRM-DEAL-does-not-exist")


class ReadThreadTest(IntegrationTestCase):
	def test_unsupported_doctype_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			tools.read_thread("User", "Administrator")

	def test_unreadable_parent_raises_before_any_child_is_read(self):
		with self.assertRaises(frappe.DoesNotExistError):
			tools.read_thread("CRM Deal", "CRM-DEAL-does-not-exist")


class ThreadIsVisibleToOrdinarySalesUsersTest(IntegrationTestCase):
	"""The regression this layer's parent gate exists for.

	frappe's Communication ``permission_query_condition`` keeps only rows whose
	``email_account`` belongs to the reading user, and returns
	``communication_medium != 'Email'`` for a user with no User Email rows. CRM's
	Sales User holds neither System Manager nor Super Email User, so a ``get_list``
	read returns nothing at all here -- while the endpoint still reports success.
	Administrator, who manual verification runs as, cannot see the bug.
	"""

	USER = "agent-thread-reader@crmtest.test"

	def setUp(self):
		super().setUp()
		frappe.db.savepoint("agent_read_thread")
		self.addCleanup(frappe.db.rollback, save_point="agent_read_thread")
		self.addCleanup(frappe.set_user, frappe.session.user)

		if not frappe.db.exists("User", self.USER):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": self.USER,
					"first_name": "Agent Thread Reader",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
			user.add_roles("Sales User")

		deal = frappe.get_doc({"doctype": "CRM Deal", "deal_owner": self.USER})
		deal.flags.ignore_mandatory = True
		deal.flags.ignore_links = True
		self.deal = deal.insert(ignore_permissions=True)

		self.communication = frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"communication_medium": "Email",
				"sent_or_received": "Received",
				"subject": "Re: pricing",
				"content": "Can you send the quote?",
				"sender": "buyer@acme.test",
				"reference_doctype": "CRM Deal",
				"reference_name": deal.name,
			}
		).insert(ignore_permissions=True)

	def test_owner_with_only_the_sales_user_role_sees_the_thread(self):
		frappe.set_user(self.USER)
		roles = frappe.get_roles()
		self.assertNotIn("System Manager", roles)
		self.assertNotIn("Super Email User", roles)

		rows = tools.read_thread("CRM Deal", self.deal.name)
		self.assertEqual([row["name"] for row in rows], [self.communication.name])
		self.assertEqual(rows[0]["sender"], "buyer@acme.test")


class LimitTest(UnitTestCase):
	def test_zero_and_negative_limits_are_clamped(self):
		"""``limit=0`` is falsy in frappe's query builder and so means *unbounded*; a
		negative limit is a SQL error. Both are reachable from an MCP client."""
		self.assertEqual(tools._clamp_limit(0), 1)
		self.assertEqual(tools._clamp_limit(-5), 1)

	def test_oversized_limits_are_capped(self):
		self.assertEqual(tools._clamp_limit(10_000), tools.MAX_THREAD_LIMIT)

	def test_unparseable_limits_fall_back_to_the_default(self):
		self.assertEqual(tools._clamp_limit("many"), tools.DEFAULT_THREAD_LIMIT)
		self.assertEqual(tools._clamp_limit(None), tools.DEFAULT_THREAD_LIMIT)

	def test_a_string_limit_from_an_http_caller_still_works(self):
		self.assertEqual(tools._clamp_limit("10"), 10)


class PermissionInvariantTest(UnitTestCase):
	def test_frappe_calls_stay_inside_the_allowlist(self):
		"""An allowlist, not a ``get_all`` blacklist: the point is that every route out
		of this module is named and justified, not that one known-bad name is absent."""
		unexpected = _frappe_calls(TOOLS_SOURCE) - ALLOWED_FRAPPE_CALLS
		self.assertEqual(
			unexpected,
			set(),
			f"tools.py calls non-allowlisted frappe APIs: {sorted(unexpected)}",
		)

	def test_the_permission_checked_api_is_still_the_default(self):
		self.assertIn("get_list", _frappe_calls(TOOLS_SOURCE))

	def test_the_allowlist_walks_nested_attribute_chains(self):
		"""Guards the walker itself: the blacklist it replaced skipped ``frappe.db.*``."""
		source = "import frappe\nfrappe.db.sql('select 1')\nfrappe.qb.from_('x')\n"
		self.assertEqual(_frappe_calls(source), {"db.sql", "qb.from_"})

	def test_nothing_bypasses_permissions(self):
		self.assertNotIn("ignore_permissions", _call_keywords(TOOLS_SOURCE))

	def test_a_smuggled_ignore_permissions_kwarg_is_still_seen(self):
		"""``**{"ignore_permissions": True}`` is a keyword with ``arg=None``, which the
		plain check would have walked straight past."""
		source = 'import frappe\nfrappe.get_all("X", **{"ignore_permissions": True})\n'
		self.assertIn("ignore_permissions", _call_keywords(source))
