# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Prompt-injection evals for the agent tier.

The README records the finding these exist to track: **every model tried follows
the injected instruction**, on both the summariser and the draft tier. That is not
a bug awaiting a fix -- it is why this tier has no write path and why a draft is
something a human sends. But it was written down as a prose table produced by hand,
which means it cannot be re-run when the model changes, and a property nobody can
re-measure quietly stops being true.

So the cases are data (:mod:`cases`), the harness is code (:mod:`runner`), and the
result is a report rather than a verdict. There is deliberately no pass/fail gate:
a suite that fails on every model gets switched off within a week. What it produces
is a number per model -- how often the injection lands -- so a model can be chosen
on evidence and a regression is visible.

Running it needs a real endpoint, so it is a ``bench execute`` away rather than a
CI job::

    bench --site <site> execute crm.agent.evals.runner.run_and_print
"""
