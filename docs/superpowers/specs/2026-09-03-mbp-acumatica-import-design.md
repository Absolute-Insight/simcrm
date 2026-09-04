# MBP Acumatica spreadsheet import — design

**Date:** 2026-09-03, revised 2026-09-04 against the actual files
**Status:** drafted in session, pending review
**Context:** the 2026-09-02 demo to MBP Engineering went well and they supplied
four Acumatica Excel exports for a trial. This covers getting that data onto the
production site and running the pilot against it.

The first draft was written from column lists and one sample row per file. The
files arrived on 2026-09-04 at `/home/evo/dev/mbp/acumatica_data/` and every
section below has been re-derived from them. Four claims in that draft were
wrong; they are corrected in place and flagged where the correction changes a
decision.

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

## Data profile

Taken 2026-09-02, exported by "MBP". Every file has a `Data` sheet and a
three-row `Parameters` sheet. Counts exclude the header row.

| File | Rows | Span | Notes |
|---|---|---|---|
| Customers | 1,098 | created 2025-10-20 → 2026-09-02 | 1,096 distinct customer IDs |
| Sales Orders | 10,153 | 2025-11-29 → 2026-09-02 | QT 7,187 · SO 2,234 · TR 667 · CM 65 |
| Invoices | 2,308 | 2025-12-01 → 2026-09-02 | R88.6m, 336 customers |
| Purchase Orders | 2,651 | 2025-11-17 → 2026-09-02 | 408 vendors |

**The history is nine months deep, not years.** Acumatica went live around
2025-11-29: 88 sales orders dated 2025-11-29 to 2025-12-01 carry bare numeric
order numbers (`134440`, `127193`) instead of the `SO-JHB…` pattern used since.
Those are pre-migration orders carried over at cutover. They are valid rows and
import normally; the numbering is only worth knowing so it is not mistaken for
corruption.

Nine months is enough for a credible pipeline and *not* enough for year-over-year
comparison. Any report offering one on this data will show an empty prior year.

## Non-goals

- **Purchase Orders are not imported.** Confirmed against the file: there is no
  customer column, and `Production Nbr.` is filled on only 175 of 2,651 rows.
  The rows cannot be joined to a customer or a deal by any available key. Vectora
  models no vendor, PO or production order. `Project` is the literal string `X`
  on all 2,651 rows — a disabled feature, not data.
- **No invoice records.** Vectora is a CRM and has no invoice doctype. Invoice
  rows are used only to derive a per-organization revenue figure.
- **No live Acumatica API sync.** The existing integration stays off. This is a
  one-way file import that leaves the door open to enabling sync later.
- **No contact/person import** — there is no source data for it. This is the
  single biggest gap and the top ask of MBP; see *Gaps*.

## Global transform rules

### Read the `.xlsx` directly — never via CSV

**Correction to the first draft.** That draft made date handling the headline
risk, on the strength of `20/10/2025` appearing in a pasted sample: dates are
`DD/MM/YYYY`, parse them with an explicit format, `02/09/2026` is silently
ambiguous. That reasoning was sound for the *rendered* value and wrong for the
file. openpyxl returns native `datetime` objects for every date column in all
four files — 10,153 of 10,153 in Sales Orders, 2,308 of 2,308 in Invoices. There
is no string to misparse.

The rule this replaces it with is narrower and firmer: **the importer reads the
workbook, not an export of it.** Round-tripping through CSV re-introduces
`DD/MM/YYYY` ambiguity that the source does not have, and it is a silent
failure — a MM/DD misread only errors on days above 12, so it corrupts part of
the file and passes the rest. The importer takes an `.xlsx` path. It does not
accept CSV.

This still compounds with a known production hazard: `deploy/README.md:714`
records 153,661 future-dated `creation`/`modified` values from the last
deployment sorting real records below every seeded row in list views ordered by
last-modified. Imported rows must not extend that; `creation` is left to Frappe.

