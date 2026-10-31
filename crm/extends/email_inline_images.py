"""Send the private images placed in an outgoing email as inline parts.

The email composer uploads a pasted or inserted image as a private File
attached to the deal or lead, and writes its ``/private/files/...`` URL into
the ``<img>``. frappe expands that to an absolute URL when it builds the mail,
and the recipient's mail client fetches it without a session: a 403, so the
customer saw a broken image. Making the upload public is not the answer --
any desk user can list public File rows, so every rep could read images from
deals row scoping hides from them.

frappe already turns ``<img embed="...">`` into a ``cid:`` part, but it reads
whatever path the attribute names without asking whether the sender may see
it. This hook does the same for ``src`` and asks first: an image becomes an
inline part only when the user building the mail could download it from the
CRM (``find_file_by_url``, the check behind ``/private/files/`` itself).
Anything else is left as it was.

Runs as ``make_email_body_message``, once the html part has been built and
its relative URLs expanded, so it sees exactly what the recipient would.
"""

from __future__ import annotations

import html as html_lib
import os
import re
from email import policy
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import unquote

from frappe.core.doctype.file.utils import find_file_by_url
from frappe.email.email_body import add_attachment
from frappe.utils import get_files_path, get_url, random_string

PRIVATE_PREFIX = "/private/files/"

# `\s` before src so `data-src` is not taken for it.
IMG_SRC = re.compile(r"""(<img\b[^>]*?\ssrc\s*=\s*)(["'])(.*?)\2""", re.IGNORECASE)


def embed_private_images(email) -> None:
	parts = email.msg_alternative.get_payload()
	for index, part in enumerate(parts):
		if part.get_content_type() == "text/html":
			related, html_part = None, part
		elif part.get_content_type() == "multipart/related":
			# frappe's own embed= handling: the html is the first part.
			related, html_part = part, part.get_payload()[0]
		else:
			continue

		charset = html_part.get_content_charset() or "utf-8"
		message = html_part.get_payload(decode=True).decode(charset)
		message, images = inline_private_images(message)
		if not images:
			continue

		new_html = MIMEText(message, "html", "utf-8", policy=policy.SMTP)
		if related is None:
			related = MIMEMultipart("related", policy=policy.SMTP)
			related.attach(new_html)
			parts[index] = related
		else:
			related.get_payload()[0] = new_html

		for image in images:
			add_attachment(
				image["filename"],
				image["content"],
				parent=related,
				content_id=image["content_id"],
				inline=True,
			)


def inline_private_images(message: str) -> tuple[str, list[dict]]:
	"""Point each readable private ``<img>`` at a ``cid:`` and return its bytes."""
	site = get_url().rstrip("/")
	images: list[dict] = []
	content_ids: dict[str, str | None] = {}

	def swap(match: re.Match) -> str:
		path = html_lib.unescape(match.group(3))
		if path.startswith(site + "/"):
			path = path[len(site) :]
		path = unquote(path.split("?", 1)[0].split("#", 1)[0])
		if not path.startswith(PRIVATE_PREFIX):
			return match.group(0)

		if path not in content_ids:
			content_ids[path] = load_image(path, images)
		content_id = content_ids[path]
		if not content_id:
			return match.group(0)
		return f"{match.group(1)}{match.group(2)}cid:{content_id}{match.group(2)}"

	return IMG_SRC.sub(swap, message), images


def load_image(path: str, images: list[dict]) -> str | None:
	file = find_file_by_url(path)
	if not file or file.is_folder or not file.is_private:
		return None

	# A bad row must not stop the email going out, so check rather than
	# letting File.validate_file_path throw.
	base = os.path.realpath(get_files_path(is_private=1))
	full_path = os.path.realpath(file.get_full_path())
	if os.path.commonpath((base, full_path)) != base or not os.path.isfile(full_path):
		return None

	with open(full_path, "rb") as f:
		content = f.read()

	content_id = random_string(10)
	images.append({"filename": file.file_name, "content": content, "content_id": content_id})
	return content_id
