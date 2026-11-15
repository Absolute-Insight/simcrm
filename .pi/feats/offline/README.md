# Field mode (offline)

> Reps drive to sites with no reception. Field mode is the part of Vectora
> that still opens there: their week, their customers, their tasks, read from
> a copy on the phone. It is deliberately **not** the whole CRM offline.

## What the user sees

- **Field mode** (`/crm/field`, in the nav as "Field mode"): three tabs — *My
  week*, *Customers*, *Tasks* — with its own header and tab bar. The header
  pill shows when the copy was last saved and syncs on tap; offline it reads
  "Offline" and a band says what time the copy is from.
- **Offline, every other page lands here.** The router sends any route that
  needs the server to `Field` while the server cannot be reached.
- **A cold start with no network works**, including after the phone has
  closed the app, once the device has loaded Vectora online a single time.
  A device that never has shows "open it once with a connection".
- **Capture works offline.** *Log activity* (on My week and on a customer),
  *Log outcome* / *Cancel* on a planned item, *Add note* on a customer or one
  of its open deals, *New task*, *Mark as done* on a task. Each is saved on
  the device at once and shows where it belongs immediately, marked "Waiting
  to send"; it is sent when there is a connection. A header pill counts what
  is waiting, and turns red for anything the server refused.
- **Plan** (on My week, for the day selected, today or later): adds one
  planned activity to the week. Offline planning only ever *adds* — see
  `_replay_plan_item`.
- **Sheets** (a fourth tab, only where the company has loaded reference
  sheets): *Keep on this device* downloads a sheet's page images; a kept
  sheet opens with no connection, page under page, with zoom.
- On an iPhone or iPad in a browser tab, a dismissible band says to add the
  app to the Home Screen (`FieldInstallHint.vue`).
- **To send** (`/crm/field/outbox`): what is waiting and what was refused,
  with the server's reason, and *Send again* / *Discard* for each.
- Everything else — dashboard, reports, assistant, e-mail, WhatsApp, deal
  editing, team week, settings — is online only, by decision.

## The three pieces

### 1. The shell (`frontend/offlineShell.js`, `frontend/public/field-sw.js`)

`/crm` is a Jinja template: Frappe inlines the session's boot and CSRF token.
That is why `index.html` is never precached (it took production down once —
see the VitePWA comment in `vite.config.js`), and why the app could not open
offline at all.

`shell.html` is the built page with the Jinja boot block replaced by a loader.
It has no template syntax and nothing from any session, so it is precached.
`field-sw.js` (imported into the generated worker) answers a navigation under
`/crm` **network-first**, falling back to the shell only when the fetch fails
or takes longer than 6 s. `navigateFallback` stays off — it is cache-first.

The loader (`loadOfflineBoot` in `src/offline/bootSnapshot.js`) restores the
boot the last online page load saved to localStorage, **minus `csrf_token`**,
which is never kept at rest. `BOOT_KEYS` mirrors `get_boot()`; a unit test
reads `crm/www/crm.py` and fails when they drift.

**Who the shell is for.** `user_id` is a session cookie, and a phone drops it
when it closes the app. So the server also sets a persistent cookie,
`crm_field_user`, on every `/crm` render and on **every new session**
(`crm.api.auth.name_field_user` on `on_session_creation`, 14 days — that hook is what stops it
naming the last rep after someone else signs in and goes to the desk) and
deletes it in an `on_logout` hook
(`crm.api.auth.forget_field_user`) — which runs for a logout from the desk
too, where none of the app's code does. The shell takes `user_id` when there
is one (`Guest` is honoured as logged out); otherwise `crm_field_user`,
*provided* it matches the offline owner `utils/offlineCache.js` last claimed
this device's stores for. Neither cookie authenticates anything: they decide
whose saved copy to show until the server can be asked, and the first
handshake settles it — Frappe's own refusal (a JSON body naming the
exception; a bare 403 from a proxy is treated as unreachable), or a session
that belongs to someone else, empties the stores and reloads (`handOver` in
`connectivity.js`). The loader
restores only `BOOT_KEYS`, never arbitrary keys from storage.

A shell that cannot establish a user mounts nothing and shows "open it once
with a connection"; the router guard does not send it to `/login`, which
offline is the browser's error page.

