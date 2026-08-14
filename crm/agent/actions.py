# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The write-tier proposal layer: drafts only, never writes.

Every function here returns a payload for a human to review in a compose
window or ``formDialog()`` — nothing in this module may touch the database.
That is a structural guarantee, not a convention: this module never imports
``frappe`` (``test_actions`` parses the source and fails if it appears), so
there is no route from a compromised model output to a record. Reads happen
in the API layer through ``tools``; sends happen in the client after a human
pressed the button.
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