### Money is a native number, but not a `Decimal`

The second correction: amounts are not strings, so there are no thousands
separators or trailing whitespace to strip. openpyxl returns floats. Convert
through `Decimal(str(x))` rather than `Decimal(x)` so the binary float is not
carried into the decimal, and let Frappe's currency field do the rounding.

### Currency is *not* uniform

The third correction — the first draft asserted "Currency is `ZAR` throughout",
which the sample rows supported and the files do not:

| File | Currencies |
|---|---|
| Sales Orders | ZAR 10,123 · **USD 30** |
| Invoices | ZAR 2,301 · **USD 7** |
| Customers | ZAR 1,094 · **USD 4** |
| Purchase Orders | ZAR 2,517 · USD 124 · EUR 10 |

`ensure_zar_currency()` (`crm/install.py:40`) guarantees the ZAR record exists;
USD is a Frappe default. The importer must set `currency` per row and must not
sum mixed currencies. Thirty USD deals is few enough to be invisible in testing
and quite enough to make a total wrong — a R-denominated pipeline figure that
silently adds USD order totals as if they were rands *understates* each of those
rows by the rate, around 18×, because a USD deal is worth ~18 times the rand
figure it is filed under.

### Country is ISO-2

Twelve countries: ZA 997, MZ 24, TZ 15, ZM 13, AE 6, BW 6, ZW 5, NA 4, GH 4,
MU 4, GN 3, CD 2. Frappe's `Country` doctype is keyed on the full name, so every
one needs mapping. `NA` is Namibia and must not be read as a null.

### Email needs filtering, not just placeholder-stripping

1,094 of 1,098 customers carry an email; only 607 are distinct.

- **361 are the literal placeholder `no@email.co.za`** — a third of the file.
- Many are **semicolon-joined distribution lists**, e.g.
  `michell.mabale@implats.co.za; statements@implats.co.za` and one with six
  addresses. These are accounts-receivable and statement mailboxes.

Both must be filtered, and the second matters more than the first. A placeholder
address is merely useless; importing `statements@implats.co.za` as a contactable
address on a customer record puts a live IONOS outgoing account one click away
from sending sales follow-up to a client's AP department. **Import only
single-address values that are not placeholders**, and drop the rest rather than
splitting them — a statement mailbox is not a sales contact under any split.

### Phone numbers are local SA format

`0792530729`, no `+27`. Filled on 875 of 1,098. Normalise on the way in.

## File 1 — Customers → `CRM Organization` + `Address`

The cleanest fit of the four. Fill rates measured across all 1,098 rows.

| Column | Target | Fill |
|---|---|---|
| Customer ID (`C-2HK001`) | `CRM Organization.acumatica_id` (custom, read-only) | 100% |
| Customer Name | `organization_name` — **the docname** | 100% |
| Currency ID | `currency` (Link → Currency) | 100% |
| Customer Status | *filter* | 100% |
| Address Line 1 / 2 | `Address.address_line1` / `2` | 95% |
| City | `Address.city` | 91% |
| State | `Address.state` | 81% |
| Postal Code | `Address.pincode` | 86% |
| Country | `Address.country` (ISO-2 → full name) | 100% |
| Email | `Address.email_id`, after filtering | 100% raw, ~57% usable |
| Phone 1 | `Address.phone`, normalised | 80% |
| Salesperson ID + Sales Person | → ownership mapping | **43%** |
| Created On | provenance only | 100% |

`CRM Organization` has no email or phone field of its own (its fields are name,
website, logo, employees, revenue, industry, territory, currency, address,
exchange rate, description and socials). Both land on the linked `Address`,
which carries `email_id` and `phone`, joined through the `links` Dynamic Link
child table.

**`Customer Status`**: Active 882, On Hold 209, Inactive 5, Credit Hold 2. Import
Active and On Hold — "On Hold" is a credit state, not a dead account, and 209 of
them is a fifth of the book. Exclude only the 5 Inactive.

