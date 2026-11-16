"""Add File.crm_thumbnail_of, which marks the thumbnails crm.utils.thumbnails makes.

Only the column: existing images are thumbnailed by the hourly
``backfill_thumbnails`` job, 200 a run, so an upgrade does not wait on Pillow
working through every photo on the site.
"""

from crm.utils.thumbnails import ensure_thumbnail_field


def execute():
	ensure_thumbnail_field()
