import frappe
from frappe.tests import IntegrationTestCase

from crm.api.doc import get_data
from crm.tests.test_row_permissions import ensure_rep

ALICE = "comments-filter-alice@crmtest.test"
BOB = "comments-filter-bob@crmtest.test"


def lead_names(filters):
	result = get_data(
		doctype="CRM Lead",
		filters=filters,
		order_by="modified desc",
		page_length=100,
		view={"view_type": "list"},
	)
	return [row["name"] for row in result["data"]]


def kanban_lead_names(filters):
	result = get_data(
		doctype="CRM Lead",
		filters=filters,
		order_by="modified desc",
		column_field="status",
		title_field="lead_name",
		kanban_columns=[{"name": "New"}],
		view={"view_type": "kanban"},
	)
	return [row["name"] for column in result["data"] for row in column["data"]]


class TestCommentsFilter(IntegrationTestCase):
	"""The Comments filter must search the full comment text, not the `_comments`
	cache that Frappe truncates to ~100 characters."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.marker = frappe.generate_hash(length=10)
		self.matching = self.make_lead("Match")
		self.other = self.make_lead("Other")
		self.add_comment(self.matching, f"{'x' * 150} deep text {self.marker}")
		self.add_comment(self.other, "A short unrelated comment")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def make_lead(self, first_name, **kwargs):
		return frappe.get_doc({"doctype": "CRM Lead", "first_name": first_name, **kwargs}).insert().name

	def add_comment(self, lead, content, comment_type="Comment"):
		frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": comment_type,
				"reference_doctype": "CRM Lead",
				"reference_name": lead,
				"content": content,
			}
		).insert(ignore_permissions=True)

	def test_like_matches_text_past_the_truncated_cache(self):
		names = lead_names({"_comments": ["like", f"%deep text {self.marker}%"]})

		self.assertIn(self.matching, names)
		self.assertNotIn(self.other, names)

	def test_not_like_excludes_leads_with_matching_comment(self):
		names = lead_names({"_comments": ["not like", f"%{self.marker}%"]})

		self.assertNotIn(self.matching, names)
		self.assertIn(self.other, names)

	def test_like_combines_with_other_filters(self):
		filters = {"_comments": ["like", f"%{self.marker}%"]}

		self.assertEqual(lead_names({**filters, "name": self.matching}), [self.matching])
		self.assertEqual(lead_names({**filters, "name": self.other}), [])

	def test_only_comments_of_type_comment_are_searched(self):
		self.add_comment(self.other, f"info {self.marker}", comment_type="Info")

		names = lead_names({"_comments": ["like", f"%info {self.marker}%"]})

		self.assertNotIn(self.other, names)

	def test_no_match_finds_nothing(self):
		self.assertEqual(lead_names({"_comments": ["like", f"%absent {self.marker}%"]}), [])

	def test_not_like_with_no_match_keeps_everything(self):
		names = lead_names({"_comments": ["not like", f"%absent {self.marker}%"]})

		self.assertIn(self.matching, names)
		self.assertIn(self.other, names)

	def test_the_kanban_view_searches_the_full_text(self):
		names = kanban_lead_names({"_comments": ["like", f"%deep text {self.marker}%"]})

		self.assertEqual(names, [self.matching])

	def test_set_and_not_set_still_read_the_field(self):
		"""Only like and not like are about the text; the rest are left to the query."""
		names = lead_names({"_comments": ["is", "set"], "name": ["in", [self.matching]]})

		self.assertEqual(names, [self.matching])

	def test_a_rep_only_finds_leads_they_can_read(self):
		"""The lookup reads Comment unscoped, because a Sales User has no grant on it.
		The list that uses it is what scopes the result."""
		ensure_rep(ALICE, "Alice")
		ensure_rep(BOB, "Bob")
		hers = self.make_lead("Hers", lead_owner=ALICE)
		his = self.make_lead("His", lead_owner=BOB)
		self.add_comment(hers, f"shared {self.marker}")
		self.add_comment(his, f"shared {self.marker}")

		frappe.set_user(ALICE)
		self.assertEqual(lead_names({"_comments": ["like", f"%shared {self.marker}%"]}), [hers])
		self.assertNotIn(his, lead_names({"_comments": ["not like", f"%absent {self.marker}%"]}))

	def test_a_rep_does_not_receive_other_peoples_lead_names(self):
		ensure_rep(ALICE, "Alice")
		ensure_rep(BOB, "Bob")
		his = self.make_lead("His", lead_owner=BOB)
		self.add_comment(his, f"private {self.marker}")

		frappe.set_user(ALICE)
		result = get_data(
			doctype="CRM Lead",
			filters={"_comments": ["like", f"%private {self.marker}%"]},
			order_by="modified desc",
			view={"view_type": "list"},
		)

		self.assertNotIn(his, frappe.as_json(result))
