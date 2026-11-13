"""Where an ERP integration may send the credentials it stores.

CRM Acumatica Settings and ERPNext CRM Settings each hold a URL and the secrets
that are sent to it, in one document a Sales Manager can write. The secrets are
masked on read, but whoever can change the URL can have them posted anywhere: to
a host of their own, or to a service on the server's private network.

So the URL is checked when it is saved, the host is checked again when a request
is about to carry the secrets (a name can change what it resolves to), and the
controllers refuse to carry a stored secret over to a different host
(``carried_secrets``).

A self-hosted ERP is legitimately on a private address, and often on plain http
inside a compose network. That is an operator's decision, made in the site config
where no application role can reach it::

    bench --site <site> set-config -p crm_erp_trusted_hosts '["erpnext.internal"]'

A host listed there may resolve to a private address and may be reached over
http. Nothing else may, outside developer mode (which allows http only).
"""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

import frappe
from frappe import _

from crm.domain_enrichment.http import _is_blocked_ip

TRUSTED_HOSTS_CONFIG = "crm_erp_trusted_hosts"

# Characters urlparse drops or passes through that another parser reads otherwise.
_URL_NOISE = re.compile(r"[\s\x00-\x20\x7f\\]")
_DEFAULT_PORTS = {"http": 80, "https": 443}
# underscore included: compose service names have it, whatever DNS says
_HOSTNAME = re.compile(r"[a-z0-9]([a-z0-9._-]{0,251}[a-z0-9])?")


class RemoteHostNotAllowed(frappe.ValidationError):
	"""The URL's host is not one the stored credentials may be sent to."""


def trusted_hosts() -> set[str]:
	"""Hosts the operator allowed in the site config, lower-cased."""
	configured = frappe.conf.get(TRUSTED_HOSTS_CONFIG) or []
	if isinstance(configured, str):
		configured = configured.split(",")
	return {str(host).strip().lower().rstrip(".") for host in configured if str(host).strip()}


def _insecure_scheme_allowed() -> bool:
	return bool(frappe.conf.get("developer_mode"))


def _parse(url: str):
	"""``(scheme, host, port)`` of ``url``, or None when it is not a usable URL."""
	url = (url or "").strip()
	if not url or _URL_NOISE.search(url):
		return None
	try:
		parsed = urlparse(url)
		port = parsed.port
	except ValueError:
		return None
	scheme = (parsed.scheme or "").lower()
	host = (parsed.hostname or "").lower().rstrip(".")
	if scheme not in _DEFAULT_PORTS or not _is_hostname(host):
		return None
	return scheme, host, port or _DEFAULT_PORTS[scheme]


def _is_hostname(host: str) -> bool:
	"""An IP literal, or a name made of what names are made of.

	urlparse returns whatever sat between ``//`` and the next ``/`` -- quotes,
	semicolons, ``$(...)``. The host goes on into log lines, error messages and the
	``set-config`` command an operator is told to run, so nothing else gets that far.
	(An internationalised name is written in its ASCII form, ``xn--...``.)"""
	if not host:
		return False
	try:
		ipaddress.ip_address(host)
		return True
	except ValueError:
		return bool(_HOSTNAME.fullmatch(host))


def origin(url: str | None):
	"""What "the same host" means for a stored secret: scheme, host and port.

	None for no URL, and for one that cannot be parsed -- which is therefore never
	the same host as anything, itself included."""
	return _parse(url or "")


def host_changed(old: str | None, new: str | None) -> bool:
	old_origin, new_origin = origin(old), origin(new)
	if old_origin is None and new_origin is None:
		# both empty is no change; two unreadable values are not known to be equal
		return (old or "").strip() != (new or "").strip()
	return old_origin != new_origin


def _resolve(host: str) -> list[str]:
	return list({info[4][0] for info in socket.getaddrinfo(host, None)})


def host_state(host: str) -> str:
	"""Where ``host`` leads right now.

	``public``     every address it resolves to is globally routable
	``internal``   it is, or resolves to, a loopback, private or link-local address
	``unresolved`` the resolver has no answer: nothing can be sent to it, and
	               ``ensure_host_allowed`` asks again before anything is
	``invalid``    the resolver could not even encode the name (an IDN error). Not
	               "no answer": the connection encodes names its own way and might
	               get one, so this is refused like an internal host
	"""
	if host == "localhost" or host.endswith(".localhost"):
		return "internal"
	try:
		ipaddress.ip_address(host)
	except ValueError:
		pass
	else:
		return "internal" if _is_blocked_ip(host) else "public"
	try:
		addresses = _resolve(host)
	except UnicodeError:
		return "invalid"
	except OSError:
		return "unresolved"
	if not addresses:
		return "unresolved"
	return "internal" if any(_is_blocked_ip(address) for address in addresses) else "public"


def _refused(host: str) -> bool:
	return host_state(host) in ("internal", "invalid")


