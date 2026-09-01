---
title: Curating the knowledge base
category: AI & automation
order: 5
---

The knowledge base is everything **The Assistant** is allowed to say about
your company's offering. It lives in **Settings → Knowledge**, it is written
by administrators, and an article is the only thing the Assistant will quote —
so the quality of its answers is the quality of what you put here.

## What it does for you

- **One place to write down what the company sells and how to talk about it**
  — products, models, materials and trims, pressure classes and end
  connections, standards and certifications, and which industries use what.
- **Reps get the same answer every time**, in the company's own words,
  instead of each person's recollection of the datasheet.
- **A starting point ships with it.** **Import sample knowledge** loads a
  sample valve knowledge pack — valve types, actuators, flow meters, materials,
  pressure classes, standards and a selection guide by industry — so you can
  see what a good article looks like before you write your own.

## When it runs

An article is read only at the moment a rep asks the Assistant something, and
only if its availability switch is on. Nothing is indexed or trained; editing
an article changes the next answer immediately. Saving or importing an article
runs no model at all.

## What it never does

- **It never reaches a customer on its own.** The knowledge base is read by
  the Assistant and shown to reps; nothing here is published or emailed.
- **It never overrides a rep's judgement.** The Assistant repeats what an
  article says and does not guess beyond it. An article that states a rating
  wrongly will be repeated wrongly, which is why each one should be written
  from the datasheet.
- **It never imports your ERP.** The product-catalogue switch (below) is the
  only automatic source; everything else is written here by hand.

## Writing a good article

- **One topic per article.** "Ball valves" and "Ball valve materials" are two
  articles, not one. The Assistant picks the articles that match the question
  best, and a narrow article matches precisely.
- **Put the words customers use in the tags.** The tags are counted like the
  title when the Assistant chooses what to read, so an article on knife-gate
  valves tagged *slurry, tailings, isolation* is found for the question a rep
  actually types.
- **State a rating with its standard.** "Class 150 to ASME B16.34" or "PN16 to
  BS EN 1092-1" is an answer; "rated for 150" is not. The Assistant will
  repeat the figure as written, so write it the way it should be quoted.
- **Link a product where there is one.** An article linked to a product in
  the catalogue surfaces when that product is named.
- **Write for a rep in a hurry.** Short paragraphs, the selection rule up
  front, the exceptions after.

## The availability switch

Every article has an **available to the assistant** switch, on by default.
Switch it off to keep an article — a draft, a superseded model, a product you
no longer quote — without the Assistant ever quoting it. Off means kept but
silent.

## The sample pack

**Import sample knowledge** loads the sample valve pack once; an article whose
title already exists is skipped, so importing twice does not duplicate. Every
sample article says at the top that it is sample content. It is there to show
the shape of a good knowledge base and to give a demonstration something to
answer with — replace it with the company's own products, ratings and
standards before reps rely on it, and delete what does not apply.

## The product-catalogue switch

In **Settings → Assistant** an administrator can let the Assistant read the
product catalogue. When it is on, each enabled product's name, code,
description and list price in the base currency is available to the Assistant
alongside the articles. It reads products only — never deals, leads or email —
and only what the asking rep is permitted to see.
