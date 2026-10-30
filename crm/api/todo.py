import frappe
from frappe import _

from crm.fcrm.doctype.crm_notification.crm_notification import notify_user

OWNER_FIELD = {"CRM Lead": "lead_owner", "CRM Deal": "deal_owner"}


def before_insert(doc, method):
	"""Refuse an assignment that hands a lead or deal to someone it may not.

	frappe's ToDo grants create and write to the ``All`` role, and
	:func:`after_insert` mirrors every assignment into ``lead_owner`` /
	``deal_owner``. ``frappe.client.insert`` with a guessed deal name and
	``allocated_to`` set was therefore enough to take the deal -- or, with
	someone else's address, to hand it to them. The owner field is what the
	pipeline, the quota figures and the owner clause of the hierarchy read.

	Refused before the row is written, not after: an open ToDo is itself the
	second clause that grants a rep visibility of a record
	(:mod:`crm.permissions.org_hierarchy`), so a row inserted first and judged
	afterwards both opens the record and makes the judgement circular -- the
	permission check would pass *because* of the row being checked.

	An assignment that does not move the owner is left alone. That is every
	server-side path where the controller wrote the owner field first and then
	called ``assign_agent`` (a converted lead, a public-form lead, an import),
	and it hands the assignee nothing they did not already have.
	"""
	if doc.reference_type not in OWNER_FIELD or not doc.reference_name or not doc.allocated_to:
		return

	_refuse_unless_permitted(doc, doc.owner or frappe.session.user)


def validate(doc, method):
	"""Hold an edit to a ToDo to the rule :func:`before_insert` holds a new one to.

	frappe's ToDo grants write to ``All``, and ``ToDo.has_permission`` passes for
	the row's owner and its assignee, so ``frappe.client.set_value`` reaches any
	field of a ToDo the caller made or was given. Guarding the insert alone left
	two steps around it: insert a reminder that points at nothing (or at a deal,
	allocated to nobody), then point it at any deal and allocate it to yourself;
	or set an assignment a manager cancelled back to Open. Either way the rep is
	left holding a live ToDo on the record, which
	:mod:`crm.permissions.org_hierarchy` reads as read, write and delete.

	So an edit that gives someone a live ToDo on a lead or deal they did not
	hold one on before is judged exactly as that insert would be -- asked of the
	session making the edit, not of the row's owner, who may be the manager who
	wrote the assignment in the first place. Every other edit (closing it,
	rewording it, moving its date) is left alone.
	"""
	if doc.is_new():
		return  # judged by before_insert, against the account inserting it

	opened = _opens(doc)
	if not opened or opened == _opens(doc.get_doc_before_save()):
		return

	_refuse_unless_permitted(doc, frappe.session.user)


def _opens(row) -> tuple | None:
	"""The ``(doctype, name, user)`` a ToDo row makes visible, if it makes any.

	The same rows org_hierarchy counts: on a lead or deal, allocated to someone,
	and not Cancelled.
	"""
	if not row or row.reference_type not in OWNER_FIELD or not row.reference_name or not row.allocated_to:
		return None
	if row.status == "Cancelled":
		return None
	return (row.reference_type, row.reference_name, row.allocated_to)


def _refuse_unless_permitted(doc, user: str) -> None:
	fieldname = OWNER_FIELD[doc.reference_type]
	if frappe.db.get_value(doc.reference_type, doc.reference_name, fieldname) == doc.allocated_to:
		return

	if not may_assign(doc, user):
		frappe.throw(
			_("Not permitted to assign {0} {1}").format(_(doc.reference_type), doc.reference_name),
			frappe.PermissionError,
		)


def may_assign(doc, user: str | None = None) -> bool:
	"""Whether this ToDo may hand its lead or deal to ``allocated_to``.

	Asked of ``user``. For an insert that is ``doc.owner`` -- the account the
	row is being inserted by, which frappe has already set by the time
	``before_insert`` runs -- rather than the session, so a row written in a
	background job is still that account's assignment. For an edit it is the
	session making it. It is a *write* check: assignment moves ownership, not
	just visibility.

	``doc.flags.ignore_permissions`` is deliberately not an exemption.
	``frappe.desk.form.assign_to`` inserts every ToDo with it, including from its
	whitelisted ``add``, which only checks that the caller can *read* the record
	-- trusting the flag would leave the front door open. The exemptions below
	are the contexts that have no session to answer for.
	"""
	if (
		frappe.flags.in_install
		or frappe.flags.in_migrate
		or frappe.flags.in_patch
		or frappe.flags.in_import
		or frappe.flags.ignore_permissions
	):
		return True

	# frappe's own assignment rules: the row carries the rule that made it, and
	# the rule is an administrator's instruction rather than the saving user's.
	# Only while that rule is actually running, though (crm.overrides.assignment_rule):
	# ``assignment_rule`` is an ordinary field, and frappe.client.insert or the
	# whitelisted assign_to.add will write any rule's name into it on request.
	if doc.assignment_rule and doc.assignment_rule == frappe.flags.crm_running_assignment_rule:
		return True

	return bool(
		frappe.has_permission(
			doc.reference_type, "write", doc=doc.reference_name, user=user or doc.owner or frappe.session.user
		)
	)


