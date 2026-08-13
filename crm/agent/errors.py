# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Agent-layer exceptions.

Stdlib only, so every layer can raise them without an import cycle. Callers are
expected to catch ``AgentUnavailable`` and degrade -- never to surface it to a user.
"""

from __future__ import annotations


class AgentUnavailable(Exception):
	"""The inference endpoint could not be reached, or answered unusably."""


class SchemaMismatch(Exception):
	"""The model's reply did not validate against the requested schema."""
