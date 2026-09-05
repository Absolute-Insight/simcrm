from crm.integrations.acumatica.install import ensure_custom_fields


def execute():
	# Unconditional since #166: the fields are schema, not a feature flag. Sites
	# where this already ran as a no-op get them from the after_migrate hook.
	ensure_custom_fields()
