# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""A golden set for the enrichment model fallback.

The fallback exists because a JavaScript-rendered site leaves the rule-based
extractors with nothing to match. What it produces goes onto a Lead, Deal or
Organization and is read as though somebody researched it, so "does it fill more
fields" is the wrong question to optimise. A fallback that answers every prompt
fills every field and quietly fills some of them with fiction.

So the set is scored as a confusion matrix, not a hit rate, and half of it is
**abstention cases**: pages where the correct answer is to leave the field empty.
A page with no company description must produce no description. Those cases are
what stops a model being credited for confidence.

The five outcomes, and why they are not collapsed into a score:

======================  ======================================================
``correct``             expected a value, got that value
``missed``              expected a value, got nothing -- the *safe* failure;
                        the field stays as blank as the rules left it
``wrong``               expected a value, got a different one -- harmful
``hallucinated``        expected nothing, got something -- the worst outcome,
                        and the one a hit rate hides
``abstained``           expected nothing, got nothing -- correct, and the
                        outcome a guessing model never reaches
======================  ======================================================

``missed`` is cheap and ``hallucinated`` is expensive, so they must never be
averaged together. A model that misses half the fields is a weak fallback; a model
that hallucinates a tenth of them is a liability, and the second is not visible in
any single number that includes the first.

Running it needs a real endpoint, so it is a ``bench execute`` rather than a CI
job::

    bench --site <site> execute crm.domain_enrichment.evals.runner.run_and_print

With no endpoint configured the report says so and reports nothing else -- the
same rule the injection evals follow. A zero that means "did not run" reads
exactly like a zero that means "nothing went wrong".
"""
