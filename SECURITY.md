# Security policy

## Supported versions

Security fixes target the latest published release and the `main` branch of
[astrivant/resumeme](https://github.com/astrivant/resumeme). Older releases do not
receive separate security backports. Fork maintainers are responsible for applying
upstream fixes and maintaining their own reporting channels.

## Reporting a vulnerability

Report vulnerabilities privately before opening a public issue or pull request.
When GitHub private vulnerability reporting is enabled, use
[Report a vulnerability](https://github.com/astrivant/resumeme/security/advisories/new).

If that form is unavailable, open an
[issue requesting a private reporting channel](https://github.com/astrivant/resumeme/issues/new?title=Private%20security%20reporting%20contact).
Include only the request for contact. Wait for a private channel before sharing
the vulnerability, reproduction steps, or affected systems.

In the private report, include:

- The affected release or commit, installation method, and operating system.
- The affected component and potential impact.
- Minimal reproduction steps or a proof of concept using synthetic data.
- Relevant sanitized logs and any proposed mitigation.

Relevant vulnerabilities include credential or browser-session exposure, unsafe
handling of captured content or remote assets, command or template injection,
unauthorized profile updates, and compromised build or release artifacts.

Do not send passwords, session cookies, API tokens, private signing keys, or
another person's profile data. Use the regular issue tracker for non-security bugs.

## Response and disclosure

Maintainers aim to acknowledge private reports within 7 days. This is a best-effort
target, not a guaranteed response time. Follow up in the private reporting channel
if you have not received a response.

Maintainers will assess the impact, discuss mitigations and a disclosure timeline
with the reporter, and coordinate a fix. Remediation timing depends on severity
and reproducibility. Please keep exploit details private while that coordination
is in progress.

Confirmed vulnerabilities and available fixes will be documented in
[security advisories](https://github.com/astrivant/resumeme/security/advisories)
and the relevant [release notes](https://github.com/astrivant/resumeme/releases).
Reporter credit is included with consent.

## Forks

Before using this policy in a fork, replace the reporting links with a channel
your maintainers monitor. Enable GitHub private vulnerability reporting if using
the advisory form. Report vulnerabilities in upstream resumeme code to the
upstream project; report fork-specific infrastructure or changes to the fork owner.
