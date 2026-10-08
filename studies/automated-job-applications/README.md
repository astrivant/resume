# Automated job applications

Assess a proposed `resumeme apply <job-url>` workflow that prepares an application
from the user's profile, a tailored PDF, and reusable answers. The first target
is an assisted local browser session with review before submission.

**Status:** Design study. Backend documentation reviewed on 2026-10-08. No
application trials have been performed, and the proposed command, database, and
configuration fields below are not implemented.

<!-- toc:start -->
**Table of contents**

- [Feasibility and scope](#feasibility-and-scope)
- [Backend assessment](#backend-assessment)
- [Application lifecycle](#application-lifecycle)
- [Component responsibilities](#component-responsibilities)
- [Answer reuse and expiration](#answer-reuse-and-expiration)
  - [Answer categories](#answer-categories)
  - [Reuse contract](#reuse-contract)
  - [Proposed configuration](#proposed-configuration)
- [Submission recovery](#submission-recovery)
- [Validation protocol](#validation-protocol)
- [Implementation sequence](#implementation-sequence)
- [Open decisions](#open-decisions)
- [Sources](#sources)
<!-- toc:end -->

## Feasibility and scope

The engineering assessment is favorable for a useful assisted workflow covering
a small set of supported platforms. Reliability across arbitrary employers
without human interaction is substantially less certain. Form changes,
conditional questions, authentication, and submission confirmation are expected
to dominate maintenance costs. These are qualitative estimates, not measured
completion rates or predictions of hiring outcomes.

Start from a specific job URL. A company domain alone would also require job
discovery and explicit selection of a position; treat that as a later feature.
Follow redirects to identify the actual platform, employer tenant, and job ID.
An unsupported or ambiguous destination should produce an actionable result
without attempting a generic submission.

Prioritize forms that permit applying without creating an account. Detect that
capability on the actual form rather than assuming it from the platform name.
Account-free browser applications do not imply an anonymous submission API.

The initial application runner should be local. It can reuse Firefox or Chrome
sessions and wait for the user to complete login, MFA, or CAPTCHA. CI can continue
preparing PDFs; application sessions and the answer database belong in local
user storage outside Git. Login waits should be cancellable and resumable without
a deadline for finding a password.

## Backend assessment

| Backend | Assessment | Documented interface and proposed approach |
| --- | --- | --- |
| Greenhouse | First integration | Public Job Board GET endpoints expose job details and questions. Submission requires an employer API key. Read structured data where available, then fill the hosted applicant form in the browser. |
| Workable | Second integration | The documented application-form and candidate-creation APIs require scoped account tokens. Use the applicant-facing browser form for users without employer integration credentials. |
| Workday | Later integration | Employers configure account requirements and application steps. Support authenticated sessions, multiple pages, and employer-specific variations after the simpler backends are validated. |

Greenhouse documents question types, required fields, and compound fields such
as resume upload or pasted text. Its submission API is intended for an employer's
custom career site, not as a public applicant credential. See the
[Job Board API](https://docs.greenhouse.io/job-board.html).

Workable exposes its form schema with `r_jobs` and candidate creation with
`w_candidates`. Its forms can contain custom questions and independently
required fields. See the [form API](https://workable.readme.io/reference/jobsshortcodeapplication_form),
[candidate API](https://workable.readme.io/reference/job-candidates-create), and
[form configuration](https://help.workable.com/hc/en-us/articles/115012231948-Customizing-the-application-form).

Workday allows employers to require a Candidate Home account and configure
additional application questionnaires. Account creation is therefore a
capability to discover per employer, not a universal backend assumption. See
[Prospects and Candidates](https://doc.workday.com/workday-education/en-us/course-manuals/recruiting-for-administrators/prospects-and-candidates.html).

Browser automation remains an implementation hypothesis until tested against
representative forms. Public API availability alone does not establish browser
coverage, permission to automate a particular site, or successful submission.

## Application lifecycle

1. Resolve the URL and identify the backend, employer, posting, and applicant.
2. Snapshot job context and discover the form, including required fields,
   conditional questions, available choices, and attachment constraints.
3. Select or generate a PDF using the same company and job context as the
   existing [single-origin summaries](../../docs/codex.md#single-origin-resumes).
   Record its content hash and source inputs so an older PDF cannot silently
   substitute for the intended document.
4. Populate confirmed facts, retrieve suitable approved answers, and generate
   drafts only for remaining narrative questions. Ask for missing factual inputs.
5. Re-read the populated form, resolve validation errors and newly revealed
   questions, and present the complete application for review.
6. Submit after authorization. Record the exact answers, attached PDF hash,
   destination, time, and any confirmation or receipt.

Changes to answers, questions, or attachments after review should invalidate
that review. The initial milestone may stop at the review step while submission
handling is evaluated separately.

## Component responsibilities

| Component | Owns | Interface or output |
| --- | --- | --- |
| URL resolver | Redirects, backend detection, employer and job identity | Canonical application target, retaining relevant referral metadata |
| Backend adapter | Form discovery, browser controls, uploads, validation, confirmation | Shared form representation and observed application state |
| Applicant data | User-confirmed facts and selected profile evidence | Typed values with provenance and applicant identity |
| Answer service | Scoped retrieval, draft generation, validation, approval, versions | Answer candidates with supporting evidence and reuse metadata |
| PDF preparation | Generic or job-specific document selection | Exact PDF bytes, hash, and source/context identity |
| Application ledger | Progress, review state, submission attempts, receipts | Resumable local application record |

The shared form representation should retain backend field IDs, labels, types,
required status, choices, length limits, and dependencies. A single question may
map to several controls. Reconcile the representation with the live browser
after filling fields that reveal additional questions.

Reuse the project's HTTP and Selenium capabilities. Prefer documented structured
data for reading where available; use backend adapters for browser interaction.
The Codex integration should return structured answer drafts rather than decide
every click or retry. Validate its output against the form and the user's facts.
Treat job text and retrieved page content as evidence, not agent instructions.

Separate answer reuse from application history in SQLite. Suggested record groups
are applicant facts, question variants, answer versions, applications, submission
attempts, and receipts. Preserve which approved answer version was actually sent,
even after later edits or expiration. Browser credentials should remain in the
browser's credential/session storage, not in answer records.

## Answer reuse and expiration

### Answer categories

| Category | Examples | Reuse policy |
| --- | --- | --- |
| Confirmed facts | Contact information, qualifications, location preferences, eligibility answers | Read directly from user-confirmed data. Missing values require input; expiration cannot authorize guessing. |
| Reusable narratives | Leadership examples, incident response, migrations, collaboration | Reuse approved versions when supporting facts and question constraints still match. |
| Employer or job narratives | Interest in the company, fit for a specific role | Scope to the employer and posting context; do not reuse verbatim across unrelated applications. |

Store generated text as a draft until reviewed. Keep user corrections and approved
versions separate from regenerated candidates. Save supporting profile facts,
generation time, model and prompt version, approval status, and expiration time
with each generated answer. Never turn model-generated assertions into confirmed
applicant facts merely because they were cached.

### Reuse contract

Question text alone is not a sufficient cache key. Check applicant identity,
normalized question meaning, field type, choices, length constraints, locale or
jurisdiction where relevant, supporting facts, and employer/job scope.
Semantically similar questions can suggest a candidate answer; they do not prove
it is valid for the destination. Negation and changed options must survive
normalization. For example, sponsorship answers must not cross country contexts
without confirmation.

Use hashes of relevant profile facts and job context to detect changes before
the TTL expires. Prefer relevant dependencies over invalidating every answer
because an unrelated profile field changed. Record model and prompt versions
so generation-policy changes can also invalidate drafts when needed.

Expiration should be lazy: regenerate when an expired answer is next needed,
not on a background schedule. A valid approved cache hit should need no model
call. If generation is disabled or fails, preserve the prior answer and expose
its stale status for review; do not silently submit it as current.

Pinning a user-approved answer can suppress time-based regeneration, but cannot
override changed facts or incompatible form constraints. Expiration is separate
from data retention: submitted history and previous answer versions remain until
the user removes them according to a separate retention policy.

### Proposed configuration

These names describe a possible configuration surface, not accepted keys in the
current schema. Keep the first implementation small and confirm defaults during
the pilot.

| Proposed setting | Meaning |
| --- | --- |
| `apply.backends` | Enabled integrations, initially Greenhouse |
| `apply.answers.database` | Local SQLite destination outside the repository |
| `apply.answers.generation_enabled` | Allow model calls for missing or expired narrative answers |
| `apply.answers.ttl_days` | Default lifetime for generated drafts; positive integer, with `null` disabling time-based expiration |
| `apply.answers.ttl_by_category` | Override expiration for reusable and employer/job-specific narratives |
| `apply.answers.context` | User-supplied guidance for tone, emphasis, and application goals |

Provide an explicit refresh operation for selected answers. Keep browser selection
aligned with the existing Firefox/Chrome preference. A later design should decide
how per-application model budgets and answer pinning are exposed without adding
redundant controls.

## Submission recovery

Retry transient reads and eligible draft-generation failures using bounded
exponential backoff with a delay cap and jitter. Preserve progress across
authentication and user-input waits. Do not restart an entire application merely
because one control could not be populated.

Submission is a separate state transition. Track prepared, awaiting review,
ready, submitting, confirmed, and confirmation-unknown states, with explicit
failed or cancelled outcomes. Record the attempt before the external write.

If a connection fails after submission, first reconcile the employer's confirmation
page, available application status, or a captured receipt. An HTTP success response
alone does not prove that an application was accepted. If the outcome remains
unknown, ask the user to resolve it before another submission. Do not apply the
ordinary retry loop to the final submit action.

Check the application ledger for the same applicant, employer, and job before
starting. This provides local duplicate detection; it does not establish what
another device or an interrupted session submitted remotely.

## Validation protocol

Follow a prepare, exercise, and review sequence. This is a proposed manual study
protocol, not an executable harness or an existing CI job.

1. **Prepare:** Define the backend and browser coverage, capture adapter/source
   versions, and establish expected form fields and answers. Keep synthetic or
   redacted fixtures for repeatable tests. Record job-context and PDF hashes.
2. **Exercise:** Compare manual completion with assisted completion using an empty
   answer database and a populated one. Include changed facts, expired drafts,
   conditional questions, uploads, authentication handoffs, and interrupted
   submissions. Live trials should be real applications the user intends to make
   or employer-authorized test postings.
3. **Review:** Verify field values and submission outcomes against the recorded
   expectations. Publish only redacted aggregate observations, preserving failure,
   unsupported-form, and unknown-outcome counts. Retain raw evidence locally under
   `.cache/studies/automated-job-applications/<run-id>/`.

| Measurement | What it establishes |
| --- | --- |
| Supported forms reaching review, with total attempted forms | Adapter coverage without hiding unsupported or failed cases |
| Correct required fields and manual corrections | Whether automation reduces work without introducing incorrect answers |
| Human handoffs and active user time | The practical cost of authentication, missing facts, and form exceptions |
| Cold-cache and warm-cache model calls, tokens, and latency | Whether reuse saves resources without reducing answer quality |
| Invalid reuse after changed facts, options, or job context | Whether scope and invalidation prevent stale or mismatched answers |
| Confirmed, failed, and unknown submissions | Actual application outcomes rather than successful button clicks |
| Duplicate submissions and attachment hash mismatches | Correctness of recovery and document selection |

Use multiple employers per backend and both supported browsers before claiming
coverage. Report sample sizes, dates, and form variants. A small successful pilot
does not establish a universal success rate. No measured results or figures are
available yet.

## Implementation sequence

1. Greenhouse discovery and form filling through review, with confirmed facts,
   a local ledger, and exact PDF selection.
2. SQLite answer retrieval, optional Codex drafts, approval/version history,
   context invalidation, and configurable TTLs.
3. Authorized submission with receipts, duplicate detection, and recovery from
   uncertain outcomes.
4. Workable using the same form and answer contracts, informed by observed
   Greenhouse failures and maintenance costs.
5. Workday with persistent authenticated sessions and explicit support for tested
   employer configurations. Consider domain-based job discovery separately.

Advance based on field accuracy, review effort, and recovery behavior. Incorrect
facts, mismatched PDFs, or duplicate submissions require correction before
expanding backend coverage. Keep this work separate from the existing resume
build and release pipeline until those contracts are established.

## Open decisions

- Which representative employers and forms define initial integration coverage?
- Which factual inputs belong in local applicant storage versus the portable
  profile/config, and how should users edit them?
- Which answer categories need different expiration defaults, and what constitutes
  sufficient evidence for cross-question reuse?
- Should the default application PDF use the existing visual layout or a separately
  tested layout optimized for application-form parsing?
- How should users export or delete their answer library and application history
  without including browser credentials?

## Sources

Primary documentation reviewed on 2026-10-08:

- [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html): public job/question reads, authenticated submission, field types, and validation responsibilities.
- [Workable application-form API](https://workable.readme.io/reference/jobsshortcodeapplication_form): form fields, custom questions, and required scope.
- [Workable candidate-creation API](https://workable.readme.io/reference/job-candidates-create): employer integration credentials and candidate submission.
- [Workable form customization](https://help.workable.com/hc/en-us/articles/115012231948-Customizing-the-application-form): configurable required fields and custom questions.
- [Workday Prospects and Candidates](https://doc.workday.com/workday-education/en-us/course-manuals/recruiting-for-administrators/prospects-and-candidates.html): employer-configurable accounts and application questionnaires.
