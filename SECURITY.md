# Security policy

## Supported versions

Security fixes target the latest published release and the `main` branch of
[astrivant/resumeme](https://github.com/astrivant/resumeme). Older releases do not
receive separate security backports. Fork maintainers are responsible for applying
upstream fixes and maintaining their own reporting channels.

## Sensitive data and publication

Resumeme runs in the user's checkout and GitHub Actions environment. It captures
profile information available to the signed-in account, including Contact info
fields when present. The upstream project does not operate a service that receives
fork captures or credentials; configured workflows communicate with LinkedIn,
GitHub, and enabled external providers.

Before enabling automation, read the [data-handling inventory](docs/data-handling.md).
It documents each storage location, recipient, artifact retention period,
encryption boundary, cleanup limit, and recovery procedure. In particular:

- **Hidden PDF content remains in captured source.** Section, job, school, photo,
  and birthday visibility settings do not redact the snapshot. Refreshes upload
  the full accepted profile and referenced images; main publication also commits
  them. This can expose
  contact details and other information absent from the PDF.
- **Browser sessions are account credentials.** Ordinary local capture retains
  a dedicated browser profile without resumeme encryption. CI's optional encrypted session cache
  protects stored copies, while the active job uses plaintext. Runner compromise,
  exposed decrypting keys, or incomplete cleanup can expose that login.
- **Most outputs are intended to be shared.** Profile/build artifacts, prompts,
  model results, PDFs, TeX, README previews, and repository history are not encrypted
  by the session-cache feature. Signing provides integrity, not confidentiality.
  Releases, Pages, and public signing metadata can outlive the originating job.
- **Optional AI processing sends profile evidence and configured context to
  OpenAI.** Prompt filters and the upstream action's permissions are not a
  guarantee that only non-sensitive text can reach the provider or logs.
- **Secrets and their consumers must be trusted.** Keep credentials out of
  configuration and source. Review credential-bearing workflows and dependencies,
  restrict runner access, and protect key backups. Generated backup directories
  contain both the encrypted private key and its password.

The [session-cache guide](docs/linkedin-session-cache.md) covers setup. The
[disable/delete/recovery procedure](docs/data-handling.md#disable-delete-or-respond-to-exposure)
explains why deleting a cache or changing a display setting does not revoke an
account session or remove already-published copies.

## Automated source scanning

The required CI test stage runs Trivy against the checked-out repository using
the `aquasec/trivy:0.75.0` image. It checks filesystem dependencies for known
vulnerabilities and repository files for secret patterns. The checkout is mounted
read-only; repository-provided Trivy configuration, ignore files, and secret
rules are not loaded. A finding, scanner error, or invalid report fails the
`CI verification` check on pull requests and pushes.

Before upload, report processing removes source snippets and redacts matched
secret text. CI retains the sanitized report artifact for 90 days. A follow-up
workflow posts or updates a pull request comment with finding counts and links to
the report and scan logs. That workflow checks out the default branch, not pull
request code, and alone receives permission to write issue comments. See the
[Trivy pipeline details](docs/automation.md#trivy-security-scan) and its
[scanner stage](.github/workflows/stage-test.yml),
[report redaction code](scripts/ci/trivy-report.py), and
[pull request comment workflow](.github/workflows/trivy-pr-comment.yml).

This is a source-filesystem scan, not a scan of the built container image, runner,
or live services. A clean result cannot establish that the application or its
dependencies are free from vulnerabilities. Review the full sanitized report and
address findings in the affected source or dependency declaration.

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

Upstream maintainers operate `astrivant/resumeme` and maintain its code and
security reporting. Each fork owner operates their own repository, accounts,
secrets, runners, provider settings, and publications. We do not administer,
monitor, or secure those resources for them. Fork owners decide what personal
data to collect and publish, review changes before granting credentials, apply
updates, and handle incidents in their deployment.

Before using this policy in a fork, replace the reporting links with a channel
your maintainers monitor. Enable GitHub private vulnerability reporting if using
the advisory form. Report vulnerabilities in upstream resumeme code to the
upstream project; report fork-specific infrastructure or changes to the fork owner.
