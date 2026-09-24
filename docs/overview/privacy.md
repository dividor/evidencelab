## Privacy Policy

*Last updated: September 2026*

Evidence Lab is committed to protecting your privacy. This policy explains what data we collect, how we use it, and your rights.

## Browsing without an account

You can browse documents and search results without creating an account. To help us improve the platform, anonymous usage data (search queries, result counts, and timing) is collected locally and associated with a random session identifier stored in your browser. This data is not linked to any personal information and is used solely for system improvements. Standard server logs (IP address, browser user-agent) and optional analytics cookies (see **Cookies** below) may also be captured.

## Account registration

If you choose to create an account, we collect:

- **Email address** — used for sign-in, email verification, and password reset.
- **Password** — stored as a one-way cryptographic hash; we never store or see your plain-text password.
- **Display name** (optional) — shown in the interface so collaborators can identify you.

If you sign in via a third-party provider (Google or Microsoft), we receive your name and email address from that provider. We do not receive or store your third-party password.

## Data we store

| Data | Purpose | Retention |
|------|---------|-----------|
| Email and display name | Authentication and identification | Until you delete your account |
| Hashed password | Secure sign-in | Until you delete your account or reset your password |
| Group memberships | Access control for data sources | Until you leave a group or delete your account |
| OAuth provider link | Federated sign-in (Google/Microsoft) | Until you delete your account |
| Audit log (login events, IP address) | Security monitoring and abuse prevention | 90 days, then automatically purged |
| Failed login attempts and lockout timestamp | Brute-force protection | Reset on successful login or account deletion |
| Search activity (queries, result summaries) | Platform improvement and usage analytics | Until you delete your account |
| Anonymous search activity (queries, result counts, timing) | System improvements (non-logged-in visitors only) | Retained locally; not linked to any personal data |
| Ratings and comments on content | Quality feedback to help improve search and content | Until you delete your account |

## Cookies

Evidence Lab uses the following cookies:

| Cookie | Type | Purpose |
|--------|------|---------|
| `evidencelab_auth` | httpOnly, secure | Session authentication — sent automatically by the browser. Cannot be read by JavaScript. |
| `evidencelab_csrf` | non-httpOnly | CSRF protection — read by the frontend and echoed back as a header to prevent cross-site request forgery. |
| `ga-consent` | localStorage | Records your Google Analytics cookie preference. |
| Google Analytics (`_ga`, `_ga_*`) | Third-party (optional) | Usage analytics to help us understand how people use the platform. Only set if you accept analytics cookies. No data is used for advertising. |

You can change your analytics cookie preference at any time from the Privacy tab.

## How we use your data

- **Authentication and authorisation** — verifying your identity and controlling access to data sources.
- **Email communications** — sending verification emails and password reset links. We do not send marketing emails.
- **Security** — detecting and preventing unauthorised access, brute-force attacks, and abuse.
- **Analytics** (optional) — understanding aggregate usage patterns to improve the platform.
- **Feedback and activity logging** — when you are logged in, your search queries and any ratings you provide are recorded to help us improve search quality and content. This data is associated with your account and deleted when you delete your account.

We do **not** sell, rent, or share your personal data with third parties for marketing purposes.

## Your rights

You have the right to:

- **Access** your data — view your profile, email, and group memberships from the Profile page.
- **Correct** your data — update your display name at any time from the Profile page.
- **Delete** your account — to permanently delete your account, click your user icon in the top-right corner, open **Profile**, scroll to the **Danger zone** section, and follow the confirmation steps. Deletion removes your personal data, group memberships, and OAuth links. This action is irreversible.
- **Export** your data — contact us to request a copy of your data.
- **Withdraw consent** — decline or revoke analytics cookies at any time.

## GDPR compliance

Evidence Lab is designed and operated to comply with the EU General Data Protection Regulation (GDPR, Regulation (EU) 2016/679) and the UK GDPR. This section explains how.

**Data controller.** The {{SITE_HOST}} instance is operated by {{OPERATOR}}. Contact: {{CONTACT_EMAIL_LINK}}. Evidence Lab is open-source software; organisations that run their own instance are the data controller for that instance.

**Legal basis for processing** (Article 6 GDPR):

| Processing | Legal basis |
|-----------|-------------|
| Account data, authentication, group memberships, verification and password-reset emails | Performance of a contract (Art. 6(1)(b)): providing the service you signed up for |
| Security logging, failed-login lockout, audit log | Legitimate interest (Art. 6(1)(f)): protecting the service and its users from abuse |
| Search activity and ratings linked to your account | Legitimate interest (Art. 6(1)(f)): improving search quality; you can delete it at any time by deleting your account |
| Anonymous usage data for visitors without an account | Not personal data: held under a random browser identifier and never linked to a person |
| Analytics cookies | Consent (Art. 6(1)(a)): set only after you accept them, and withdrawable at any time from the Privacy tab |

**Data minimisation and retention.** We collect only the data listed in *Data we store*, for the purposes listed, and keep it for the retention periods given there. Security logs are purged automatically after 90 days. Deleting your account removes your personal data.

**Your rights under the GDPR.** In addition to the rights above, you may object to processing based on legitimate interest, ask us to restrict processing, request a copy of your data in a portable format, and withdraw consent at any time without affecting earlier processing. To exercise any right, use the Profile page or contact us at the address above; we respond within one month. You also have the right to lodge a complaint with your national data protection supervisory authority.

**International transfers.** The service is hosted in {{HOSTING_REGION}}. If you accept analytics cookies, analytics data is processed by Google LLC, including on servers outside the European Economic Area, under the EU-US Data Privacy Framework and Google's standard contractual clauses. No other personal data is transferred outside the EEA.

**Security.** Passwords are stored only as one-way hashes, session tokens are held in httpOnly cookies, all traffic is encrypted in transit (HTTPS), and access to data sources is controlled per user group.

## Contact

If you have questions about privacy or data handling, contact us at {{CONTACT_EMAIL_LINK}}.
