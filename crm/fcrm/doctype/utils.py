from copy import deepcopy

LOST_REASON_SECTION = {
	"name": "lost_reason_section",
	"label": "Lost Reason",
	"opened": True,
	"columns": [
		{
			"name": "lost_reason_column",
			"fields": ["lost_reason", "lost_notes"],
		}
	],
}


def with_lost_reason_section(sections: list) -> list:
	"""``sections`` with the Lost Reason section in it, once.

	The section lives in the side-panel layout for good, and the page shows it
	only on a record whose status is Lost-type (SidePanelLayout.vue). It used to
	be added and removed by saving this one shared layout from each record's
	validate, so every deal (or lead) page showed whatever the last status
	change anywhere on the site called for.
	"""
	if any(section.get("name") == LOST_REASON_SECTION["name"] for section in sections):
		return sections
	section = deepcopy(LOST_REASON_SECTION)
	if sections and sections[0].get("name") == "contacts_section":
		return [*sections[:1], section, *sections[1:]]
	return [section, *sections]
