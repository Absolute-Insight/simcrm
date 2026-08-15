# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The write-tier proposal layer: drafts only, never writes.

Every function here returns a payload for a human to review in a compose
window or ``formDialog()`` — nothing in this module touches the database.
What is actually enforced: this module imports no frappe symbol directly
(``test_actions`` parses the source and fails if one appears) and performs no
DB access of its own. It is not transitive isolation — ``config`` imports
frappe — so read the diff, not just the test. Reads happen in the API layer
through ``tools``; sends happen in the client after a human pressed the
button.
"""

from __future__ import annotations

from crm.agent import client
from crm.agent.config import AgentConfig
from crm.agent.context import build_reply_messages
from crm.agent.schemas import ReplyDraft


def propose_reply(cfg: AgentConfig, record: dict, thread: list[dict]) -> ReplyDraft:
	"""A reply draft for the latest inbound message on ``record``'s thread.

	Raises AgentUnavailable / SchemaMismatch like every client call; the API
	layer turns those into a degrade status.
	"""
	messages = build_reply_messages(record, thread)
	return client.complete(cfg, ReplyDraft, messages)
