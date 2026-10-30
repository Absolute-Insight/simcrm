import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'

// Run the public form page's own inline script (crm_form.html), with the Jinja
// values get_context would render, and submit it: success_url is author-entered
// and the page navigates to it after a successful submission.
const html = readFileSync(
  join(
    dirname(fileURLToPath(import.meta.url)),
    '../../../crm/www/crm_form.html',
  ),
  'utf8',
)
const script = html.slice(
  html.lastIndexOf('<script>') + '<script>'.length,
  html.lastIndexOf('</script>'),
)
const PAGE = 'https://crm.example.com/crm-form/lead-capture'

function submitWith(successUrl) {
  document.body.innerHTML = `
    <div id="form-view">
      <div id="form-error"></div><div id="form-ok"></div>
      <form id="web-form"><button type="submit" id="submit-btn">Submit</button></form>
    </div>
    <div id="success-view" style="display:none">
      <h2 id="success-title">Thanks</h2><p id="success-note"></p>
      <p id="redirect-note" style="display:none"></p>
    </div>`
  const code = script
    .replace('{{ form_route | tojson }}', '"lead-capture"')
    .replace('{{ web_form_name | tojson }}', '"lead-capture"')
    .replace('{{ fields | tojson }}', '[]')
    .replace('{{ csrf_token | tojson }}', '""')
    .replace('{{ draft_preview | tojson }}', 'false')
    .replace('{{ success_url | tojson }}', JSON.stringify(successUrl))
    .replace('{{ embed | tojson }}', 'false')
  const assign = vi.fn()
  const page = { location: { href: PAGE, assign } }
  const fetch = async () => ({ ok: true, json: async () => ({}) })
  new Function('window', 'fetch', code)(page, fetch)
  document
    .getElementById('web-form')
    .dispatchEvent(new Event('submit', { cancelable: true }))
  return assign
}
const goNow = () => document.querySelector('#redirect-note a')

afterEach(() => {
  vi.useRealTimers()
  document.body.innerHTML = ''
})

describe('crm_form.html success redirect', () => {
  it.each([
    'javascript:fetch("/api/method/frappe.auth.get_logged_user")',
    '  JavaScript:alert(1)',
    'java\tscript:alert(1)',
    'data:text/html,<script>alert(1)</script>',
    'vbscript:msgbox(1)',
  ])('never navigates to %j', async (url) => {
    vi.useFakeTimers()
    const assign = submitWith(url)
    await vi.advanceTimersByTimeAsync(6000)

    expect(assign).not.toHaveBeenCalled()
    expect(goNow()).toBeNull()
    // the visitor still sees their submission went through
    expect(document.getElementById('success-view').style.display).toBe('block')
  })

  it.each([
    [
      'https://example.com/thanks?a=1&b=2',
      'https://example.com/thanks?a=1&b=2',
    ],
    ['http://example.com/thanks', 'http://example.com/thanks'],
    ['/thank-you', 'https://crm.example.com/thank-you'],
  ])('redirects to %j after the countdown', async (url, target) => {
    vi.useFakeTimers()
    const assign = submitWith(url)
    await vi.advanceTimersByTimeAsync(0)
    expect(goNow().href).toBe(target)
    expect(assign).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(5000)
    expect(assign).toHaveBeenCalledWith(target)
  })
})
