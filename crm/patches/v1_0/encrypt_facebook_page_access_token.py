"""Move Facebook Page access tokens out of the table and into the encrypted store.

``Facebook Page.access_token`` was a Small Text: every connected page's long-lived
token sat in ``tabFacebook Page`` in the clear, in every backup, and came back from
``/api/resource/Facebook Page`` to anyone who could read the doctype. It is a
Password field now, which keeps the value in ``__Auth`` and a row of asterisks in
the column -- but only for values written from here on. A token already in the
column would stay readable there and fail to decrypt, so each one is moved.

Nothing is dropped: the token a row held is the token ``get_password`` returns
afterwards. Safe to run again -- a row that is already asterisks, or empty, is left
alone, so a token stored since is never overwritten by its own mask.

Written straight to the two tables rather than through ``doc.save()``: the doctype
tracks changes, and a save would copy the plaintext into a Version row.
"""

import frappe
from frappe.utils.password import set_encrypted_password

DOCTYPE = "Facebook Page"
FIELD = "access_token"


def execute():
	if not frappe.db.has_column(DOCTYPE, FIELD):
		return
	# the table itself, not the document API: what is being read is the column
	Page = frappe.qb.DocType(DOCTYPE)
	rows = frappe.qb.from_(Page).select(Page.name, Page[FIELD]).run(as_dict=True)
	for row in rows:
		token = row[FIELD]
		if not token or set(token) == {"*"}:
			continue
		set_encrypted_password(DOCTYPE, row.name, token, FIELD)
		frappe.db.set_value(DOCTYPE, row.name, FIELD, "*" * len(token), update_modified=False)
