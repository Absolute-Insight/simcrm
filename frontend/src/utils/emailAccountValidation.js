// Pure validation for the email-account settings forms. Lives outside the
// utils barrel (index.js) so unit tests can import it without dragging in
// frappe-ui, Vue components, and icon modules.

export function validateEmail(email) {
  let regExp =
    /^(([^<>()[\]\\.,;:\s@"]+(\.[^<>()[\]\\.,;:\s@"]+)*)|(".+"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$/
  return regExp.test(email)
}

export function validateInputs(state, serviceName) {
  if (!state.email_account_name) {
    return __('Account name is required')
  }
  if (!state.email_id) {
    return __('Email ID is required')
  }
  if (!validateEmail(state.email_id)) {
    return __('Invalid email ID')
  }
  if (serviceName === 'Frappe Mail') {
    if (!state.api_key) {
      return __('API key is required')
    }
    if (!state.api_secret) {
      return __('API secret is required')
    }
    return ''
  }
  if (!state.password) {
    return __('Password is required')
  }
  if (serviceName === 'Custom' || !serviceName) {
    if (!state.email_server) {
      return __('IMAP server is required')
    }
    if (!state.smtp_server) {
      return __('SMTP server is required')
    }
    if (state.smtp_port && !/^\d+$/.test(String(state.smtp_port).trim())) {
      return __('SMTP port must be a number')
    }
  }
  return ''
}
