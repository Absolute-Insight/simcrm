import { describe, it, expect } from 'vitest'
import { validateEmail, validateInputs } from '@/utils/emailAccountValidation'

const base = {
  email_account_name: 'Support',
  email_id: 'support@example.com',
  password: 'secret',
}

describe('validateEmail', () => {
  it('accepts a normal address and rejects junk', () => {
    expect(validateEmail('a.b@example.co')).toBe(true)
    expect(validateEmail('not-an-email')).toBe(false)
    expect(validateEmail('missing@tld')).toBe(false)
  })
})

describe('validateInputs', () => {
  it('requires account name, email id, and a valid email', () => {
    expect(validateInputs({ ...base, email_account_name: '' }, 'GMail')).toBe(
      'Account name is required',
    )
    expect(validateInputs({ ...base, email_id: '' }, 'GMail')).toBe(
      'Email ID is required',
    )
    expect(validateInputs({ ...base, email_id: 'nope' }, 'GMail')).toBe(
      'Invalid email ID',
    )
  })

  it('requires a password for every non-Frappe-Mail service', () => {
    expect(validateInputs({ ...base, password: '' }, 'GMail')).toBe(
      'Password is required',
    )
    expect(validateInputs({ ...base, password: '' }, 'Custom')).toBe(
      'Password is required',
    )
    expect(validateInputs(base, 'GMail')).toBe('')
  })

  it('requires api key AND api secret for Frappe Mail', () => {
    const fm = { ...base, password: '', api_key: 'k', api_secret: 's' }
    expect(validateInputs(fm, 'Frappe Mail')).toBe('')
    expect(validateInputs({ ...fm, api_key: '' }, 'Frappe Mail')).toBe(
      'API key is required',
    )
    // regression: a missing api secret used to return undefined, which the
    // dialogs treated as "valid" and submitted anyway
    expect(validateInputs({ ...fm, api_secret: '' }, 'Frappe Mail')).toBe(
      'API secret is required',
    )
  })

  it('requires both servers and a numeric port for Custom', () => {
    const custom = {
      ...base,
      email_server: 'imap.example.com',
      smtp_server: 'smtp.example.com',
      smtp_port: '587',
    }
    expect(validateInputs(custom, 'Custom')).toBe('')
    expect(validateInputs({ ...custom, email_server: '' }, 'Custom')).toBe(
      'IMAP server is required',
    )
    expect(validateInputs({ ...custom, smtp_server: '' }, 'Custom')).toBe(
      'SMTP server is required',
    )
    expect(validateInputs({ ...custom, smtp_port: '58x' }, 'Custom')).toBe(
      'SMTP port must be a number',
    )
    // an empty port is fine -- the backend defaults it to 587
    expect(validateInputs({ ...custom, smtp_port: '' }, 'Custom')).toBe('')
  })
})
