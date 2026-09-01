# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""``ask_analyst``: the gate order, the grant, the plan fallback and the degrade
paths. The client and the data layer are stubbed; nothing here contacts a model."""

from __future__ import annotations

from unittest import mock

import frappe
from frappe.tests import IntegrationTestCase

from crm.agent import api as api_mod
from crm.agent.config import AgentConfig
from crm.agent.errors import AgentUnavailable, SchemaMismatch
from crm.agent.schemas import AnalystAnswer, AnalystPlan

REP = "analyst-rep@crmtest.test"

OFF = AgentConfig(enabled=False, base_url="http://x/v1", model="m", timeout=5, max_tokens=64)
NO_GRANT = AgentConfig(enabled=True, base_url="http://x/v1", model="m", timeout=5, max_tokens=64)
GRANTED = AgentConfig(
	enabled=True, base_url="http://x/v1", model="m", timeout=5, max_tokens=64, analyst_enabled=True
)

TABLE = {
	"key": "won_revenue_by_month",
	"title": "Revenue from won deals by month",
	"source": "CRM",
	"columns": [],
	"rows": [{"month": "2026-08", "value": 10.0}],
	"period": {"from": "2026-01-01", "to": "2026-09-01"},
	"note": "",
	"error": None,
}
ANSWER = AnalystAnswer(answer="Revenue was 10.0 in August.", highlights=["10.0 in 2026-08"], caveats=[])


def make_sales_user(email: str) -> None:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": "Analyst Rep", "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		user.add_roles("Sales User")


def stubs(cfg, complete):
	return (
		mock.patch.object(api_mod, "get_config", return_value=cfg),
		mock.patch.object(api_mod, "_throttled", return_value=False),
		mock.patch.object(api_mod.analyst_data, "enabled_erp", return_value=None),
		mock.patch.object(api_mod.analyst_data, "run_plan", return_value=[TABLE]),
		mock.patch.object(api_mod.client, "complete", side_effect=complete),
	)


class GateTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, frappe.session.user)
		make_sales_user(REP)

	def test_a_sales_user_is_refused_before_anything_runs(self):
		frappe.set_user(REP)
		with mock.patch.object(api_mod, "get_config") as get_config:
			with self.assertRaises(frappe.PermissionError):
				api_mod.ask_analyst("how are we doing?")
		get_config.assert_not_called()

	def test_model_off_and_grant_off_are_distinct_statuses(self):
		with mock.patch.object(api_mod.client, "complete") as complete:
			with mock.patch.object(api_mod, "get_config", return_value=OFF):
				self.assertEqual(api_mod.ask_analyst("q"), {"status": "disabled"})
			with mock.patch.object(api_mod, "get_config", return_value=NO_GRANT):
				self.assertEqual(api_mod.ask_analyst("q"), {"status": "disabled", "reason": "analyst_off"})
		complete.assert_not_called()


class FlowTest(IntegrationTestCase):
	def test_happy_path_returns_the_computed_tables_verbatim(self):
		plan = AnalystPlan(
			metrics=["won_revenue_by_month"], from_date="2026-01-01", to_date="2026-09-01", reasoning=""
		)
		patches = stubs(GRANTED, [plan, ANSWER])
		with patches[0], patches[1], patches[2], patches[3] as run_plan, patches[4] as complete:
			result = api_mod.ask_analyst("how did revenue go?")

		self.assertEqual(result["status"], "ok")
		self.assertEqual(result["answer"], ANSWER.answer)
		self.assertEqual(result["highlights"], ANSWER.highlights)
		self.assertEqual(result["tables"], [TABLE])
		self.assertEqual(result["sources"], ["CRM"])
		self.assertEqual(result["period"], {"from_date": "2026-01-01", "to_date": "2026-09-01"})
		self.assertEqual(run_plan.call_args[0][0]["metrics"], ["won_revenue_by_month"])
		self.assertIs(complete.call_args_list[0][0][1], AnalystPlan)
		self.assertIs(complete.call_args_list[1][0][1], AnalystAnswer)
		# the figures reach the second call's system message
		self.assertIn("10.0", complete.call_args_list[1][0][2][0]["content"])

	def test_a_plan_the_model_cannot_produce_falls_back_to_keywords(self):
		patches = stubs(GRANTED, [SchemaMismatch("no json"), ANSWER])
		with patches[0], patches[1], patches[2], patches[3] as run_plan, patches[4]:
			result = api_mod.ask_analyst("are we behind quota?")
		self.assertEqual(result["status"], "ok")
		self.assertEqual(run_plan.call_args[0][0]["metrics"], ["quota_attainment_by_rep"])

	def test_an_answer_failure_degrades(self):
		plan = AnalystPlan(metrics=["won_revenue_by_month"], from_date="", to_date="", reasoning="")
		patches = stubs(GRANTED, [plan, AgentUnavailable("down")])
		with patches[0], patches[1], patches[2], patches[3], patches[4]:
			result = api_mod.ask_analyst("how did revenue go?")
		self.assertEqual(result, {"status": "unavailable"})

	def test_erp_metrics_are_offered_only_when_an_erp_is_enabled(self):
		plan = AnalystPlan(metrics=["erp_cashflow_by_month"], from_date="", to_date="", reasoning="")
		patches = stubs(GRANTED, [plan, ANSWER])
		with patches[0], patches[1], patches[2], patches[3] as run_plan, patches[4] as complete:
			api_mod.ask_analyst("what is our cashflow?")
		self.assertNotIn("erp_cashflow_by_month", complete.call_args_list[0][0][2][0]["content"])
		# the fallback ran because the only requested metric was unavailable
		self.assertEqual(run_plan.call_args[0][0]["metrics"], ["won_revenue_by_month", "pipeline_by_stage"])
