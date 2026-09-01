---
title: The Assistant
category: AI & automation
order: 3
---

The Assistant is the sparkle entry in the sidebar: a chat panel you can open
anywhere in the app to ask about your own company's offering — "which valve do
we sell for slurry service?", "what pressure class is that model rated for?",
"which of our products are used in water treatment?". It answers from a
knowledge base your administrator writes and maintains in
**Settings → Knowledge**, and from nothing else.

## What it does for you

- **Answers a rep's questions about products, models, materials, standards
  and certifications, and which industries use what** — in the words your own
  knowledge base uses, so the answer matches what the company actually says.
- **Shows which knowledge articles it drew on**, so you can open the source
  and read the full text before quoting it to a customer.
- **Can know the product catalogue.** If an administrator switches on the
  option to let it read the product catalogue in **Settings → Assistant**,
  product names, codes, descriptions and list prices are available to it as
  well as the articles.
- **Says so when there is nothing to answer from.** If no knowledge has been
  added yet, the panel tells you that an administrator has not added any;
  administrators see a shortcut to **Settings → Knowledge**. If the knowledge
  base does not cover your question, it says that rather than guessing.

## When it runs

Only when you ask. It does not run in the background, and the conversation
lives in your browser tab for the session — nothing is stored.

It is available to sales users once an administrator has enabled the model
(below) and added knowledge. The same switch enables all three conversational
surfaces — the Mentor, the Assistant and the Analyst — together with thread
summaries and reply drafts on records.

## What it never does

- **It never guesses a specification, rating or price.** If the knowledge base
  does not state a figure, it says the knowledge base does not cover it. A
  rating, a class or a price that reaches a customer should still be checked
  against the datasheet or the price list.
- **It never reads deals, leads or email.** It is not a query tool over your
  pipeline and cannot see a customer's thread. Its knowledge is the curated
  knowledge base, plus the product catalogue when that option is on.
- **It never writes.** It cannot create, edit or delete records, send email or
  change settings. Actions stay behind your own buttons and confirm dialogs.
- **It never sends anything to a customer.** An answer is text in front of
  you; what you do with it is yours.

## Enabling the model

The model is **off by default**. An administrator enables it in
**Settings → Assistant** by pointing Vectora at an OpenAI-compatible inference
endpoint — your own server or provider; nothing is sent anywhere Vectora is
not told to send it. One switch enables all three surfaces — the Mentor, the
Assistant and the Analyst — plus thread summaries and reply drafts. **Test
connection** verifies the endpoint before reps ever see any of them. There is
a daily call budget so usage stays bounded.

- **Base URL** is an OpenAI-compatible endpoint including the version prefix —
  `http://ollama:11434/v1`, `https://api.example.com/v1`. **API Key** only if
  the server requires one.
- **Test connection** sends one real request and checks the reply's shape; it
  works with the model still off, and tells a wrong base URL from a model that
  cannot do structured output — those look identical from a record page.
- A model on your own hardware is just a different base URL. The self-hosted
  stack ships an inference container behind an opt-in profile, and a site
  created with it already has the endpoint filled in. From inside the
  application container `127.0.0.1` is that container, not the machine —
  address a local endpoint by its service name or a real host.
- **Timeout** is capped at 59 seconds, and each surface is limited to a fixed
  number of calls a minute per user. The **daily call budget** caps the whole
  site's model calls for the day; once it is spent, every surface reports
  itself unavailable until tomorrow.
- The Analyst has a second switch of its own on the same page, off by default:
  **Allow the analyst to read CRM and ERP data**. See **The Analyst**.

When the model is off or unreachable, each surface says so and the rest of
Vectora is unaffected: signals, scoring, planning and analytics are automatic
rules and never depend on a model.
