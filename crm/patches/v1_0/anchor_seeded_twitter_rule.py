import frappe

from crm.domain_enrichment.install import SOCIAL_PATTERNS, TWITTER_PATTERN_V1


def execute():
	# The seeded pattern matched "x.com/" inside any host ending in it (wix.com,
	# fedex.com, dropbox.com). Only rows still holding the seeded text are replaced: an
	# admin's own pattern is theirs.
	frappe.db.set_value(
		"CRM Enrichment Rule Pattern",
		{"pattern": TWITTER_PATTERN_V1, "parenttype": "CRM Enrichment Rule"},
		"pattern",
		SOCIAL_PATTERNS["twitter"][0],
		update_modified=False,
	)