### 2. Connectivity (`src/offline/connectivity.js`)

`navigator.onLine` is not trusted to say "online" (one bar at a mine gate says
yes and every request hangs); it *is* trusted to say "offline". **Only a
probe changes the answer**: a request that dies starts one, and the app goes
offline if that fails too. One dropped fetch on a laptop waking from sleep
must not bounce someone into field mode.

The probe is `GET crm.api.offline.handshake`: it proves the server is there,
hands a shell its CSRF token, carries the server clock (`skewMs`), and names
the session's user. `throughGate()` wraps **both** ways a request leaves the
app — the resource fetcher (`main.js`) and `call()`
(`lib/frappe-ui-compat/call.js`) — so offline a request fails at once as
`offline` instead of hanging, and a shell never POSTs without a token. After
a failed probe requests fail fast for a few seconds rather than each probing.
A 401/403 is the server answering: it surfaces as a permission error, not as
offline, and is not retried.

The router asks through `reachableForNavigation()`, which waits up to 2.5 s
for a probe: a slow line that answers keeps the page that was asked for; a
dead one lands on Field, with the intended route kept for "Open the full app".

### 3. The pack (`crm/api/offline.py`, `src/offline/pack.js`)

`get_pack()` is the snapshot: three weeks of the caller's plan, the customers
they may see with address and open deals, the contacts *at those customers*
(not every contact the rep can read — a phone has no use for the rest, and
what is not on it cannot be lost with it), 90 days of their own
visit history and notes, their open tasks. **Every list is `frappe.get_list`**,
so `crm/permissions` scopes the pack exactly as it scopes the app; the pack
is not a second access path. Rich text is stripped to plain text and clipped
server-side — the phone never renders stored markup.

It is a full snapshot, not a diff: a cursor would have to get deletions and
reassigned customers right, and getting that wrong shows a rep a customer
they no longer have. `known_hash` skips the download when nothing changed,
and `known_sections` — the hash of each list, as the last answer gave them —
skips the lists that did not: one note costs the notes, not every customer
and contact again. A list is left out (`kept`) only when its hash equals the
one the phone sent, and `packFrom` (`pack.js`) puts it back from the pack
those hashes described, asking for everything if it cannot. The rows are
still read on the server to know what changed: this saves the line, not the
queries.

On the device it lives in its own IndexedDB database (`offline/db.js`) and is
read by the Field screens through `offline/useField.js` — online and offline
alike, so the offline path is the everyday path. It syncs on start, on
reconnect, when the tab comes back, and every 10 minutes; automatically only
on a phone-width layout or a device that has opened field mode.

### 4. The outbox (`src/offline/outbox.js`, `crm.api.offline.replay`)

Every write the Field screens make goes through the outbox, **online too** —
stored, then sent — so the path that runs at a mine is the one that runs
every day. An entry is `{id, action, payload, captured_at}`; the id is made
once on the device and sent with every attempt.

`replay()` applies an entry **exactly once**. It inserts a `CRM Offline
Receipt` named by the id in the same transaction as the work: both are
stored, or the handler threw and neither is. A second copy finds the receipt
(or loses the race for its primary key) and is answered `duplicate`. The
action is one of six in `ACTIONS` — it is not a method dispatcher — and each
handler checks permission as the session user, as the endpoint it stands in
for does. Receipts are purged after `RECEIPT_DAYS` (90), and that is also
the oldest entry `replay` takes: past it the receipt that would have said
"duplicate" may be gone, so an entry with no receipt is refused rather than
risk applying it twice (one whose receipt is still there is still answered
`duplicate`). The device counts the same days (`OUTBOX_MAX_AGE_DAYS`, held to
the Python by a unit test): it sets such an entry aside as refused without
sending it, and *Send again* asks the server.

`captured_at` is the device's clock corrected by the handshake's skew. It is
never accepted in the future (five minutes of tolerance, then clamped).
**It buys one thing**: with *Plan only for today or later* on, an activity
captured offline is accepted up to `OFFLINE_GRACE_HOURS` (72) after the fact,
where the online door refuses yesterday. Anything that took more than 15
minutes to arrive, **or is dated on an earlier day than the one it arrived
on** (a visit captured at 23:52 and delivered at 00:03), is flagged
`captured_offline` on its plan item — logged, completed or cancelled alike
(`_flag_offline`) — server-
owned like `manual_override`, shown in the Planner and the team week — so a
manager can tell the device's word from the server's. The whitelisted
`log_unplanned_visit` cannot pass that flag; only `log_activity`, which is
not whitelisted, takes it.

