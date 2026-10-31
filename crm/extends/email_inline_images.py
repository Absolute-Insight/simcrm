"""Send the images placed in an outgoing email as inline parts.

The email composer uploads a pasted or inserted image as a private File
attached to the deal or lead, and writes its ``/private/files/...`` URL into
the ``<img>``. frappe expands that to an absolute URL when it builds the mail,
and the recipient's mail client fetches it without a session: a 403, so the
customer saw a broken image. Making the upload public is not the answer --
any desk user can list public File rows, so every rep could read images from
deals row scoping hides from them.

frappe already turns ``<img embed="...">`` into a ``cid:`` part, but it reads
whatever path the attribute names without asking whether the sender may see
it. This hook does the same for ``src``, and only for a file that is this
email's own:

- it is attached to the document the email is about -- where the composer
  uploads it. The html is not always the sender's: a reply quotes the received
  mail verbatim, and frappe keeps ``<img src>`` on incoming mail, so an outside
  sender who names ``/private/files/...`` of some other deal would otherwise
  have the rep's reply mail that file back to them;
- it is not in quoted reply content, so an outside sender cannot pull that
  deal's own images out either. The quote is everything from the first
  ``<blockquote>`` (or the composer's ``reply-to-content`` marker) on, not just
  what the blockquote encloses: the composer builds a reply as
  ``<blockquote>${received}</blockquote>`` from a string, so a received mail
  that says ``</blockquote><img ...>`` closes the quote early and puts its
  ``<img>`` after it. The rep's own words go above the quote;
- it is an image, so a quoted ``<img>`` cannot carry a price list out;
- the user building the mail could download it from the CRM (the check behind
  ``/private/files/`` itself);
- it fits in what is left of ``MAX_INLINE_BYTES`` for the email.

Anything else keeps its original URL; the email still goes out.

Runs as the Email Queue ``before_insert`` doc_event: that is the first point
that sees both the built mail -- html expanded to what the recipient gets --
and the document it is about, and it runs in the sender's request, so the
read check is the sender's.
"""

from __future__ import annotations

import html as html_lib
import mimetypes
import os
import re
from email import policy
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.parser import Parser
from urllib.parse import unquote

import frappe
from frappe.email.email_body import add_attachment
from frappe.utils import get_files_path, get_url, random_string

PRIVATE_PREFIX = "/private/files/"

# The documents the composer uploads to. Other queued mail (newsletters, digests)
# is not parsed at all.
REFERENCE_DOCTYPES = ("CRM Deal", "CRM Lead")

# Past this many bytes of images an email keeps the rest as links.
MAX_INLINE_BYTES = 10 * 1024 * 1024

# How frappe itself reads a queued message back (SendMailContext.get_message_object):
# headers are written out as they were, placeholders in them included.
QUEUED = policy.SMTP.clone(refold_source="none")

# `\s` before src so `data-src` is not taken for it.
IMG_SRC = re.compile(r"""(<img\b[^>]*?\ssrc\s*=\s*)(["'])(.*?)\2""", re.IGNORECASE)

# Where quoted reply content starts. A plain text search on purpose: a match
# anywhere -- a comment, an attribute -- only moves the cut-off earlier, so it
# can stop an image being inlined but never let a quoted one through.
QUOTE_START = re.compile(r"<blockquote\b|reply-to-content", re.IGNORECASE)


def embed_private_images(doc, method=None) -> None:
	if not (doc.message and doc.reference_name and doc.reference_doctype in REFERENCE_DOCTYPES):
		return

	try:
		message = Parser(policy=QUEUED).parsestr(doc.message)
		inliner = Inliner(doc.reference_doctype, doc.reference_name)
		alternatives = [part for part in message.walk() if part.get_content_type() == "multipart/alternative"]
		changed = False
		for alternative in alternatives:
			changed |= embed_in(alternative, inliner)
		if changed:
			doc.message = message.as_string()
	except Exception:
		# The mail goes out with its links rather than not at all.
		frappe.log_error(
			title="Could not inline email images",
			reference_doctype=doc.reference_doctype,
			reference_name=doc.reference_name,
		)


def embed_in(alternative, inliner: Inliner) -> bool:
	changed = False
	parts = alternative.get_payload()
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
		message, images = inliner.inline(message)
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
		changed = True
	return changed


class Inliner:
	"""Turns the private ``<img>`` of one email into ``cid:`` parts."""

	def __init__(self, reference_doctype: str, reference_name: str):
		self.reference_doctype = reference_doctype
		self.reference_name = reference_name
		self.bytes_left = MAX_INLINE_BYTES
		self.loaded: dict[str, dict | None] = {}

	def inline(self, message: str) -> tuple[str, list[dict]]:
		"""Point each of this email's own images at a ``cid:`` and return their bytes."""
		site = get_url().rstrip("/")
		images: dict[str, dict] = {}
		quote = QUOTE_START.search(message)
		quote_start = quote.start() if quote else len(message)

		def swap(match: re.Match) -> str:
			if match.start() >= quote_start:
				return match.group(0)
			path = html_lib.unescape(match.group(3))
			if path.startswith(site + "/"):
				path = path[len(site) :]
			path = unquote(path.split("?", 1)[0].split("#", 1)[0])
			if not path.startswith(PRIVATE_PREFIX):
				return match.group(0)

			if path not in self.loaded:
				self.loaded[path] = self.load(path)
			image = self.loaded[path]
			if not image:
				return match.group(0)
			images[path] = image
			return f"{match.group(1)}{match.group(2)}cid:{image['content_id']}{match.group(2)}"

		return IMG_SRC.sub(swap, message), list(images.values())

	def load(self, path: str) -> dict | None:
		file = self.find(path)
		if not file:
			return None

		# A bad row must not stop the email going out, so check rather than
		# letting File.validate_file_path throw.
		base = os.path.realpath(get_files_path(is_private=1))
		full_path = os.path.realpath(file.get_full_path())
		if os.path.commonpath((base, full_path)) != base or not os.path.isfile(full_path):
			return None

		size = os.path.getsize(full_path)
		if size > self.bytes_left:
			return None

		# path is the stored row's, confined to the private files directory just above
		with open(
			full_path, "rb"
		) as f:  # nosemgrep: frappe-semgrep-rules.rules.security.frappe-security-file-traversal
			content = f.read(size + 1)
		if len(content) > self.bytes_left:
			return None
		self.bytes_left -= len(content)

		return {"filename": file.file_name, "content": content, "content_id": random_string(10)}

	def find(self, path: str):
		"""The File behind ``path`` that is an image on this email's document and the sender can read."""
		names = frappe.get_all(
			"File",
			filters={
				"file_url": path,
				"attached_to_doctype": self.reference_doctype,
				"attached_to_name": self.reference_name,
				"is_private": 1,
				"is_folder": 0,
			},
			pluck="name",
		)
		for name in names:
			file = frappe.get_doc("File", name)
			content_type = mimetypes.guess_type(file.file_name or "")[0] or ""
			if content_type.startswith("image/") and file.is_downloadable():
				return file
		return None
