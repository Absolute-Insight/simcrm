# The assistant

The assistant is Vectora's optional model tier. It is **off by default**, and
everything else in the product works without it — signals, deal health, the
planner, forecasting, reports, digests and automation rules are ordinary code
and do not call a model.

If you are wondering where the AI is: it is here, and it is probably switched
off.

## What it does when it is on

Two things, both on a record, both on demand rather than on page load:

- **Summarise thread** — a short summary of the email conversation on a deal or
  lead, with the sentiment and the next steps it can see.
- **Draft reply** — a reply you can edit before sending. It is never sent for
  you.

That is the whole surface. There is no chat window and no autonomous agent
acting on your records: this tier has no write tools at all. Everything it can
read, it reads as *you*, through the same permissions you have — it cannot
summarise a thread you could not open yourself.

## Switching it on

**Settings → Automation & Rules → Assistant.**

1. Set **Base URL** to an OpenAI-compatible endpoint, including the version
   prefix — `http://ollama:11434/v1`, `https://api.example.com/v1`.
2. Set **Model** to the model name that endpoint serves.
3. **API Key** only if the server requires one. Left blank, no authorization
   header is sent.
4. Press **Test connection**. It sends one real request and checks the reply
   follows the expected schema. It works with the tier still off, and it is the
   fastest way to tell a wrong base URL from a model that cannot do structured
   output — those look identical from a record page and have different fixes.
5. Then switch **Enabled** on.

## Running a local model

Nothing about the CRM changes between a hosted API and a model on your own
hardware; only the base URL does. Three shapes are supported:

| | Cost | Where your data goes |
|---|---|---|
| **Off** | none | Nowhere. The default. |
| **Hosted API** | per token | Thread contents, including customer email, leave your infrastructure. |
| **Local model** | one machine with a GPU | Nowhere. |

The self-hosted stack ships an inference container behind an opt-in profile,
with a model pre-pulled and warmed. If your administrator brought the stack up
with it, the endpoint is already filled in and there is nothing to configure but
the switch. The deployment README has the details.

One trap worth knowing: from inside the application container, `127.0.0.1` is
that container, not the machine. A local endpoint has to be addressed by its
service name or a real host, which is the single mistake that makes a correctly
installed model look broken.

## Limits, and why they exist

- **Timeout** is capped at 59 seconds. A call can hold a worker for the timeout
  twice over, and beyond about a minute the web proxy has already given up on
  the request — so the rep sees a failure while a worker stays busy anyway.
- **Daily call budget** is a site-wide ceiling on model calls per day. Once
  spent, endpoints report themselves unavailable rather than continuing to bill.
- Summarise and draft are rate-limited to **10 calls a minute per user**, test
  connection to six.

## What to expect of the output

Read it as a draft, not as a fact. Two things follow from that, and both are
worth saying out loud.

A summary is built from email your counterparty wrote. Text in that email can
influence what the summary says — this was tested against three real models and
none of them resisted it. What holds instead is the shape of the tier: it has no
write tools, so there is nothing for a hostile instruction to aim at, and every
action still needs you to take it.

And a model that cannot be reached is reported as unavailable, never as an empty
summary. If a summary is missing, the emails below it are still the thread.