**`Customer Class` is payment terms, not industry.** Now confirmed across the
file: COD 735, 30DAYS 315, 60DAYS 37, LEGAL 4, DEPOSITS 3, SETTLEMENT 3,
120DAYS 1. It must not be mapped to `CRM Industry` despite the superficial fit.
There is **no industry data in any of the four files**; `industry` stays empty.

**Two duplicate customer IDs.** `C-A00070` appears twice, byte-identical — take
either. `C-MET006` appears twice differing only in `Salesperson ID` / `Default`;
take the row with `Default = True`. Deduplicate on `Customer ID` before writing,
or the second row silently overwrites the first.

**Nine customer names are shared by more than one record**, 20 records in total
(e.g. `Sibanye Rustenburg Platinum Mines (Pty) Ltd` across four customer IDs).
Because the docname *is* the name, these collide and Frappe appends `-1`, `-2`.
See *Decision 1*.

**Address quality is imperfect and that is expected.** `City = Olifantsfontein - EC`
against `State = EC`, but Olifantsfontein is in Gauteng. Import as given; do not
attempt correction.

**Dropped — ERP-only, no CRM meaning:** `Selected`, `Customer Class`,
`Class Description`, `Terms`, `Statement Cycle ID`, `Credit Limit`,
`Credit Verification`, `Tax Registration ID`, `Bill-to Partner`, `Default`,
`Created By`, `Price Class`, `AR Sub.`, `Sales Sub.`, `Parent Account`,
`Tax Zone`, `Billing Cycle`, `Require Customer Signature on Mobile App`.

`Parent Account` (filled on 112 rows) implies a customer hierarchy that
`CRM Organization` has no field to hold. It is the only dropped column with
genuine CRM value, and it is the natural fix for the duplicate-name problem if
MBP ever wants group roll-ups.

## File 2 — Sales Orders → `CRM Deal`

The pipeline, and the file that carries every real decision.

### What each row type is

| Type | Rows | Disposition |
|---|---|---|
| `QT` quote | 7,187 | **The deals.** See the status table below. |
| `SO` order | 2,234 | Excluded — the fulfilment record of an already-won quote. Importing both double-counts. |
| `TR` transfer | 667 | Excluded — internal branch transfers. |
| `CM` credit memo | 65 | Excluded — a reversal, not an opportunity. |

The `TR` exclusion is proven rather than assumed: exactly 4 customer references
in the whole file are absent from the Customers export — `JHB`, `KXE`, `KZN`,
`RTB` — and they account for exactly 667 rows, the entire `TR` population. They
are branch codes in a customer column. Referential integrity is otherwise
perfect: all 773 real customers referenced by sales orders, and all 336
referenced by invoices, are present in the Customers file.

### Quote status → deal status

| Status | Quote Outcome | Rows | → |
|---|---|---|---|
| Open | *(empty)* | 5,041 | open deal, subject to *Decision 2* |
| Completed | *(empty)* | 1,711 | **Won** |
| Open | Lost | 352 | **Lost** |
| On Hold | *(empty)* | 34 | open deal |
| Canceled | *(empty)* | 21 | Lost |
| Rejected | *(empty)* | 10 | Lost |
| Open | Open | 9 | open deal |
| Pending Approval | *(empty)* | 7 | open deal |
| Completed | Lost | 2 | Lost |

**`Quote Outcome` only ever records failure.** Its distinct values across 10,153
rows are `Lost` (357), `Open` (9), and empty (9,787). There is no `Won`. This
contradicts the first draft's assumption that `Quote Outcome` "is stamped when a
quote closes, which gives a clean filter" — it is stamped on 3.5% of quotes.

Won therefore has to be read from `Status = Completed`, on the reading that
Acumatica marks a quote Completed when it converts to an order. The evidence
supports that without proving it: 96% of Completed quotes are followed within 45
days by a sales order for the same customer, against a 59% base rate for quotes
still Open. The lift is real; the base rate is high because MBP's larger
customers order continuously, so the test cannot separate "this quote
converted" from "this customer buys constantly". **Worth one confirming question
to MBP** — it decides 1,711 deals — but it is the only defensible reading of the
data and the plan proceeds on it.

