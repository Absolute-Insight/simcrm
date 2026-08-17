from urllib.parse import urlparse, urlunparse

from frappe.utils import get_url

# Ports a bench serves on locally. Twilio has to reach these callbacks from the
# public internet, so a URL on one of them is never the address to hand it --
# the site is behind a proxy and the proxy is on 80/443.
#
# An explicit set, because the old implementation was ``split(":8", 1)[0]``:
# that strips from the first ``:8`` onwards, so it ate **any** port beginning
# with 8. A site on ``:8443`` -- the conventional alternative HTTPS port, and a
# perfectly public one -- silently handed Twilio a URL with no port at all, and
# every callback went to the wrong place with nothing to say why.
LOCAL_PORTS = frozenset({8000, 8080, 9000})


def get_public_url(path: str | None = None) -> str:
	"""The externally reachable base URL for a Twilio callback, plus ``path``.

	Prefers whatever ``get_url()`` says, which already honours ``host_name`` from
	site config -- an admin who has set that has told us their public address and
	we should not second-guess it. Only a recognised bench port is dropped.
	"""
	parsed = urlparse(get_url())
	if parsed.port in LOCAL_PORTS:
		parsed = parsed._replace(netloc=parsed.hostname or parsed.netloc)
	# `path or ""`: the signature has defaulted to None since this was written,
	# and `str + None` raises -- so calling it with no path, as the type hint
	# invites, was a TypeError rather than the base URL.
	return urlunparse(parsed).rstrip("/") + (path or "")


def merge_dicts(d1: dict, d2: dict):
	"""Merge dicts of dictionaries.
	>>> merge_dicts(
		{'name1': {'age': 20}, 'name2': {'age': 30}},
		{'name1': {'phone': '+xxx'}, 'name2': {'phone': '+yyy'}, 'name3': {'phone': '+zzz'}}
	)
	... {'name1': {'age': 20, 'phone': '+xxx'}, 'name2': {'age': 30, 'phone': '+yyy'}}
	"""
	return {k: {**v, **d2.get(k, {})} for k, v in d1.items()}
