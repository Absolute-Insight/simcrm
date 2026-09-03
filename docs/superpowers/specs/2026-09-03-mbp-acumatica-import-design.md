# MBP Acumatica spreadsheet import — design

**Date:** 2026-09-03
**Status:** drafted in session, pending review
**Context:** the 2026-09-02 demo to MBP Engineers went well and they supplied
four Acumatica Excel exports for a trial. This covers getting that data onto the
production site and running the pilot against it.

## Goal

MBP's real customers and open pipeline in Vectora, on the existing production
site, so a pilot with their own reps judges the product against their own data
rather than against seeded fiction.

## Decisions already taken

Settled in session on 2026-09-03; recorded here so the plan does not reopen them.

| Decision | Outcome |
|---|---|
| Where the trial lives | The **existing site**, `vectora.absolute-insight.ai`. No second Frappe site, no `mbp.*` hostname, no DNS or Caddy change, `host_name` stays unset. |
| Demo data | Cleared before the import, via `clear_demo_data()`. |
| Backups | **Deferred by the user.** No cron, no offsite. |

The backup decision has one consequence this plan must carry: a manual
`bench --site all backup --with-files` immediately before the import is the
*only* way back from a bad mapping. It is a required step, not a precaution.

## Non-goals

- **Purchase Orders are not imported.** Vendor-side procurement; Vectora models
  no vendor, PO or production order. See the file survey below.
- **No invoice records.** Vectora is a CRM and has no invoice doctype. Invoice
  rows are used only to derive a per-organization revenue figure.
- **No live Acumatica API sync.** The existing integration stays off. This is a
  one-way file import that leaves the door open to enabling sync later.
- **No contact/person import** — there is no source data for it. This is the
  single biggest gap and the top ask of MBP; see *Gaps*.

## Source data

Four Excel exports taken 2026-09-02, all ZAR, all with header rows. Column
lists and one sample row per file were supplied in session.

### Global transform rules

These apply to every file and are the parts most likely to corrupt data
silently. Each gets a unit test.

**Dates are `DD/MM/YYYY`.** Proven by `20/10/2025` in the Customers export —
day 20 cannot be a month. Parse with an explicit format string; never hand
these to a permissive inferring parser, because `02/09/2026` is valid under
both readings and a wrong one fails *silently* for every day ≤ 12. Frappe
stores `YYYY-MM-DD`.

This compounds with a known production hazard: `deploy/README.md:714` records
153,661 future-dated `creation`/`modified` values from the last deployment
sorting real records below every seeded row in list views ordered by
last-modified. Imported dates that land in the future reproduce it.

**Numbers carry thousands separators and trailing whitespace.** `20,359.60 `,
`30.00 `, `33.82 `, `0.00 `. Strip both before converting; use `Decimal`, not
`float`, for money.

**Currency is `ZAR` throughout.** `ensure_zar_currency()` runs at install
(`crm/install.py:40`), so the `Currency` record is guaranteed to exist.

**Country is ISO-2.** `ZA` must map to `South Africa` — Frappe's `Country`
doctype is keyed on the full name.

**Placeholder emails must be filtered.** `no@email.co.za` appears in the sample
Customers row. Import no address matching a placeholder pattern; an obviously
fake address is worse than a blank one, because it looks actionable. Production
has a live IONOS outgoing account.

**Phone numbers are local SA format.** `0792530729`, no `+27`. Normalise on
the way in.

### File 1 — Customers → `CRM Organization` + `Address`

The cleanest fit of the four.

| Column | Sample | Target | Note |
|---|---|---|---|
| Customer ID | `C-2HK001` | `CRM Organization.acumatica_id` | custom field, read-only |
| Customer Name | `2HK Trading & Projects (Pty) Ltd - COD` | `organization_name` | **docname**; see Open decision 1 |
| Currency ID | `ZAR` | `currency` | Link → Currency |
| Customer Status | `Active` | *filter* | import Active only |
| Address Line 1 | `5 Springbok Avenue` | `Address.address_line1` | |
| Address Line 2 | `Clayville East` | `Address.address_line2` | |
| City | `Olifantsfontein - EC` | `Address.city` | quality varies, see below |
| State | `EC` | `Address.state` | |
| Postal Code | `1666` | `Address.pincode` | |
| Country | `ZA` | `Address.country` | ISO-2 → full name |
| Email | `no@email.co.za` | `Address.email_id` | after placeholder filter |
| Phone 1 | `0792530729` | `Address.phone` | normalised |
| Salesperson ID | `003` | → ownership mapping | see Prerequisite 2 |
| Sales Person | `Simon Mofokeng` | → ownership mapping | supplies code→name |
| Created On | `20/10/2025` | provenance only | |

`CRM Organization` itself has no email or phone field (its fields are name,
website, logo, employees, revenue, industry, territory, currency, address,
exchange rate, description and socials). Both land on the linked `Address`
instead, which carries `email_id` and `phone`, joined to the organization
through the `links` Dynamic Link child table.