Target statuses are the seven from `crm/install.py:144` — Qualification,
Demo/Making, Proposal/Quotation, Negotiation, Ready to Close, Won, Lost. Every
imported open quote lands in **Proposal/Quotation** (probability 50). This is
honest: a quote has been issued and nothing in the file says more than that.
Spreading them across Qualification/Negotiation/Ready-to-Close would be invented
stage history, which is the exact failure `.pi/feats/acumatica/README.md` warns
about.

### Field mapping

| Column | Target | Note |
|---|---|---|
| Order Nbr. (`QT103012`) | `acumatica_sales_quote` | **idempotency key** |
| Customer (`C-PRO004`) | `acumatica_customer` | |
| Customer Name | `organization` | Link; Customers import first |
| Order Total | `deal_value` | 52 quotes are R0 |
| Currency | `currency` | ZAR/USD, see above |
| Default Salesperson (`018`) | `deal_owner` | Link → User, via mapping — **see Gaps** |
| Status + Quote Outcome | `status` | table above |
| Date | `creation`-adjacent provenance, and the basis for the close date | |

**`Sched. Shipment` must not be mapped to `expected_closure_date`.** The first
draft called this "a semantic stretch" and kept it. The file says it is worse
than that: it equals `Date` on 98.4% of quotes, and **zero of the 5,041 open
quotes has a shipment date in the future**. Using it would give every open deal a
close date in the past — every deal instantly overdue, and a forecast with
nothing in any future period. That would break the demo's headline feature on
first sight.

`expected_closure_date` has no source column. Options, in preference order:

1. **`Date` + a fixed quote-validity offset supplied by MBP** (their standard
   quote validity, typically 30 days). One assumption, uniformly applied,
   documented on screen, and corrected by reps as they work the pipeline — which
   is exactly the trial activity we want. Recommended.
2. Leave it empty — forecasting shows nothing, and the trial cannot exercise the
   feature MBP was sold on.
3. Derive per-deal from historical quote→order lag. Rejected: it manufactures
   per-deal precision the data does not contain.

**No home:** `Est. Margin (%)` and `Ordered Qty.` have no deal-level field.
Margin is also unusable — it ranges to −341,926,291%, so some rows carry a
divide-by-near-zero artefact. `Created By` is a real staff email (29 distinct,
all `@mbpeng.co.za` bar `admin` and `BCLOUD`) but it is the person who captured
the quote, not the salesperson — see *Gaps*.

## File 3 — Invoices → derived revenue only

2,223 invoices and 85 credit memos; Closed 1,938, Open 350, Canceled 20;
R88,629,848 across 336 customers. No negative amounts, 13 zeroes.

Sum `Amount` per `Customer` and write it to `CRM Organization.annual_revenue`,
which is a real field. Two caveats to apply: the window is nine months, not
twelve, so either annualise and say so or label it as period revenue; and the 85
credit memos are positive amounts that should be **subtracted**, not added.

**`Customer Order Nbr.` is the customer's own PO reference**, now proven rather
than inferred: of 2,306 populated values, **5** match any MBP order number, and
those five are coincidence — the rest are the customers' own formats (`11520`,
`5502486617`, `POMJ0002716`, `WALKIN`). Invoices join to a *customer*, never to
an order or a deal. There is no order-level revenue linking available in this
export.

## File 4 — Purchase Orders → not imported

See *Non-goals*. Retained here only so the exclusion is not revisited: 2,651
rows, all `Type = Normal`, 408 vendors, no customer column, `Project = X`
throughout. The one CRM-adjacent signal is supply lead time (`Promised On` vs
`Date`), which no current Vectora surface consumes.

## Decisions resolved by the data

