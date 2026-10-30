// The two port conventions the Custom (any IMAP/SMTP) email form promises in
// its labels: SMTP port 465 is implicit TLS, any other port STARTTLS; IMAP with
// SSL off is STARTTLS on 143. crm/api/settings.py custom_service_config applies
// them when the account is created. An edit goes straight to set_value, which
// stores only the fields it is sent, so without this the account kept the
// flags of the port it was created on and failed the next SMTP/IMAP handshake.

function portOf(value) {
  return parseInt(String(value ?? '').trim(), 10) || 587
}

/**
 * The transport flags an edit of a Custom account implies, for set_value.
 *
 * Only a field the admin changed moves its flags: an account configured
 * server-by-server in the desk keeps whatever it was set to until the port or
 * the SSL box is touched here.
 */
export function customTransportChanges(state, original) {
  const changes = {}
  const port = portOf(state.smtp_port)
  if (port !== portOf(original.smtp_port)) {
    const ssl = port === 465 ? 1 : 0
    changes.use_ssl_for_outgoing = ssl
    changes.use_tls = ssl ? 0 : 1
  }
  if (Boolean(Number(state.use_ssl)) !== Boolean(Number(original.use_ssl))) {
    const ssl = state.use_ssl ? 1 : 0
    changes.use_ssl = ssl
    changes.use_starttls = ssl ? 0 : 1
    // frappe stores the port it resolved at create time (993 for SSL), so a
    // box unticked without this would speak plain IMAP to the SSL port.
    changes.incoming_port = ssl ? '993' : '143'
  }
  return changes
}