**Dropped — ERP-only, no CRM meaning:** `Selected`, `Customer Class`,
`Class Description`, `Terms`, `Statement Cycle ID`, `Credit Limit`,
`Credit Verification`, `Tax Registration ID`, `Bill-to Partner`, `Default`,
`Created By`, `Price Class`, `AR Sub.`, `Sales Sub.`, `Parent Account`,
`Tax Zone`, `Billing Cycle`, `Require Customer Signature on Mobile App`.

Two of those deserve a note. **`Customer Class` is payment terms, not
industry** — the sample is `COD` / "COD Customers", so it must not be mapped to
`CRM Industry` despite the superficial fit. **`Parent Account`** implies a
customer hierarchy that `CRM Organization` has no field to hold.

**Address quality is imperfect and that is expected.** The sample has
`City = Olifantsfontein - EC` against `State = EC`, but Olifantsfontein is in
Gauteng. Import as given; do not attempt correction.

### File 2 — Sales Orders → `CRM Deal`

The pipeline, and the file with the one real scoping decision.

| Column | Sample | Target | Note |
|---|---|---|---|
| Order Nbr. | `QT103012` | `acumatica_sales_quote` | **idempotency key** |
| Customer | `C-PRO004` | `acumatica_customer` | |
| Customer Name | `Proserve (Pty) Ltd` | `organization` | Link; Customers import first |
| Order Total | `20,359.60 ` | `deal_value` | |
| Currency | `ZAR` | `currency` | |
| Default Salesperson | `018` | `deal_owner` | Link → User, via mapping |
| Order Type + Status + Quote Outcome | `QT`, `Pending Approval`, *(empty)* | `status` | Link → CRM Deal Status |
| Sched. Shipment | `02/09/2026` | `expected_closure_date` | see below |
| Date / Created On | `02/09/2026` | provenance | |

`Order Type = QT` confirms quotes are in this file. `Quote Outcome` is **empty
on the open quote** and stamped only when a quote closes, which gives a clean
filter for open pipeline without interpreting status codes.

Target statuses are the seven from `crm/install.py:144` — Qualification,
Demo/Making, Proposal/Quotation, Negotiation, Ready to Close, Won, Lost. The
exact mapping cannot be finalised until the distinct values of `Order Type`,
`Status` and `Quote Outcome` are known from the full file.

**`Sched. Shipment` → `expected_closure_date` is a semantic stretch** and is
called out rather than hidden: a scheduled shipment date is not a forecast
close date. It is the closest available column. If the resulting forecast looks
wrong to MBP's manager, this mapping is the first thing to revisit.

**No home:** `Est. Margin (%)` (`33.82`) and `Ordered Qty.` (`30.00`) have no
deal-level field. `Created By` (`ReneO@mbpeng.co.za`) is a real staff email and
is useful for the ownership mapping, but is not the salesperson.

### File 3 — Invoices → derived revenue only

No CRM doctype models an invoice. Sum `Amount` per `Customer` over the trailing
twelve months and write it to `CRM Organization.annual_revenue`, which is a
real field. Honest, computed from real rows, and feeds nothing that forecasts.

`Customer Order Nbr.` is the **customer's own** PO reference (`11520`), not an
Acumatica order number like `QT103012`, so invoices cannot be joined back to
sales orders. No order-level revenue linking is available.

### File 4 — Purchase Orders → not imported

`Vendor Name: Quality Tube Services CC`, `Production Nbr: PR200964-000`,
`Order Total: 0.00`, `Project: X`. Vendor-side procurement. Core to MBP's
business, but a CRM has nothing to map it onto. Excluded entirely.

## Gaps to raise with MBP

**There are no people in any file.** Not one first or last name. Vectora's
proposition — suggestions, "needs attention", propose-my-week, call and email
activity — keys on contacts. Organizations carrying order totals with no humans
attached gives reps a pipeline they cannot act on, and would judge the product
on its weakest showing.

Acumatica has a Contacts entity and `upsert_contact` already handles exactly
its shape (`FirstName`, `LastName`, `Email`, `Phone1`, `BusinessAccount`). **A
Contacts export is the highest-value thing to request**, and it needs no new
mapping work.

**The salesperson code → email mapping is missing.** `Default Salesperson` is a
code (`018`); the Customers file supplies code→name (`003 → Simon Mofokeng`)
but never an email. Ownership drives every scoped metric — `scope_deals`,
`visible_reps`, quota attainment, who sees which suggestions — so this must
come from MBP before the import runs. Codes appearing only in Sales Orders and
never in Customers will not resolve from the files alone.

**Branch codes may be territory data.** `IN-JHB…` and `PO-JHB…` encode a
branch, and MBP has Boksburg, Rustenburg and KZN offices. Worth asking whether
they want the pipeline segmented by `territory`.

## Prerequisites

