# Your first week

## If you are a rep

**Start in Suggestions**, not in the deal list. The panel opens from the sidebar
and holds the ranked list of things worth doing today, each with the reason it
appeared. Work down it. Accepting a suggestion creates the task, call or reply
it describes; dismissing one asks why, and that answer is used.

**Then set your week in the Planner.** *Propose my week* drafts one from your
highest-scoring open suggestions — up to ten of them, spread across the working
days. Nothing is saved until you save it, so edit it first. Through the week the
plan resolves itself against what you actually logged.

**Check the Dashboard on a Monday.** It is the honest version of how you are
doing, including the gap to your target if one is set.

## If you are an administrator

Roughly in this order:

1. **Users and roles** — Settings → Users, and Invite User for the rest.
2. **Email** — Settings → Email → Accounts. Without an account connected, no
   thread is visible to the CRM and several signals have nothing to read.
3. **Statuses and stages** — the deal statuses carry a probability, and that
   probability is what forecasting and the *close date at risk* signal both
   read. Set them to what your pipeline actually converts at.
4. **Sales targets** — Settings → Sales Targets, if you want attainment to mean
   anything.
5. **Sales hierarchy** — Settings → Sales Hierarchy, so a manager's dashboard
   rolls up the right people.
6. **SLA policies** — Settings → SLA Policies, if you want the first-response
   clock to exist.
7. **Assignment rules** — Settings → Assignment Rules, so new records land on
   somebody.
8. **The assistant** — optional, and off by default. See
   [The assistant](/crm/help/assistant).

## What happens on its own

Once an hour: the signal engine runs and deal health is rescored. Once a day:
plans are matched against actuals, old suggestions are purged and any due
digests are sent. Once a week: a forecast snapshot is taken.

All of that lives in the scheduler. On a self-hosted stack, if the scheduler is
not running, the proactive half of the product is silent — and that silence
looks exactly like nothing being wrong.
