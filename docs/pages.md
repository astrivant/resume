# GitHub Pages

Publish the current résumé at your site's `index.html`, with an embedded PDF,
open/download links, public profile links, and a link to signed releases.
The page uses your captured name, `publishing.readme.introduction`, and the selected theme's
colors. It serves the same working PDF accepted on `main`.

## Enable publication

1. In your fork, select **Settings > Pages > Build and deployment > Source >
   GitHub Actions**.
2. Update `resumeme.config.yaml`:

   ```yaml
   publishing:
     pages:
       enabled: true
       path: /
       custom_domain: null
   ```

3. Push to `main`, or run `gh workflow run ci.yml --ref main` after pushing the
   configuration. The website updates after verification and PDF publication.

The default address is `https://OWNER.github.io/REPOSITORY/`. Its directory root
and `index.html` display the same page; `resume.pdf` opens the complete document.
No additional secret or personal access token is needed. The deployment job uses
the built-in token with `pages: write`, `id-token: write`, `actions: read`, and
`contents: read`, and targets the `github-pages` environment. In **Settings >
Environments > github-pages > Deployment branches and tags**, select **Selected
branches and tags** and add both rules:

| Type | Name pattern | Purpose |
| --- | --- | --- |
| Branch | `main` | Branch pushes, monthly captures, and manual main runs |
| Tag | `v*` | Versioned releases after their signed PDF is committed to main |

Use the matching tag pattern if your fork names releases differently. GitHub
checks the triggering workflow's ref, even when a tag job checks out an accepted
commit on `main`. A branch rule named `v*` does not authorize tags. See
[GitHub's environment rules](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments#deployment-branches-and-tags)
and
[GitHub's custom workflow setup](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

## Custom domain

For `https://resume.tiger-lily-plants.com/` from `astrivant/resumeme`:

1. In the fork's **Settings > Pages > Custom domain**, save
   `resume.tiger-lily-plants.com`.
2. At the DNS provider for `tiger-lily-plants.com`, set a **CNAME** record named
   `resume` targeting **`astrivant.github.io`**. Use the publishing repository
   owner's Pages hostname when adapting these instructions. The target does not
   include a repository name or `https://`. Replace existing A records for
   `resume` with this CNAME; GitHub's subdomain validation rejects that A-record
   setup even when those addresses point to GitHub. Leave the parent domain's
   records unchanged.
3. Set the configuration below, push it, and select **Enforce HTTPS** in Pages
   settings once GitHub makes the certificate available.

   ```yaml
   publishing:
     pages:
       enabled: true
       path: /
       custom_domain: resume.tiger-lily-plants.com
   ```

The resulting URLs are `https://resume.tiger-lily-plants.com/`,
`https://resume.tiger-lily-plants.com/index.html`, and
`https://resume.tiger-lily-plants.com/resume.pdf`.
The root displays the PDF inside `index.html`; `/resume.pdf` serves the actual
PDF file. Selecting **GitHub Actions** as the Pages source is required for this
project's generated viewer. Publishing directly from the repository branch would
serve repository content instead of the generated site artifact.

`custom_domain` checks that GitHub's configured hostname matches your expectation;
it does not configure DNS or change repository settings. Keep it `null` to use
whatever hostname GitHub Pages has configured. Actions deployments ignore a
repository `CNAME` file, so this workflow does not generate one. GitHub documents
domain verification, DNS propagation, and certificate setup in its
[custom domain guide](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site).

## Publication paths

`publishing.pages.path` is relative to the Pages site's base URL, with leading and trailing
slashes. Use ordinary URL directory names; traversal, query strings, and fragments
are rejected. GitHub supplies the repository prefix on project sites.

| Pages base URL | `publishing.pages.path` | Visitor URL |
| --- | --- | --- |
| `https://resume.example.com` | `/` | `https://resume.example.com/` |
| `https://resume.example.com` | `/cv/` | `https://resume.example.com/cv/` |
| `https://person.github.io/resume` | `/` | `https://person.github.io/resume/` |
| `https://person.github.io/resume` | `/career/cv/` | `https://person.github.io/resume/career/cv/` |

The public PDF is always named `resume.pdf` beside `index.html`, even when the
repository uses another `document.output.pdf` path. Relative links work at either the
directory URL or its explicit `index.html` URL.

This artifact owns the repository's whole Pages site. Each deployment replaces
the previous site; changing `path` removes the old location. To share a larger
website, combine the generated files with that site's artifact before deployment,
or host this fork as a separate Pages site with its own subdomain.

## Updates and recovery

Main-branch pushes, monthly captures, manual main runs, and tagged releases
update Pages after their accepted PDF is committed to `main`. Tags publish the
same signed PDF attached to the release. The pipeline passes the publication
commit directly to the Pages stage; it does not depend on a second workflow
being triggered by the bot commit. Queued deployments check that `main` still
names that accepted commit before proceeding. Superseded runs skip the older site.

Pull requests and other branches do not deploy the site. The site's **Signed releases**
link leads to release verification artifacts. Pages does not publish raw profile
JSON, browser state, or the employer-specific PDFs under `single-origin/`.

If Pages setup, domain validation, or deployment fails, the PDF commit remains
available and the existing live site stays at its last successful deployment.
If GitHub reports `Tag "v..." is not allowed to deploy to github-pages`, add the
tag rule above. This rejection happens before any job step runs, so retries
cannot fix it until the environment rule changes. Rerun only the failed **Update
GitHub Pages** job to reuse its prepared artifact; no LinkedIn capture or release
rebuild is required while that artifact is retained and its accepted commit is
still current. For example:

```bash
gh run rerun RUN_ID --job FAILED_PAGES_JOB_ID
```

For other errors, fix the indicated setting and rerun the failed job, or trigger
a new main run if `main` has advanced. Setting `publishing.pages.enabled: false` stops
updates; unpublishing an already-live site is a separate operation in GitHub
Pages settings.

## Local preview

Generate from the existing PDF without capture, compilation, network requests,
or a Pages deployment:

```bash
poetry run resumeme site
python3 -m http.server 8000 --bind 127.0.0.1 --directory .cache/pages
```

Open `http://127.0.0.1:8000/`, or append the configured `publishing.pages.path`. `resumeme site`
prints the generated index path and works while CI publication is disabled.
It reads `GITHUB_REPOSITORY` in CI and the local Git origin otherwise; override
the release-link repository with `--repository OWNER/REPO` when previewing a fork.
The command replaces only its generated `.cache/pages` directory. Stop the
preview server with Ctrl+C.