**1. Organization name suffixes — strip `- COD` only.**

666 of 1,098 names carry a ` - XXX` suffix, and **591 of those are ` - COD`** —
payment terms leaking into the customer name. The remainder are almost entirely
*site* identifiers (`- Shaft 10`, `- Driefontein Division`, `- Springs`,
`- Mozambique`), which distinguish genuinely separate delivery points of one
mining group and must be kept.

Stripping ` - COD` (case-insensitively; one record uses ` - Cod`) is measurably
safe: distinct names are **1,087 before and 1,087 after**. It merges nothing and
splits nothing, because no COD-suffixed customer shares a base name with a
non-COD one. It is a pure cosmetic improvement, and it removes the risk the
first draft worried about — one company appearing twice because it holds both a
COD and a 30-day account — without touching real site distinctions.

The nine genuinely duplicated names remain and are a separate matter. They are
one company with several Acumatica accounts (four `Sibanye Rustenburg Platinum
Mines`, two `Western Platinum`). Frappe will name them `…`, `…-1`, `…-2`.
Recommendation: **let it, and disambiguate by appending the customer ID** —
`Sibanye Rustenburg Platinum Mines (Pty) Ltd (C-SIB001F)` — which is meaningful
to an MBP rep, where `-1` is not. 20 records affected.

**2. Which open quotes become open deals — a recency window, recommended 90 days.**

This is the decision the first draft could not see. 5,041 open quotes carry
**R778,745,145**, against R118m of actual sales orders in the same nine months.
70% of them are more than 60 days old:

| Age | Deals | Value |
|---|---|---|
| ≤30d | 862 | R108,467,707 |
| ≤60d | 1,502 | R202,140,108 |
| **≤90d** | **2,068** | **R312,055,804** |
| ≤120d | 2,729 | R463,347,782 |
| ≤180d | 3,743 | R583,596,050 |
| all | 5,041 | R778,745,145 |

MBP does not close out quotes in Acumatica — that is why `Quote Outcome` is
empty on 96.5% of rows. A quote from March that never became an order is dead,
but the ERP still calls it Open. Importing all 5,041 gives the trial a R779m
"pipeline" that is mostly fiction, floods health scoring and the suggestion
inbox, and — per `AGENTS.md` — the per-rep suggestion ceiling counts every open
row on the site, so 5,041 open deals will distort the ceiling itself.

**Recommend ≤90 days: 2,068 deals, R312m.** Large enough to exercise every
surface, recent enough that a rep recognises the quotes, and the cut is a stated
policy rather than a judgement about individual deals. Make the window a
parameter so it can be re-run at a different setting after MBP looks at it.

