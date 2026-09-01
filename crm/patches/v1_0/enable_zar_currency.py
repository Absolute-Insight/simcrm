from crm.install import ensure_zar_currency


def execute():
	"""Existing sites get ZAR on migrate; fresh installs get it from
	``after_install``, which owns the shared implementation -- patches are
	marked executed, never run, on a fresh install."""
	ensure_zar_currency()
