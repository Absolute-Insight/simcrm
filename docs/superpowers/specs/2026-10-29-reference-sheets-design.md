# Reference sheets: exact answers with a citation to the cell

2026-10-29. Prompted by MBP Engineering's six sales reference PDFs (flange
drilling tables, flange bolt dimensions, line sizes, rating & bar, IP ratings,
valve material equivalents).

## Intent

Reps are not technical. A rep asks the Assistant a plain question — "which
bolts for a 6 inch SABS 1600 flange?" — and must get an answer that is
**exactly what the company's sheet says**, with a reference to the precise row
on the actual document so anyone can check it in one click.

A knowledge article is prose the model paraphrases. A drilling table is a grid
of numbers where a paraphrase that swaps one digit is a wrong flange. So the
sheets are not articles: they are rows of labelled cells, each anchored to its
page and position in the PDF.

## Goals

- Plain-language questions find the right row deterministically: sizes in
  inches or millimetres, "PN16"/"1600 kPa"/"16/3", "ANSI"/"ASME"/"ASA".
- The model only phrases the answer. **Every number in the answer must appear
  in the cited rows** (or the question); otherwise the model's text is
  discarded and the rows themselves are shown. The rep never sees a figure the
  sheet does not hold.
- Each cited row is a chip under the answer. It opens a viewer: the row's
  values as a table, and the PDF page with that row and the cells used
  highlighted, plus a link to the original PDF at that page.
- Cells the company has not confirmed (the errata list sent to MBP) are
  withheld: the model never sees their value, the viewer says "awaiting
  confirmation", and the page image still lets the rep see the sheet.
- When the model is unreachable, a question that matched rows still gets the
  rows. A lookup table does not need a model to be read.

## Non-goals

- No in-app PDF parsing. Sheet layouts are bespoke (rotated headers, two
  tables per page, merged cells); a generic parser would be confidently wrong.
  A sheet is loaded as a **pack** built offline per customer: rows, cells,
  boxes, page images and the PDF.
- No in-app cell editor. Corrections arrive from the customer's engineers and
  are applied by rebuilding the pack and re-importing it, which replaces that
  sheet's rows.
- No change to knowledge articles or the Mentor.

## Anti-goals

- A plausible number that is not on the sheet. Worse than "I don't know".
- A citation that points at the wrong place.
- Customer documents in the repository. Packs are site data, never shipped.

## Shape

- `CRM Reference Sheet` — one per PDF: title, `sheet_key` (stable pack key),
  the private PDF, page images and their sizes, an availability switch, a note
  (provenance, e.g. third-party copyright).
- `CRM Reference Entry` — one per row: page, label, section, search text,
  `cells` (label, value, box, status, note) and the row box. Read by Sales
  User, like knowledge articles; written only by the importer.
- `crm/agent/reference.py` — pure: query normalisation, entry selection, the
  prompt block, the number check, the deterministic fallback, which cells to
  highlight.
- `ask_assistant` — selects entries alongside articles; when entries match it
  answers with `ReferenceAnswer` (adds `cited_rows`), checks numbers, and
  returns `references` carrying everything the viewer needs.
- `crm.api.reference` — list sheets / toggle availability (admin), read one
  sheet for the viewer, and `import_pack(path)` for `bench execute` only.
- Frontend — reference chips in the Assistant, `ReferenceViewerModal`, a
  "Reference sheets" section in Settings → Knowledge.

## Pack format

`manifest.json` beside the PDFs and page images it names (bare file names,
nothing else is read):

```json
{"version": 1, "sheets": [{
  "key": "flange-drilling", "title": "Flange Drilling Tables", "note": "",
  "file": "drilling.pdf",
  "pages": [{"page": 1, "width": 842.0, "height": 595.0, "image": "drilling-1.png"}],
  "entries": [{
    "page": 1, "section": "Flange drilling", "label": "150 mm (6\") · SABS 1123 · 1600/3",
    "search": "150 mm 6\" SABS 1123 1600/3 1600 kPa PN16",
    "bbox": [x0, top, x1, bottom],
    "cells": [{"label": "PCD", "value": "240.0", "unit": "mm", "bbox": [..],
               "status": "ok"}, {"label": "Bolt hole diameter", "value": "22.0",
               "status": "questioned", "note": "Errata 8: should it be 26.0?"}]
  }]}]}
```

Boxes are PDF points from the page's top-left, as pdfplumber reports them.

## Calls made

- Bolt sheet: one entry per size × standard column, the "4 Off M12 x 45"
  value kept verbatim and split into quantity / size / length cells.
- Retrieval needs a size match when the question names a size: a 6" question
  never cites a 4" row, however well the rest scores.
- The check is per claim (line, list item, sentence): all of a claim's
  figures must come from one row, so a list may take each line from its own
  row but one line may not mix two. A figure equal to an unconfirmed value on
  a cited row is refused even when another row holds the same digits.
- Number words up to twenty count as numbers for the check ("eight bolts").
- The viewer draws faint guide bands from the page edges to the row and the
  quoted cell, so the cell can be traced to its headings at "fit page".
- The MBP pack builder lives with the MBP working files, not in this repo.
