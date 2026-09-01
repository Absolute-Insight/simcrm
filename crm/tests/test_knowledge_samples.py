from frappe.tests import UnitTestCase

from crm.knowledge import load_samples, parse_sample


class SamplePackTest(UnitTestCase):
	def test_every_sample_parses_and_is_marked_as_sample(self):
		samples = load_samples()
		self.assertGreaterEqual(len(samples), 14)
		for s in samples:
			self.assertTrue(s["title"] and s["category"] and s["content"])
			self.assertIn("sample content", s["content"].lower()[:200])
			self.assertTrue(s["tags"], s["name"])

	def test_parse_sample_reads_optional_tags_and_product(self):
		s = parse_sample("x", "---\ntitle: T\ncategory: C\ntags: a, b\n---\nbody")
		self.assertEqual(s["tags"], "a, b")
		self.assertEqual(s["product"], "")
		self.assertEqual(s["content"], "body")

	def test_parse_sample_refuses_missing_title_and_empty_body(self):
		with self.assertRaises(ValueError):
			parse_sample("x", "---\ncategory: C\n---\nbody")
		with self.assertRaises(ValueError):
			parse_sample("x", "---\ntitle: T\ncategory: C\n---\n\n")