`captured_at` is the device's word and nothing on the server witnesses it:
any signed-in client can claim an activity was captured up to 72 hours ago
and have it accepted past the day lock, flagged. That is the price of the
exemption, accepted knowingly; closing it needs evidence the server holds
itself (a device id on the handshake, say), which is a product decision.

On the device, a failed send is one of two things (`failureKind`, from
`failureCause`): a **refusal** marks the entry `rejected` with the server's
message and the run moves on; **anything else** — no network, 5xx, 429, a
lapsed session — stops the run with the rest still pending, in order.

- **Only Frappe's own answer is a refusal**: 403/404/409/417 *with* an
  `exc_type`. The same status with no exception named is a captive portal or
  a proxy (`between`): the run stops, nothing is refused, and a probe finds
  out whether the server is there — the bare-403 rule of the handshake.
- **A `CSRFTokenError`** means the session was re-created under the open page.
  The outbox asks for the session's token (`renewToken`, the one case where a
  rendered page's token is replaced) and sends the same entry again, once a
  run.
- **A page belongs to the person it was loaded for** (`pageUser`, read once in
  `connectivity.js`). The cookie jar is shared between tabs, so the live
  cookie can come to name someone else while the page still shows the first
  rep's customers. Entries are stamped with `pageUser`, never the live
  cookie; a token is never taken from a handshake that names anyone else
  (`connectivity.otherUser`); and a run sends nothing while the cookie or the
  handshake says the session is another's. The outbox screen says to reload.
- **The entry a run stopped at keeps the reason** (`entry.error`, with
  `attempts`), and the outbox screen shows it while there is a connection;
  the entries behind it say they are waiting for it. Everything automatic —
  the minute timer, the tab or the line coming back — waits out a backoff
  while runs keep stopping (`BACKOFF_MS`); only a new entry or *Send again*
  sends at once.
