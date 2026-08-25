import { validateInputs } from '@/utils/emailAccountValidation'

import LogoGmail from '@/images/gmail.png'
import LogoOutlook from '@/images/outlook.png'
import LogoSendgrid from '@/images/sendgrid.png'
import LogoSparkpost from '@/images/sparkpost.webp'
import LogoYahoo from '@/images/yahoo.png'
import LogoYandex from '@/images/yandex.png'
import LogoFrappeMail from '@/images/frappe-mail.svg'
import LogoCustomMail from '@/images/custom-mail.svg'

const fixedFields = [
  {
    label: __('Account Name'),
    name: 'email_account_name',
    type: 'text',
    placeholder: __('Support / Sales'),
  },
  {
    label: __('Email ID'),
    name: 'email_id',
    type: 'email',
    placeholder: 'johndoe@example.com',
  },
]

export const incomingOutgoingFields = [
  {
    label: __('Enable Incoming'),
    name: 'enable_incoming',
    type: 'checkbox',
    description: __('If enabled, emails will be pulled from this account.'),
  },
  {
    label: __('Enable Outgoing'),
    name: 'enable_outgoing',
    type: 'checkbox',
    description: __(
      'If enabled, outgoing emails can be sent from this account.',
    ),
  },
  {
    label: __('Default Incoming'),
    name: 'default_incoming',
    type: 'checkbox',
    description: __(
      'If enabled, all replies to your company (eg: replies@yourcompany.com) will come to this account. Note: Only one account can be default incoming.',
    ),
  },
  {
    label: __('Default Outgoing'),
    name: 'default_outgoing',
    type: 'checkbox',
    description: __(
      'If enabled, all outgoing emails will be sent from this account. Note: Only one account can be default outgoing.',
    ),
  },
  {
    label: __('Create Lead from Incoming Emails'),
    name: 'create_lead_from_incoming_email',
    type: 'checkbox',
    description: __(
      'If enabled, a lead will be automatically created when an incoming email is received from an unknown contact.',
    ),
    condition: (state) => state.enable_incoming,
  },
]

export const popularProviderFields = [
  ...fixedFields,
  {
    label: __('Password'),
    name: 'password',
    type: 'password',
    placeholder: '********',
  },
]

export const customProviderFields = [
  ...fixedFields,
  {
    label: __('Frappe Mail Site'),
    name: 'frappe_mail_site',
    type: 'text',
    placeholder: 'https://frappemail.com',
  },
  {
    label: __('API Key'),
    name: 'api_key',
    type: 'text',
    placeholder: '********',
  },
  {
    label: __('API Secret'),
    name: 'api_secret',
    type: 'password',
    placeholder: '********',
  },
]

export const imapSmtpProviderFields = [
  ...fixedFields,
  {
    label: __('Password'),
    name: 'password',
    type: 'password',
    placeholder: '********',
  },
  {
    label: __('IMAP Server'),
    name: 'email_server',
    type: 'text',
    placeholder: 'imap.example.com',
  },
  {
    label: __('Use SSL for Incoming (IMAP port 993; off = STARTTLS on 143)'),
    name: 'use_ssl',
    type: 'checkbox',
  },
  {
    label: __('SMTP Server'),
    name: 'smtp_server',
    type: 'text',
    placeholder: 'smtp.example.com',
  },
  {
    label: __('SMTP Port (465 switches outgoing to SSL)'),
    name: 'smtp_port',
    type: 'text',
    placeholder: '587',
  },
]

export function fieldsForService(serviceName) {
  if (serviceName === 'Frappe Mail') {
    return customProviderFields
  }
  // An account with no service is one configured server-by-server: Custom
  // accounts are stored that way, and so are accounts created from the desk.
  if (!serviceName || serviceName === 'Custom') {
    return imapSmtpProviderFields
  }
  return popularProviderFields
}

export const services = [
  {
    name: 'GMail',
    icon: LogoGmail,
    info: __(
      'Setting up GMail requires you to enable two factor authentication and app specific passwords. Read more',
    ),
    link: 'https://support.google.com/accounts/answer/185833',
    custom: false,
  },
  {
    name: 'Outlook',
    icon: LogoOutlook,
    info: __(
      'Setting up Outlook requires you to enable two factor authentication and app specific passwords. Read more',
    ),
    link: 'https://support.microsoft.com/en-us/account-billing/how-to-get-and-use-app-passwords-5896ed9b-4263-e681-128a-a6f2979a7944',
    custom: false,
  },
  {
    name: 'Sendgrid',
    icon: LogoSendgrid,
    info: __(
      'Setting up Sendgrid requires you to enable two factor authentication and app specific passwords. Read more',
    ),
    link: 'https://sendgrid.com/docs/ui/account-and-settings/two-factor-authentication/',
    custom: false,
  },
  {
    name: 'SparkPost',
    icon: LogoSparkpost,
    info: __(
      'Setting up Sparkpost requires you to enable two factor authentication and app specific passwords. Read more',
    ),
    link: 'https://support.sparkpost.com/docs/my-account-and-profile/enabling-two-factor-authentication',
    custom: false,
  },
  {
    name: 'Yahoo',
    icon: LogoYahoo,
    info: __(
      'Setting up Yahoo requires you to enable two factor authentication and app specific passwords. Read more',
    ),
    link: 'https://help.yahoo.com/kb/SLN15241.html',
    custom: false,
  },
  {
    name: 'Yandex',
    icon: LogoYandex,
    info: __(
      'Setting up Yandex requires you to enable two factor authentication and app specific passwords. Read more',
    ),
    link: 'https://yandex.com/support/id/authorization/app-passwords.html',
    custom: false,
  },
  {
    name: 'Frappe Mail',
    icon: LogoFrappeMail,
    info: __(
      'Setting up Frappe Mail requires you to have an API key and API secret for your email account. Read more',
    ),
    link: 'https://github.com/frappe/mail',
    custom: true,
  },
  {
    name: 'Custom',
    icon: LogoCustomMail,
    info: __(
      'Connect any provider over IMAP/SMTP with a mailbox or app password. Incoming defaults to SSL on port 993; SMTP port 465 uses SSL for outgoing, any other port STARTTLS. Read more',
    ),
    link: 'https://docs.erpnext.com/docs/user/manual/en/email-account',
    custom: false,
  },
]

export const emailIcon = {
  GMail: LogoGmail,
  Outlook: LogoOutlook,
  Sendgrid: LogoSendgrid,
  SparkPost: LogoSparkpost,
  Yahoo: LogoYahoo,
  Yandex: LogoYandex,
  // saved accounts carry the select's own values, not the dialog names
  'Outlook.com': LogoOutlook,
  'Yahoo Mail': LogoYahoo,
  'Yandex.Mail': LogoYandex,
  'Frappe Mail': LogoFrappeMail,
  Custom: LogoCustomMail,
}

export { validateInputs }
