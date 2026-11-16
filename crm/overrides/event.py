"""Mixed into frappe's Event and Event Participants controllers by
extend_doctype_class (see hooks.py), for attendees typed by address.

Such a row names no Contact: the Contact behind it is recorded apart, where the
event's owner cannot read it (:mod:`crm.api.attendees`).
"""


class EventTypedAttendees:
	def sync_communication(self):
		"""frappe files the event on each participant's timeline as a Communication
		linked to the row's record. A typed attendee's row names none -- and a
		Communication is readable by every rep, so it must not be given one."""
		rows = self.get("event_participants") or []
		named = [row for row in rows if row.reference_docname]
		if len(named) == len(rows):
			return super().sync_communication()
		self.event_participants = named
		try:
			return super().sync_communication()
		finally:
			self.event_participants = rows


class TypedAttendeeRow:
	def _get_missing_mandatory_fields(self):
		"""The reference is required; a typed attendee resolved by the event's save
		is the one row that legitimately has none."""
		missing = super()._get_missing_mandatory_fields()
		if getattr(self, "_crm_typed_attendee", False):
			missing = [entry for entry in missing if entry[0] != "reference_docname"]
		return missing
