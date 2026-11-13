"""Keep an ERP integration that already works on a private address working.

From this release the stored credentials are only sent to a public address, or to
a host listed in the ``crm_erp_trusted_hosts`` site config (see
``crm/integrations/remote_url.py``). A site that was already pointed at a
self-hosted ERP -- ``http://erpnext-frontend:8080``, a 192.168.x address -- would
otherwise lose its sync on the first request after the upgrade, with nothing in
the settings having changed.

So the hosts in the URLs saved *now* are grandfathered, where that is plainly what
the operator set up:

* a host on a private address (RFC 1918, a ULA, a CGNAT/VPN range) is listed;
* a host that does not resolve from here is listed only when its name is itself
  private -- a compose service name with no dot, or one under ``.internal``,
  ``.local``, ``.lan`` or ``.test``. Not resolving in the migrate container is no
  proof the workers cannot reach it;
* a public-looking name whose DNS failed during one migrate is NOT listed: that
  would trust it for good on the strength of a bad minute;
* loopback and link-local addresses -- the server itself, and 169.254.169.254
  where a cloud hands out its own credentials -- are NOT listed. An operator who
  means it can say so; an upgrade does not say it for them;
* a host that resolves to public addresses needs no trust and gets none.

Whatever is not listed is logged, followed by one command that would list all of
it -- one, and built from the final list, because ``set-config`` replaces the
value: a command per host would each undo the others, and this patch's own grant.
The command is shell-quoted, and a saved URL whose host is not a hostname is
neither trusted nor printed: the host is the saved URL's to choose, and the line
is one an operator is told to paste.

This runs inside ``bench migrate``, which is an operator's action: it is still the
case that no application role can grant trust. Hosts already listed are kept, none
is repeated, a second run changes nothing, and a site config that cannot be
written is reported rather than allowed to stop the migrate.
"""

import ipaddress
import json
import shlex
import threading

import frappe
from frappe.installer import update_site_config

from crm.integrations import remote_url

CONFIG = "crm_erp_trusted_hosts"
SAVED_URLS = (
	("CRM Acumatica Settings", "instance_url", "Acumatica Instance URL"),
	("ERPNext CRM Settings", "erpnext_site_url", "SIMERP Site URL"),
)
#: Names nobody can register publicly: unresolved, they are still somebody's own.
PRIVATE_SUFFIXES = (".internal", ".local", ".lan", ".test")
#: Where a cloud serves an instance its own credentials, by name. Never trusted for
#: the operator, resolved or not, private-looking suffix or not.
METADATA_NAMES = frozenset(
	{"metadata", "metadata.google.internal", "instance-data", "instance-data.ec2.internal"}
)
#: A dead resolver must not hold a migrate: getaddrinfo has no timeout of its own.
DNS_TIMEOUT = 3

TRUST, LEAVE, PUBLIC = "trust", "leave", "public"


def execute():
	configured = frappe.conf.get(CONFIG) or []
	if isinstance(configured, str):
		configured = configured.split(",")
	hosts = [str(host).strip() for host in configured if str(host).strip()]
	listed = {host.lower().rstrip(".") for host in hosts}

	added, left = [], []
	for doctype, field, label in SAVED_URLS:
		host = _saved_host(doctype, field, label)
		if not host or host in listed:
			continue
		verdict, reason = _verdict(host)
		if verdict == TRUST:
			_log(f"trusted {host} ({label}): it {reason}, and is already in use")
			added.append(host)
			listed.add(host)
		elif verdict == LEAVE:
			_log(
				f"{host} ({label}) {reason} and was NOT trusted. Requests to it are refused until it is listed."
			)
			left.append(host)
			listed.add(host)

	written = True
	if added:
		try:
			update_site_config(CONFIG, hosts + added, validate=False)
			# the rest of this migrate sees it at once
			frappe.local.conf[CONFIG] = hosts + added
		except Exception as e:
			# a read-only config (a mounted secret, an immutable image) is the
			# operator's arrangement; the migrate goes on and they are told what to add
			written = False
			_log(f"could not write the site config ({type(e).__name__}); nothing was trusted")

	# One command, from the final list: set-config replaces the value, so anything
	# shorter would drop what is already there.
	wanted = hosts + added + left
	if not written and left:
		_log(f"to trust {', '.join(added)}, and also {', '.join(left)} if meant, run: {_command(wanted)}")
	elif not written:
		_log(f"to trust {', '.join(added)}, run: {_command(wanted)}")
	elif left:
		_log(f"to also trust {', '.join(left)}, if that is meant, run: {_command(wanted)}")


def _saved_host(doctype: str, field: str, label: str) -> str | None:
	"""The host of the URL saved in ``field``, read from that one field -- or None,
	when there is no URL or its host is not something to trust, log or print."""
	url = (frappe.db.get_single_value(doctype, field, cache=False) or "").strip()
	if not url:
		return None
	parts = remote_url.origin(url)
	if parts is None:
		# said without the value: it is whatever was typed into the field
		_log(
			f"{label} is not an http(s) URL, or its host is not a valid hostname; "
			"nothing was trusted for it"
		)
		return None
	return parts[1]


def _verdict(host: str) -> tuple[str, str]:
	if host in METADATA_NAMES:
		return LEAVE, "is a cloud metadata name"
	addresses = _addresses(host)
	if addresses is None:
		reason = "did not resolve during the upgrade"
		if "." not in host or host.endswith(PRIVATE_SUFFIXES):
			return TRUST, f"{reason} and is a private name"
		return LEAVE, reason
	if any(_never_trusted(address) for address in addresses):
		return LEAVE, "points at a loopback or link-local address"
	if any(remote_url._is_blocked_ip(address) for address in addresses):
		return TRUST, "is on a private address"
	return PUBLIC, ""


def _never_trusted(address: str) -> bool:
	try:
		ip = ipaddress.ip_address(address.split("%", 1)[0])
	except ValueError:
		return True
	ip = getattr(ip, "ipv4_mapped", None) or ip
	return ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip.is_reserved


def _addresses(host: str) -> list[str] | None:
	"""What ``host`` is or resolves to; None when it does not resolve in time."""
	if host == "localhost" or host.endswith(".localhost"):
		return ["127.0.0.1"]
	try:
		ipaddress.ip_address(host)
		return [host]
	except ValueError:
		pass
	answer = []

	def lookup():
		try:
			answer.append(remote_url._resolve(host))
		except (OSError, UnicodeError):
			pass

	thread = threading.Thread(target=lookup, daemon=True)
	thread.start()
	thread.join(DNS_TIMEOUT)
	return (answer[0] or None) if answer else None


def _command(hosts: list[str]) -> str:
	# quoted for the shell it is pasted into: neither the site name nor a host
	# already in the config is this patch's to vouch for
	return f"bench --site {shlex.quote(frappe.local.site)} set-config -p {CONFIG} {shlex.quote(json.dumps(hosts))}"


def _log(message: str) -> None:
	message = f"{CONFIG}: {message}"
	frappe.logger("crm.integrations").warning(message)
	print(message)  # migrate's own output, where the operator is looking
