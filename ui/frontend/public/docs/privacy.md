# Privacy Policy

*Last updated: March 2026*

Evidence Lab is committed to protecting your privacy. This policy explains what data we collect, how we use it, and your rights.

## Browsing without an account

You can browse documents and search results without creating an account. In this case, no personal data is collected beyond standard server logs (IP address, browser user-agent) and optional analytics cookies (see **Cookies** below).

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

We do **not** sell, rent, or share your personal data with third parties for marketing purposes.

## Your rights

You have the right to:

- **Access** your data — view your profile, email, and group memberships from the Profile page.
- **Correct** your data — update your display name at any time from the Profile page.
- **Delete** your account — to permanently delete your account, click your user icon in the top-right corner, open **Profile**, scroll to the **Danger zone** section, and follow the confirmation steps. Deletion removes your personal data, group memberships, and OAuth links. This action is irreversible.
- **Export** your data — contact us to request a copy of your data.
- **Withdraw consent** — decline or revoke analytics cookies at any time.

## Data security

- Passwords are hashed using a strong one-way algorithm (bcrypt).
- Authentication cookies are httpOnly and secure, preventing JavaScript access.
- CSRF tokens protect against cross-site request forgery.
- Accounts are locked after repeated failed login attempts.
- All data is transmitted over HTTPS in production.

## Contact

If you have questions about privacy or data handling, contact us at [evidencelab@astrobagel.com](mailto:evidencelab@astrobagel.com).
