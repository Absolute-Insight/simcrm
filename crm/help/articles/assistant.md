---
title: The Vectora assistant
category: Assistant & customisation
order: 1
---

The assistant is the sparkle icon in the sidebar: a chat panel you can open
anywhere in the app to ask how Vectora works — "how does plan adherence get
counted?", "where do I set targets?", "why did this deal get flagged?".

Its answers are grounded in this help center: the assistant reads the same
articles you can read here, and points you to the relevant ones under each
answer.

## What it can do

- **Answer questions about Vectora** — features, settings, how the numbers
  are computed, where to find things.
- **Summarise a record's email thread** and **draft a reply** — these live on
  the lead and deal pages, not in the chat panel.

## What it deliberately cannot do

- **It never writes.** The assistant cannot create, edit or delete records,
  send email, or change settings. Actions stay behind your own buttons and
  confirm dialogs.
- **It does not read your pipeline data in chat.** The chat assistant answers
  from product knowledge; it is not a query tool over your deals.

## Enabling it

The assistant is **off by default**. An administrator enables it in
**Settings → Assistant** by pointing Vectora at an OpenAI-compatible inference
endpoint — your own server or provider; nothing is sent anywhere Vectora is
not told to send it. **Test connection** verifies the endpoint before reps
ever see the feature. There is a daily call budget so usage stays bounded.

- **Base URL** is an OpenAI-compatible endpoint including the version prefix —
  `http://ollama:11434/v1`, `https://api.example.com/v1`. **API Key** only if
  the server requires one.
- **Test connection** sends one real request and checks the reply's shape; it
  works with the tier still off, and tells a wrong base URL from a model that
  cannot do structured output — those look identical from a record page.
- A model on your own hardware is just a different base URL. The self-hosted
  stack ships an inference container behind an opt-in profile, and a site
  created with it already has the endpoint filled in. From inside the
  application container `127.0.0.1` is that container, not the machine —
  address a local endpoint by its service name or a real host.
- **Timeout** is capped at 59 seconds, summarise and draft at 10 calls a
  minute per user.

When the model tier is off or unreachable, the assistant says so and the rest
of Vectora is unaffected: signals, scoring, planning and analytics are
deterministic and never depend on a model.

## Reading model output

Anything a model writes — a chat answer, a summary, a drafted reply — is a
proposal to check, not a fact. Summaries and drafts are generated from email
threads, and a thread contains whatever a third party chose to write, so read
before you trust, and always before you send.