- **Order holds, with one exception.** A status cannot tell a server that is
  down for everyone from one that fails on this entry alone, so the outbox
  asks: after a failure that is not a verdict it probes. No answer is an
  outage — the app goes offline and nothing is held against the entry. An
  answer, `STALL_LIMIT` times running for the same entry, means it is the
  entry (or a firewall that minds its text): it is set aside as refused, for
  the rep to send again or discard, as a refusal already lets later entries
  pass. A rate limit is never counted. Nor is a second failure inside the
  window the first one opened (`entry.stall_at`, 1 / 3 / 7 / 15 minutes): a
  rep who logs five things in a minute sets off five runs, and that is one
  failure seen five times. Setting aside therefore takes the whole schedule
  — about 26 minutes at the least — however often a run is started.

  **The limit of that test.** In a partial outage — the handshake answers and
  `replay` fails for everyone — the probe cannot tell, and entries are set
  aside one at a time on that schedule. Nothing is lost: each waits in the
  outbox for *Send again*. **Send again is always safe; typing it in again
  is not.** An entry that was slow (a gateway's 504) may well have been
  applied; sent again under its own id it is answered `duplicate`, while a
  fresh entry with the same words is a second note. The set-aside message
  says so, and never suggests discarding.

A sent
entry stays as `sent`, still laid over the pack (`applyOutbox`), until the
next pack sync brings the server's own version; then it is deleted. Rejected
entries are never shown as done anywhere but the outbox.

### 5. Planning offline, and kept sheets

**Planning adds, never replaces.** The Planner saves a whole week under an
optimistic lock ("nobody changed it since you loaded it"). A phone that was
offline for two days cannot make that promise, and losing the week to a
conflict is the wrong price for adding one visit. `plan_item` re-reads the
week as the server holds it and calls `save_plan` with those rows plus the
new one and the week's own timestamp, so every Planner rule applies (horizon,
day lock, the customer's owner) and nothing already there changes. If the
week changed in the instant between that read and the write, the save is
refused with `TimestampMismatchError`, which the phone treats as *retry*
(`failureKind`), not as a refusal — a re-read inside the same request would
see the same snapshot. Editing or moving planned items
stays online, in the Planner.

**Sheets** (`src/offline/sheets.js`). The pack carries only the list of
sheets and their pages. The images are fetched when a rep keeps a sheet,
through the ordinary file URLs and their ordinary permission check, and
stored as blobs in the *pack's* store — so every clear of the pack takes
them too, and expiry now clears the whole store rather than one key. Only
`/files/<name>` and `/private/files/<name>` are ever fetched, whatever the
pack says, and only an `image/*` response is kept. All pages or none.

## What is on the device, and when it goes

| Store | Holds | Cleared |
|---|---|---|
| localStorage `crm-offline-boot` | boot values, no token | logout from the app, lost session, another user, a refused handshake |
| cookie `crm_field_user` | the signed-in user's id | any logout (server hook); expires after 14 days |
| IndexedDB `vectora-field-pack` | the pack, and the page images of kept sheets | the same, after `PACK_MAX_AGE_DAYS` (14) without a sync, and when `get_pack` answers `NotAFieldUser` (the sales role was taken away). Not on any other `PermissionError`: one from inside the pack is a server fault, and must not empty every phone |
| IndexedDB `vectora-field-outbox` | work the server has not seen | only by a confirmed send or the rep discarding it; never by logout, and another user's entries are neither shown nor sent |

The store clears go through `clearOfflineCache()` / `claimOfflineCache()`.
A logout from the **desk** runs none of that: the data stays on disk until
the next `/crm` load or the 14-day expiry, but the shell will not open for
it, because the cookie is gone. A manager who sees every record carries
every record, up to the caps — that is the app's own rule, not narrowed here.
The expiry is re-checked whenever the tab comes back, and a `syncedAt` ahead
of the clock counts as expired.
Caps and windows (`HISTORY_DAYS`, `PACK_MAX_AGE_DAYS`, row limits) are
constants at the top of `crm/api/offline.py`; `truncated` in the pack names
any list that hit its cap, and every screen showing such a list says so
(`packCut`) instead of "none on record".

The 14 days are enforced by the device, and only can be: a phone with no
connection cannot be told anything. The moment it has one, the pack is
replaced, or dropped on a refusal. The server does not refuse a replay
because the pack it was captured against is old — the outbox is the rep's
work, and each handler checks permission as of now.

## Traps

- **Do not precache `index.html`, and do not turn on `navigateFallback`.**
- **A new boot key** goes in `get_boot()` *and* `BOOT_KEYS`; the test says so.
- **A new route that must work offline** needs `meta.offline`, and must read
  nothing but the pack — the guard lets it through without the users, access
  or views requests.
- **QA needs a secure context and the `Service-Worker-Allowed: /crm` header**,
  which `bench serve` does not send. Put a proxy that adds it in front, on
  `localhost`, and drive it with Playwright's `context.setOffline(true)`.
- **Every record name a handler looks up goes through `_name()`.** The
  payload is JSON; `frappe.db.exists` and `get_value` read a dict as unscoped
  filters, which turns "missing vs not yours" into a probe over other reps'
  rows. For the same reason a handler raises **one** exception for both —
  and asks before the code behind it does: `_readable` for a note or a task,
  `_customer` for a customer logged or planned against, `_own_item` for a
  planned item. Left to `log_activity` and the plan's save, "no such
  customer" and "another rep's" were refused in different words.
- **A new offline action** needs four things: a handler in `ACTIONS`, a case
  in `entryProblem` and `applyOutbox` (`utils/fieldOutbox.js`), and a form in
  `FieldEntryDialog.vue`. Never route one to a whitelisted function that
  takes a client-settable "captured offline" argument.
- **`captured_offline` is server-owned**: it is in `SERVER_ITEM_FIELDS`, and
  `_stage_items` must carry it across a `save_plan` like `manual_override`.
- iOS evicts storage for sites not added to the home screen: iPhone reps must
  install the app. The hint says so; `navigator.storage.persist()` is asked
  for on first use of field mode, and the browser may say no.
- **WebKit** was exercised in Playwright's build with device emulation, not
  on a real iPhone. Real-device QA is still owed before rollout.