def after_insert(doc, method):
	if doc.reference_type in OWNER_FIELD and doc.reference_name and doc.allocated_to:
		# Mirror assign_to: the latest assignment owns the record, overriding any
		# prior owner. What may do so is decided in before_insert, above.
		frappe.db.set_value(
			doc.reference_type,
			doc.reference_name,
			OWNER_FIELD[doc.reference_type],
			doc.allocated_to,
			update_modified=False,
		)
		_resync_suggestions(doc, doc.allocated_to)

	if doc.reference_type in ["CRM Lead", "CRM Deal", "CRM Task"] and doc.reference_name and doc.allocated_to:
		notify_assigned_user(doc)


def on_update(doc, method):
	if (
		doc.has_value_changed("status")
		and doc.status == "Cancelled"
		and doc.reference_type in ["CRM Lead", "CRM Deal", "CRM Task"]
		and doc.reference_name
		and doc.allocated_to
	):
		notify_assigned_user(doc, is_cancelled=True)
		clear_owner_on_unassign(doc)


def clear_owner_on_unassign(doc):
	# Owner concept only exists for Lead/Deal, not Task.
	if doc.reference_type not in OWNER_FIELD:
		return
	fieldname = OWNER_FIELD[doc.reference_type]
	# Only the owner's own assignment clears the owner. Ownership is
	# single-valued, so cancelling a co-assignee's ToDo used to strip the record
	# from the rep who owns it -- and out of every owner-based report and quota.
	if frappe.db.get_value(doc.reference_type, doc.reference_name, fieldname) != doc.allocated_to:
		return
	frappe.db.set_value(doc.reference_type, doc.reference_name, fieldname, None, update_modified=False)
	_resync_suggestions(doc, None)


def _resync_suggestions(doc, owner: str | None) -> None:
	"""Move the record's open suggestions to the owner just written.

	The owner is written here with ``db.set_value``, which fires no on_update, so
	the resync crm.automation runs when a lead or deal is saved with a new owner
	never ran for "Assign to": the previous rep kept the suggestions until they
	expired, possibly for a record they can no longer open.
	"""
	from crm.agent.signals import resync_owner

	resync_owner(doc.reference_type, doc.reference_name, owner)


def notify_assigned_user(doc, is_cancelled=False):
	_doc = frappe.get_doc(doc.reference_type, doc.reference_name)
	owner = frappe.get_cached_value("User", frappe.session.user, "full_name")
	notification_text = get_notification_text(owner, doc, _doc, is_cancelled)

	message = (
		_("Your assignment on {0} {1} has been removed by {2}").format(
			doc.reference_type, doc.reference_name, owner
		)
		if is_cancelled
		else _("{0} assigned a {1} {2} to you").format(owner, doc.reference_type, doc.reference_name)
	)

	redirect_to_doctype, redirect_to_name = get_redirect_to_doc(doc)

	notify_user(
		{
			"owner": frappe.session.user,
			"assigned_to": doc.allocated_to,
			"notification_type": "Assignment",
			"message": message,
			"notification_text": notification_text,
			"reference_doctype": doc.reference_type,
			"reference_docname": doc.reference_name,
			"redirect_to_doctype": redirect_to_doctype,
			"redirect_to_docname": redirect_to_name,
		}
	)


def get_notification_text(owner, doc, reference_doc, is_cancelled=False):
	name = doc.reference_name
	doctype = doc.reference_type

	if doctype.startswith("CRM "):
		doctype = doctype[4:].lower()

	if doctype in ["lead", "deal"]:
		name = (
			reference_doc.lead_name or name
			if doctype == "lead"
			else reference_doc.organization or reference_doc.lead_name or name
		)

		if is_cancelled:
			return f"""
                <div class="mb-2 leading-5 text-ink-gray-5">
                    <span>{
				_("Your assignment on {0} {1} has been removed by {2}").format(
					doctype,
					f'<span class="font-medium text-ink-gray-9">{name}</span>',
					f'<span class="font-medium text-ink-gray-9">{owner}</span>',
				)
			}</span>
                </div>
            """

		return f"""
            <div class="mb-2 leading-5 text-ink-gray-5">
                <span class="font-medium text-ink-gray-9">{owner}</span>
                <span>{
			_("assigned a {0} {1} to you").format(
				doctype, f'<span class="font-medium text-ink-gray-9">{name}</span>'
			)
		}</span>
            </div>
        """

	if doctype == "task":
		if is_cancelled:
			return f"""
                <div class="mb-2 leading-5 text-ink-gray-5">
                    <span>{
				_("Your assignment on task {0} has been removed by {1}").format(
					f'<span class="font-medium text-ink-gray-9">{reference_doc.title}</span>',
					f'<span class="font-medium text-ink-gray-9">{owner}</span>',
				)
			}</span>
                </div>
            """
		return f"""
            <div class="mb-2 leading-5 text-ink-gray-5">
                <span class="font-medium text-ink-gray-9">{owner}</span>
                <span>{
			_("assigned a new task {0} to you").format(
				f'<span class="font-medium text-ink-gray-9">{reference_doc.title}</span>'
			)
		}</span>
            </div>
        """


def get_redirect_to_doc(doc):
	if doc.reference_type == "CRM Task":
		reference_doc = frappe.get_doc(doc.reference_type, doc.reference_name)
		return reference_doc.reference_doctype, reference_doc.reference_docname

	return doc.reference_type, doc.reference_name