def validate_remote_url(url: str | None, label: str) -> str:
	"""The URL as it should be stored, or a ValidationError saying what is wrong.

	https only, unless the site is in developer mode or the host is one the
	operator trusts; no credentials inside the URL; and no host on a loopback,
	private or link-local address unless the operator trusts it."""
	url = (url or "").strip()
	if not url:
		return ""
	parts = _parse(url)
	if parts is None:
		frappe.throw(_("{0} is not a valid http(s) URL").format(label), title=_("Invalid URL"))
	scheme, host, _port = parts
	_refuse_credentials_in_url(url, label)
	trusted = host in trusted_hosts()
	if scheme != "https" and not (trusted or _insecure_scheme_allowed()):
		frappe.throw(
			_(
				"{0} must start with https://. Plain http is accepted only for a host an "
				"administrator has added to {1} in the site config."
			).format(label, TRUSTED_HOSTS_CONFIG),
			title=_("Invalid URL"),
		)
	if not trusted and _refused(host):
		frappe.throw(
			_internal_host_message(host, label), RemoteHostNotAllowed, title=_("Address not allowed")
		)
	return url.rstrip("/")


def _refuse_credentials_in_url(url: str, label: str) -> None:
	parsed = urlparse(url)
	if parsed.username or parsed.password:
		frappe.throw(
			_("{0} must not contain a username or password").format(label),
			title=_("Invalid URL"),
		)


def ensure_host_allowed(url: str | None, label: str) -> None:
	"""Called as a request is about to carry the stored secrets to ``url``.

	The save-time check saw what the name resolved to then. This sees what it
	resolves to now, so a name re-pointed at an internal address since -- or one
	that did not resolve when it was saved -- is refused before anything is sent.
	(The connection itself resolves once more; a host that changes its answer
	between this check and that one is not caught here.)"""
	parts = _parse(url or "")
	if parts is None:
		raise RemoteHostNotAllowed(_("{0} is not a valid http(s) URL").format(label))
	host = parts[1]
	if host in trusted_hosts():
		return
	if _refused(host):
		# raised, not frappe.throw: this runs inside jobs and status panels, where a
		# queued msgprint would surface on somebody's unrelated request
		raise RemoteHostNotAllowed(_internal_host_message(host, label))


def refuse_redirect(response, label: str) -> None:
	"""Called on the answer to a request made with ``allow_redirects=False``.

	The host was checked; where it sends the request next was not. Followed, a 307
	re-posts the body -- the login -- to a host of the sender's choosing, and any
	redirect reaches addresses the check exists to keep out of reach."""
	if 300 <= int(response.status_code) < 400:
		raise RemoteHostNotAllowed(
			_(
				"{0} answered with a redirect ({1}), which is not followed. "
				"Enter the address the server answers on directly."
			).format(label, response.status_code)
		)


def _internal_host_message(host: str, label: str) -> str:
	# The host is the one whoever reads this typed or saved, so it is named: they
	# have to pass it on to the administrator. What it resolved to is not -- one
	# answer for every internal target, so the reply maps nothing of the server's
	# network -- and goes to the server log instead.
	frappe.logger("crm.integrations").info(f"refused {label}: {host} is not a public address")
	return _(
		"{0}: {1} is not a public address. To connect to a server on a private network, "
		"an administrator has to add {1} to {2} in the site config."
	).format(label, host, TRUSTED_HOSTS_CONFIG)


def validate_url_field(doc, url_field: str, secret_fields: tuple[str, ...]) -> None:
	"""Run from a settings controller's ``validate``, enabled or not.

	Only a URL that moves to another origin -- scheme, host or port -- is judged, so
	a site whose stored URL predates these rules can still save its other settings,
	fix a path or add a slash; ``ensure_host_allowed`` is what holds for a URL
	already stored. A moved URL is validated, and the secrets stored for the old
	host do not follow it: the save is refused until they are entered again, or --
	when the URL is being removed -- they are cleared with it.
	"""
	before = doc.get_doc_before_save()
	previous = ((before.get(url_field) if before else "") or "").strip()
	current = (doc.get(url_field) or "").strip()
	if current == previous:
		return
	label = _(doc.meta.get_label(url_field))
	if not host_changed(previous, current):
		# the same server the secrets were entered for; only the path is new
		_refuse_credentials_in_url(current, label)
		doc.set(url_field, current.rstrip("/"))
		return
	carried = carried_secrets(doc, url_field, secret_fields)
	if not current:
		doc.set(url_field, "")
		for field in carried:
			# with no host left, a stored secret is one waiting for the next URL
			doc.set(field, "")
		return
	doc.set(url_field, validate_remote_url(current, label))
	if carried:
		frappe.throw(
			_(
				"Enter {0} again to change {1}. Stored credentials are only sent to the server "
				"they were entered for."
			).format(", ".join(_(doc.meta.get_label(field)) for field in carried), label),
			title=_("Credentials needed"),
		)


def carried_secrets(doc, url_field: str, secret_fields: tuple[str, ...]) -> list[str]:
	"""The stored secrets a save would carry over to a different host.

	``doc`` is being validated. When the host in ``url_field`` is not the one the
	stored document has, a secret field still holding its mask (``*****``) is one
	nobody entered for the new host: the caller refuses the save, or clears the
	field when the URL is being removed. A secret typed in this same save is the
	saver's own, and stays."""
	before = doc.get_doc_before_save()
	previous = before.get(url_field) if before else None
	if not host_changed(previous, doc.get(url_field)):
		return []
	return [field for field in secret_fields if doc.get(field) and doc.is_dummy_password(doc.get(field))]