**3. Territory — drop it.** The branch codes are real (`SO-JHB`, `SO-RUS`,
`SO-KXE`, `SO-KZN`, matching MBP's Boksburg, Rustenburg and KZN offices), but
they appear only on *sales order* numbers. Quote numbers (`QT103012`) carry no
branch, and quotes are what become deals. Customers carry no branch either.
There is no path from a deal to a territory in this data. Do not populate
`territory`.

**4. Won and lost history — import both, and warn about the win rate.**

The first draft recommended importing won orders as closed deals and leaving
lost history out. The data makes the second half of that wrong, and adds a
caveat to the first.

Importing 1,711 won and 354 lost produces a headline **win rate of 82.9%**. That
number is false, and MBP will know it is false the moment they see it. It is an
artefact of quote hygiene: wins get marked because converting a quote to an
order marks it automatically, while losses require someone to remember. Dropping
lost history makes it worse — a 100% win rate.

Three options were considered. Reclassifying stale open quotes as Lost would fix
the ratio by fabricating outcomes on ~3,000 deals, which is precisely the
poisoning `.pi/feats/acumatica/README.md` forbids. Importing no closed history
avoids the problem and leaves the manager view with no actuals at all.

**Recommendation: import won and lost exactly as recorded, and put the caveat in
front of MBP before they find it.** It is a genuinely strong trial message —
*your ERP cannot tell you your win rate, because 96% of your quotes are never
closed out; from day one of this trial, Vectora can.* Alongside it, the forecast
baseline should be dated from the import forward rather than computed over
imported history.

## Gaps to raise with MBP

**The salesperson code cannot be resolved from these files, and this is now
measured.** `Default Salesperson` is a code; 22 distinct codes appear on sales
orders and the Customers file supplies a name for only **11** of them. The
unresolved eleven include three of the four busiest — `022` (1,301 orders),
`035` (1,059) and `034` (885).

Deriving it from `Created By` does not work. Correlating the two across all
non-transfer rows, the most frequent creator for a given salesperson code
accounts for a median of ~50% of that code's orders, with 15+ distinct creators
per code — `Created By` is the sales-desk person who captured the quote, and
several desk staff capture for the same salesperson. Two codes are clean
(`036` → Mbali 97%, `041` → Khomotso 95%); the rest are not, and a 50%-confident
owner assignment is worse than none.

On the ~4,100 deals the recommended plan would create: **61.6% have a resolvable
owner, 36.2% carry a code with no name anywhere in the data, 2.2% have no
salesperson at all.** Ownership drives every scoped metric — `scope_deals`,
`visible_reps`, quota attainment, who sees which suggestions — so a third of the
pipeline invisible to its owner would undercut the trial badly.

**This is the one blocking ask.** A 22-row list of code → name → email. Nothing
else in the plan is gated on MBP.

**There are no people in any file.** Not one first or last name across 16,210
rows. Vectora's proposition — suggestions, "needs attention", propose-my-week,
call and email activity — keys on contacts. Organizations carrying order totals
with no humans attached give reps a pipeline they cannot act on, and would judge
the product on its weakest showing.

Acumatica has a Contacts entity and `upsert_contact` already handles exactly its
shape (`FirstName`, `LastName`, `Email`, `Phone1`, `BusinessAccount`). **A
Contacts export is the highest-value thing to request** and it needs no new
mapping work. The customer `Email` column is not a substitute — a third of it is
a placeholder and much of the rest is AP distribution lists.

**Two questions, neither blocking:**

- Does `Status = Completed` on a quote mean it converted to an order? Decides
  1,711 won deals.
- What is MBP's standard quote validity period? Supplies the
  `expected_closure_date` offset.

## Prerequisites

1. **The Acumatica custom fields do not exist on production.** Verified
   2026-09-03: `Custom Field` returns `[]` for both `CRM Organization` and
   `CRM Deal`. They are created by `ensure_custom_fields()`
   (`crm/integrations/acumatica/install.py`), reached by saving CRM Acumatica
   Settings with the integration enabled, or by calling it directly. Without
   them there is no `acumatica_id` and no idempotency key.
2. **Salesperson code → CRM user mapping**, from MBP. Blocking.
3. **Those users exist in Vectora** before the import — `deal_owner` is a Link
   to `User` and a missing target fails the row.
4. **`clear_demo_data()` has run.** Production currently holds 47
   organizations, 106 deals and 13 contacts, all seeded.
5. **A manual backup**, immediately before. See *Decisions already taken*.

## Idempotency

The import must be safely re-runnable, because the first pass will be wrong
about something — and because the open-quote window in *Decision 2* is a
parameter MBP may want changed after seeing it.

- **Organizations** — `CRM Organization` autonames on
  `field:organization_name`, so the docname *is* the name and re-import
  naturally upserts. Deduplicate on `Customer ID` first.
- **Deals** — keyed on `acumatica_sales_quote` = `Order Nbr.`. This field
  exists precisely because "Acumatica's SalesOrder PUT has no key in the body,
  so without this every click would create another order"
  (`crm/integrations/acumatica/install.py:44`). Without it, a re-run duplicates
  every deal.
- **Addresses** — keyed on the owning organization plus `address_type`.

Widening the window later must add deals without disturbing those already
present, including any a rep has edited. Re-running must never resurrect a deal
a rep deleted, so the importer records what it created.

### Note on `NoteID`

None of the four exports carries Acumatica's `NoteID` GUID, so imported rows
cannot be stamped with `acumatica_noteid`. This is not fatal: `_adopt()` falls
back to natural keys, and because the organization docname is the name, a future
live backfill adopts imported organizations by exact name match rather than
creating rivals. The adoption path survives; only GUID-stability is lost.

Exact-match adoption is why *Decision 1* matters beyond cosmetics: if the
importer strips ` - COD` and a later live sync does not, the sync sees 591
unfamiliar names and creates 591 rival organizations. **Whatever normalisation
the importer applies must be applied by the live sync too**, in shared code.

## Implementation shape

A new module, `crm/integrations/acumatica/spreadsheet.py`, split so the risky
parts are pure and testable:

- **Pure transforms** — `parse_amount`, `normalise_phone`, `map_country`,
  `usable_email`, `normalise_account_name`, `map_deal_status`,
  `within_window`. No Frappe, no I/O. These carry the whole silent-corruption
  risk and get direct unit tests. `normalise_account_name` is the function the
  live sync must share.
- **Row shapers** — turn a spreadsheet row into the `{"value": x}` encoding the
  existing upserts expect, so `upsert_organization` remains the single code
  path owning identity and adoption. Reusing it is what keeps a later live sync
  coherent with what the import wrote. The same shape works for
  `upsert_contact` unchanged if MBP supplies the Contacts export.
- **A bench command** — reads the `.xlsx`, drives the shapers, commits every 50
  records as `run_backfill` does (`COMMIT_EVERY = 50`, so a large import does
  not hold one transaction), and reports per-file counts plus a reject list.
  Takes the open-quote window as an argument and supports `--dry-run`.

Rejected rows are reported, never skipped silently. A row that fails to resolve
its organization, salesperson or status is a finding about the mapping. A
dry-run that prints the full reject list before anything is written is the
cheapest defence available given there is no backup regime.

## Testing

Following the repo's convention that only pure logic is unit-tested, every
function in the *pure transforms* group gets tests. The cases that matter, all
drawn from the real files:

- `normalise_account_name` — `- COD`, `- Cod`, and that `- Shaft 10`,
  `- Driefontein Division` and `- Mozambique` survive untouched.
- `usable_email` — rejects `no@email.co.za`, rejects
  `a@x.co.za; statements@y.com`, accepts a single real address.
- `map_country` — `ZA` → South Africa, and `NA` → Namibia rather than null.
- `map_deal_status` — all ten observed `Status` values × three `Quote Outcome`
  values, including `Completed` + `Lost`.
- `parse_amount` — float→Decimal without binary carry; R0 totals.
- Currency — a USD row does not land as ZAR.
- `within_window` — boundary at exactly the cutoff day.

Shapers get tests against sample rows taken from the four files. Run with
`bench --site test_site run-tests --module crm.integrations.acumatica.test_spreadsheet`
on a dedicated `test_site`, never the browsing site.

The files themselves are **not** committed — they are MBP's data. Tests use
fixtures typed from the rows quoted in this document.

## Rollout sequence

1. `ensure_custom_fields()`, and confirm the fields exist.
2. Obtain the salesperson mapping; create the CRM users.
3. Manual backup.
4. `clear_demo_data()`.
5. Import Customers → organizations and addresses. Review the reject list.
6. Import Sales Orders → deals, at the agreed window. Review the reject list.
7. Derive revenue from Invoices, net of credit memos.
8. Verify against the pilot checklist at `deploy/README.md:786` — agent tier
   and digests off, scheduler watched on day one.
9. Walk the result with MBP before reps get logins, with the win-rate caveat
   from *Decision 4* raised first rather than discovered.

Steps 5–7 are re-runnable by design; step 4 is not.
