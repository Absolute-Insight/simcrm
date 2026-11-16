"""A second connection to the site database, committed on its own.

For a record that must outlive the request or job that writes it: a guard set
before a call to another system, which has to stay set if that request is then
rolled back or killed -- the very case it exists for. The request's own
transaction cannot hold it (its rollback takes the record with it), and the cache
redis cannot be trusted with it either (a flush, an eviction or a restart forgets
it, and frappe's cache calls swallow a connection error).

Every statement here commits before the block returns, and nothing written
through the request's own ``frappe.db`` is visible to it until that commits. So
a table written through this connection is written ONLY through it: a row the
request's transaction had locked would leave this connection waiting on a lock
its own process holds.
"""

from contextlib import contextmanager

import frappe


@contextmanager
def autonomous_db():
	"""A fresh connection for the block; committed when it ends, rolled back if it
	raises, closed either way. Short-lived on purpose: nothing it reads is a
	snapshot older than the block."""
	from frappe.database import get_db

	conf = frappe.local.conf
	db = get_db(
		socket=conf.db_socket,
		host=conf.db_host,
		port=conf.db_port,
		user=conf.db_user or conf.db_name,
		password=conf.db_password,
		cur_db_name=conf.db_name,
	)
	try:
		db.connect()
		yield db
		db.sql("commit")
	except BaseException:
		try:
			db.sql("rollback")
		except Exception:
			pass
		raise
	finally:
		db.close()


def is_duplicate(db, e: Exception) -> bool:
	"""Whether ``e`` is a UNIQUE or PRIMARY KEY conflict on ``db``."""
	return bool(db.is_duplicate_entry(e) or db.is_unique_key_violation(e))