1. **The Acumatica custom fields do not exist on production.** Verified
   2026-09-03: `Custom Field` returns `[]` for both `CRM Organization` and
   `CRM Deal`. They are created by `ensure_custom_fields()`
   (`crm/integrations/acumatica/install.py`), reached by saving CRM Acumatica
   Settings with the integration enabled, or by calling it directly. Without
   them there is no `acumatica_id` and no idempotency key.
2. **Salesperson code → CRM user mapping**, from MBP.
3. **Those users exist in Vectora** before the import — `deal_owner` is a Link
   to `User` and a missing target fails the row.
4. **`clear_demo_data()` has run.** Production currently holds 47
   organizations, 106 deals and 13 contacts, all seeded.
5. **A manual backup**, immediately before. See *Decisions already taken*.

## Idempotency

The import must be safely re-runnable, because the first pass will be wrong
about something.

- **Organizations** — `CRM Organization` autonames on
  `field:organization_name`, so the docname *is* the name and re-import
  naturally upserts.
- **Deals** — keyed on `acumatica_sales_quote` = `Order Nbr.`. This field
  exists precisely because "Acumatica's SalesOrder PUT has no key in the body,
  so without this every click would create another order"
  (`crm/integrations/acumatica/install.py:44`). Without it, a re-run duplicates
  every deal.
- **Addresses** — keyed on the owning organization plus `address_type`.

### Note on `NoteID`

None of the four exports carries Acumatica's `NoteID` GUID, so imported rows
cannot be stamped with `acumatica_noteid`. This is not fatal: `_adopt()` falls
back to natural keys, and because the organization docname is the name, a
future live backfill adopts imported organizations by exact name match rather
than creating rivals. The adoption path survives; only GUID-stability is lost.
Exact-match adoption is one more reason Open decision 1 matters.

## Open decisions

**1. Organization name suffixes.** Customer names carry payment terms —
`2HK Trading & Projects (Pty) Ltd - COD`, repeated verbatim in `Bill-to
Partner`. Since the docname is the name, one real company holding both a COD
and a 30-day account becomes **two organizations** with its deals split between
them, which is precisely the fragmentation a CRM exists to remove. Stripping
the suffix risks merging accounts MBP considers separate legal entities.

*Recommendation:* quantify first. Count how many names differ only by suffix
once the full file is in hand, then decide on evidence.

**2. Won orders as closed deals.** `.pi/feats/acumatica/README.md` is
deliberate that historical quotations are not imported as deals, because
fabricated stage history poisons forecasting, health scoring and quota
analytics. That reasoning holds for anything closed *and* invented — but a
genuinely won order carries a real value and a real close date.

*Recommendation:* import open quotes as open deals (required — a trial with an
empty pipeline proves nothing), and won orders as `Won` with their real
`closed_date` and `deal_value`. No stage transitions are fabricated, and the
manager view gets a real actuals series. Lost and cancelled history stays out.

**3. Territory.** Whether to derive `territory` from branch codes. Depends on
MBP's answer.

## Implementation shape

A new module, `crm/integrations/acumatica/spreadsheet.py`, split so the risky
parts are pure and testable:

- **Pure transforms** — `parse_ddmmyyyy`, `parse_amount`, `normalise_phone`,
  `map_country`, `is_placeholder_email`, `strip_account_suffix`,
  `map_deal_status`. No Frappe, no I/O. These carry the whole silent-corruption
  risk and get direct unit tests.
- **Row shapers** — turn a spreadsheet row into the `{"value": x}` encoding the
  existing upserts expect, so `upsert_organization` remains the single code
  path owning identity and adoption. Reusing it is what keeps a later live sync
  coherent with what the import wrote. The same shape works for
  `upsert_contact` unchanged if MBP supplies the Contacts export.
- **A bench command** — reads the `.xlsx`, drives the shapers, commits every 50
  records as `run_backfill` does, and reports per-file counts plus a reject
  list.

Rejected rows are reported, never skipped silently. A row that fails to resolve
its organization, salesperson or status is a finding about the mapping.

## Testing

Following the repo's convention that only pure logic is unit-tested: every
function in the *pure transforms* group gets tests, with the date parser
covering the `02/09/2026` ambiguity explicitly and the amount parser covering
comma-and-trailing-space input. Shapers get tests against the four sample rows
recorded in this document. Run with
`bench --site test_site run-tests --module crm.integrations.acumatica.test_spreadsheet`
on a dedicated `test_site`, never the browsing site.

## Rollout sequence

1. `ensure_custom_fields()`, and confirm the fields exist.
2. Obtain the salesperson mapping; create the CRM users.
3. Manual backup.
4. `clear_demo_data()`.
5. Import Customers → organizations and addresses. Review the reject list.
6. Import Sales Orders → deals. Review the reject list.
7. Derive `annual_revenue` from Invoices.
8. Verify against the pilot checklist at `deploy/README.md:786` — agent tier
   and digests off, scheduler watched on day one.

Steps 5–7 are re-runnable by design; step 4 is not.
