# Single-origin resumes

Company-specific resumes live at `<company>/job-<id>/resume.pdf`. Configure the
targets in `codex.companies` in [resumeme.config.yaml](../resumeme.config.yaml).
LinkedIn postings use their numeric job ID; other job URLs use a stable URL digest.

Each version uses the same profile and styling, with an About paragraph and portrait
summary tailored to the employer and job. The [generic resume](../resume.pdf) stays
separate. CI commits selected PDFs here after verification.

See [company summaries](../docs/codex.md#single-origin-resumes) for setup, local
commands, context overrides, and artifact behavior.
