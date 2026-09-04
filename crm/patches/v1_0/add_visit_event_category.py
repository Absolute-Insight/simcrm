from crm.install import ensure_visit_event_category


def execute():
	"""Existing sites get the "Visit" event category on migrate; fresh installs get it
	from ``after_install``, which owns the shared implementation -- patches are marked
	executed, never run, on a fresh install."""
	ensure_visit_event_category()
