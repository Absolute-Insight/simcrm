/**
 * The Vectora help centre: what it contains and in what order.
 *
 * One manifest, two readers. The Help page renders it as a rail, and the help
 * panel off the sidebar renders the same entries as its article list -- which
 * is why the list is not written out twice. It used to be, in AppSidebar.vue,
 * as thirty-four links to docs.frappe.io: another product's documentation, under
 * another product's branding, describing features this one renamed and missing
 * every feature it added.
 *
 * `slug` is both the route (`/crm/help/<slug>`) and the filename under
 * `content/`. `summary` is what the rail shows under the title and what the
 * search matches on alongside the body.
 */

export const HELP_SECTIONS = [
  {
    title: 'Getting started',
    articles: [
      {
        slug: 'introduction',
        title: 'What Vectora is',
        summary:
          'A CRM that opens with what needs attention, not an empty list.',
      },
      {
        slug: 'your-first-week',
        title: 'Your first week',
        summary:
          'Where to start as a rep, and what to set up as an administrator.',
      },
    ],
  },
  {
    title: 'Working your pipeline',
    articles: [
      {
        slug: 'suggestions',
        title: 'The suggestion inbox',
        summary:
          'What each signal means, and what accepting or dismissing one does.',
      },
      {
        slug: 'deal-health',
        title: 'Deal health',
        summary:
          'How a deal is scored, and what "at risk" is measured against.',
      },
      {
        slug: 'planner',
        title: 'Weekly planning',
        summary: 'Plan a week, and let real activity resolve it.',
      },
      {
        slug: 'leads-and-deals',
        title: 'Leads, deals and records',
        summary: 'The record types, and how a lead becomes a deal.',
      },
    ],
  },
  {
    title: 'Measuring',
    articles: [
      {
        slug: 'dashboard',
        title: 'The dashboard',
        summary: 'What a rep sees, what a manager sees, and why they differ.',
      },
      {
        slug: 'reports',
        title: 'Reports and exports',
        summary: 'The six built-in reports, CSV export and print.',
      },
      {
        slug: 'forecasting',
        title: 'Forecasting',
        summary: 'Weighted pipeline, snapshots, and forecast against actual.',
      },
      {
        slug: 'quotas',
        title: 'Sales targets',
        summary:
          'Set a quota per rep per month, and read attainment against it.',
      },
      {
        slug: 'digests',
        title: 'Scheduled digests',
        summary: 'Send a report to an inbox on a schedule.',
      },
    ],
  },
  {
    title: 'Administration',
    articles: [
      {
        slug: 'assistant',
        title: 'The assistant',
        summary:
          'What the model tier adds, and how to point it at a local model.',
      },
      {
        slug: 'automation-rules',
        title: 'Automation rules',
        summary: 'React to a status change without writing code.',
      },
      {
        slug: 'assignment-and-sla',
        title: 'Assignment, SLAs and hierarchy',
        summary:
          'Who gets a record, how fast it must be answered, who rolls up to whom.',
      },
      {
        slug: 'email',
        title: 'Email',
        summary: 'Connect an account, and reuse what you write.',
      },
      {
        slug: 'form-scripts',
        title: 'Form scripts',
        summary: 'Change how a form behaves, from a record in the CRM.',
      },
      {
        slug: 'integrations',
        title: 'Integrations',
        summary: 'Telephony, WhatsApp, ERPNext, lead syncing and web forms.',
      },
    ],
  },
  {
    title: 'Mobile',
    articles: [
      {
        slug: 'mobile',
        title: 'Vectora on a phone',
        summary:
          'Add it to the home screen, and what changes on a small screen.',
      },
    ],
  },
]

/** Every article, flattened, in rail order. */
export const HELP_ARTICLES = HELP_SECTIONS.flatMap((section) =>
  section.articles.map((article) => ({ ...article, section: section.title })),
)

export function findArticle(slug) {
  return HELP_ARTICLES.find((article) => article.slug === slug) || null
}

/** The first article, which is what `/help` with no slug resolves to. */
export const FIRST_ARTICLE = HELP_ARTICLES[0]

/**
 * The manifest in the shape `<HelpModal>` wants for its article list.
 *
 * That component is frappe's, not ours, and it opens
 * `${docsLink}/${name}` in a new tab -- so pointing `docsLink` at
 * `/crm/help` is all it takes to keep a rep inside this product. `opened`
 * is the panel's own disclosure state; it lives on the object it renders.
 */
export function helpPanelArticles(translate = (value) => value) {
  return HELP_SECTIONS.map((section) => ({
    title: translate(section.title),
    opened: false,
    subArticles: section.articles.map((article) => ({
      name: article.slug,
      title: translate(article.title),
    })),
  }))
}
