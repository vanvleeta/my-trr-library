# Deployment Guide

This guide covers standing up your own TRR library from this template, and
keeping it current afterward. If you want to understand how the repository is
put together before you deploy it, read the [Repository Design] document first.

You will need permission to create a repository and a GitHub App in your
organization, and to configure branch protection.

## 1. Create the repository

Do **not** use GitHub's "Use this template" button, and do not use the fork
button. The template button produces a repository with no shared history, which
permanently removes your ability to pull in later tooling fixes. The fork button
cannot produce a private repository from a public one.

Clone the template and push it to your own repository instead, keeping the
template configured as `upstream`:

```bash
git clone https://github.com/<template-org>/<template-repo>.git my-trr-library
cd my-trr-library

# Point 'origin' at your new (possibly private) repository
git remote rename origin upstream
git remote add origin https://github.com/<your-org>/my-trr-library.git
git push -u origin main
```

The `upstream` remote is what makes updates possible later. Do not remove it.

## 2. Configure the repository

Open `local/config.json` and set your ID prefix:

```json
{
  "schema": 1,
  "id_prefix": "ACME",
  "platforms": {
    "Active Directory": "ad",
    "Windows": "win"
  },
  "tactics": [],
  "core_fields": {
    "ID": {
      "type": "single",
      "required": true
    },
    "Tactics": {
      "type": "list",
      "required": true
    },
    "Platforms": {
      "type": "list",
      "required": true
    }
  }
}
```

**`id_prefix`** is what distinguishes your reports from every other library's.
It must be 2-8 characters, uppercase letters and digits only, starting with a
letter. Pick something short and recognizable for your organization. The
template ships with `XXXX`, which every tool rejects, so nothing will run until
you change it.

Choose a prefix no other library you consume is using. Nothing can enforce this
across independent repositories, but Insomnia will flag a collision between the
sources it is configured with. Changing a prefix later means rewriting every
report, folder, and index entry, so it is worth a few minutes of thought now.

**`platforms`** maps platform display names to the folder abbreviations used
under `reports/`.

**`core_fields`** declares the metadata every report must carry. Each entry
needs a `type` — `single` for one value, `list` for a comma-separated one —
and may set `required`, `values`, and `pattern` (both together meaning either
is acceptable). A declared field must have a row in the metadata table; an
empty value is allowed unless `required`, but a missing row is an error, which
is what catches a report drifting from the template. Add whatever your organization needs, including internal
systems that will never appear upstream. Because this lives in your own
configuration rather than a shared file, your additions survive upstream merges
without conflict.

**`tactics`** is optional. Populate it to restrict reports to a fixed tactic
vocabulary; leave it empty to accept any tactic.

## 3. Set up the GitHub App

When a pull request is merged, automation assigns the report's ID, renames its
files, regenerates the index, and pushes the result to `main`. If `main` is
protected — and it should be — that push needs an identity permitted to make it.

The token GitHub issues to a workflow cannot do this. It cannot bypass branch
protection, and the identity behind it cannot be added to a bypass list, because
GitHub does not treat it as a bypassable actor. A GitHub App can be, which is
why the workflow authenticates as one.

1. Create a GitHub App under your organization
   (**Settings → Developer settings → GitHub Apps → New GitHub App**).
   - Give it a name such as `TRR Bot`.
   - Uncheck **Webhook → Active**; the app receives no events.
   - Under **Repository permissions**, grant **Contents: Read and write**.
     Nothing else is needed.
2. Generate a private key and download the `.pem` file.
3. Install the App on your library repository
   (**Install App → your organization → Only select repositories**).
4. In your repository, add two secrets under
   **Settings → Secrets and variables → Actions**:
   - `GH_APP_ID` — the App's numeric ID, shown on its settings page
   - `GH_APP_PRIVATE_KEY` — the full contents of the `.pem` file, including
     the `BEGIN`/`END` lines

## 4. Configure branch protection

Protect `main` so that reports are reviewed before they are published, then
allow the App past that protection so the post-merge indexing commit can land.

Under **Settings → Rules → Rulesets**, create a ruleset targeting `main` that
requires a pull request before merging and requires status checks to pass. Add
a status check for `lint_and_validate` provided by GitHub Actions (this status
check is included in the core repo template). Then add your GitHub App to the
ruleset's **Bypass list**.

Without the bypass entry, everything will work until the first merge, at which
point the indexing job will fail on the push.

## 5. Install and pin Tiredize

Structural linting is done by [Tiredize], a schema-driven markdown linter. It
is a Python package rather than a GitHub Action, so it installs with `pip` and
is unaffected by any restriction your organization places on which actions may
run.

The repo template includes a Tiredize schema and ruleset that matches the report
template. Both are yours to adjust. The template ships versions that match the 
public library's conventions and the [Style Guide] so they work out of the box. If
your organization writes reports differently — an extra required section, a
different line length — this is where you say so.

### The definition files

Two files under `.tiredize/` describe what a TRR should look like:

| File               | Purpose                                                |
|--------------------|--------------------------------------------------------|
| `schema.yaml`      | Section structure: which sections, what level, order    |
| `rules.yaml`       | Style rules for pull requests: line length, whitespace  |
| `rules-links.yaml` | Link checking, run weekly rather than on pull requests  |

Note that these files deliberately do *not* cover platform names, ID prefixes,
procedure ID formats, and file references. Those are all checked by the validator
instead, because they depend on knowledge of the `local/config.json`. If you find
yourself wanting to encode repository-specific values in `schema.yaml`, that check
probably belongs in the validator.

### Testing your definition files

Change a definition file and you are changing what passes review, so test
against real reports before committing. Run Tiredize locally to test:

```bash
pip install -r .tiredize/requirements.txt

# Structure only
tiredize --markdown-schema .tiredize/schema.yaml docs/examples/trr0000/win/README.md

# Style rules only
tiredize --rules .tiredize/rules.yaml docs/examples/trr0000/win/README.md

# Both, across every report you have
tiredize --markdown-schema .tiredize/schema.yaml --rules .tiredize/rules.yaml \
  $(find reports docs/examples -name README.md)
```

Violations print as `file:line:col: [rule_id] message`, and the command exits
nonzero when anything fails, which is what makes it usable in CI and in
pre-commit hooks.

### Link checking

Link checking is split into its own rules file and its own schedule. Tiredize
enables only the rules named in a config file, so `rules-links.yaml` contains
just the `links` rule and nothing is duplicated between the two files: style
rules live in `rules.yaml` and run on every pull request, link checking lives
in `rules-links.yaml` and runs weekly.

A broken link never fails a pull request. Link rot is a maintenance problem,
and failing a contribution because a third-party site was down that morning is
a bad trade. Instead, `.github/workflows/link-check.yml` runs every Monday and
maintains a single tracking issue labelled `link-check`: it rewrites that
issue's body with the current findings, reopens it if it was closed while links
were still broken, and closes it automatically once everything resolves. One
dead link produces one issue, not one issue per week.

You can also run it by hand from the **Actions** tab, and locally:

```bash
tiredize --rules .tiredize/rules-links.yaml $(find reports -name README.md)
```

Sites that return 403 or 429 to automated requests are treated as reachable,
since there is no way to tell bot-blocking apart from a real permissions wall
and the false alarms vastly outnumber the real cases.

Transient timeouts will still produce the occasional false alarm. Re-run the
workflow from the Actions tab to confirm before editing a report.

If your organization has internal hosts a runner cannot resolve, add them to
`exclude` in `rules-links.yaml` rather than disabling the check:

```yaml
links:
  exclude:
    - "*.internal.example.com"
```

**Scheduled workflows get disabled.** GitHub turns off `schedule` triggers in
repositories with no activity for 60 days. A busy library will never notice,
but a private instance where research comes in bursts can silently stop
checking. If weekly results go quiet, check the Actions tab — re-enabling is a
single click.

### Updating Tiredize

Tiredize is pinned, so new versions reach you only when you change the pin:

```bash
# See what has changed since your pinned commit
git log --oneline <your-pinned-sha>..main

# Try the new version locally
pip install "tiredize @ git+https://github.com/tired-labs/tiredize.git@<new-sha>"

# Check it against everything before committing the new pin
tiredize --markdown-schema .tiredize/schema.yaml --rules .tiredize/rules.yaml \
  $(find reports docs/examples -name README.md)
```

Once you are satisfied, update the SHA in `.tiredize/requirements.txt` and commit
it.

Because the pin lives in your repository rather than the template's, it is
yours to control. Merging from upstream may propose a newer pin; treat that
like any other change and test before accepting it.

## 6. Check that actions are permitted

The workflows use only GitHub-owned actions (`actions/checkout`,
`actions/setup-go`, `actions/create-github-app-token`). Changed-file detection
is done with `git diff` in a run step rather than a third-party action,
specifically so that organizations restricting which actions may run can use
this template unmodified.

If your organization maintains an allowlist, confirm the `actions/*` namespace
is permitted under **Settings → Actions → General**. Tiredize needs no
allowlist entry, since it installs from PyPI-style requirements inside a run
step rather than executing as an action.

## 7. Make the repository your own

- Replace the root `README.md` with a description of your library. Keep the
  line noting that it is an instance of the template, so contributors know
  where the tooling comes from.

## 8. Verify the setup

From the repository root:

```bash
# Structural checks
tiredize --markdown-schema .tiredize/schema.yaml --rules .tiredize/rules.yaml \
  $(find reports docs/examples -name README.md)

# Semantic checks against your configuration
python3 tools/index.py validate
```

Both should pass. If the validator reports that `id_prefix` is still `XXXX`,
step 2 is incomplete.

Then open a test pull request adding a report under `reports/trr0000/`, confirm
the checks run, and merge it. You should see the report renamed to your prefix
with the next available number, and an indexing commit pushed to `main` by the
App. If that commit is rejected, revisit step 4.

The indexing job triggers on pushes to `main` rather than on the pull request
closing, so it also runs if you bypass branch protection to merge, or push to
`main` directly. It skips its own commits, which carry `[skip ci]`, and runs one
at a time so that two reports merged close together cannot be assigned the same
identifier. You can also run it by hand from the **Actions** tab, which
re-checks the most recent commit.

## Keeping your instance current

Tooling is copied into your repository rather than referenced from a shared
location, so improvements to the indexer, validator, or workflows reach
you only when you pull them in:

```bash
git fetch upstream
git merge upstream/main
```

Conflicts are limited to the few files you own — chiefly `local/config.json`,
`README.md`, and `index.json`. Your reports never conflict, because the template
does not contain any.

## Connecting to Insomnia

Insomnia is the TIRED Labs frontend that helps organize and view the reports you've
published, in addtion to performing gap analysis and coverage mapping, if you have
a coverage records repo as well.

Your instance of the TRR library publishes an `index.json` at the root of the 
repository, and that is the only file Insomnia needs. You will find instructions
on configuring Insomnia to read your TRR repo's index in the Insomnia repo.
The repository itself holds no Insomnia configuration and needs no awareness of
any other library. A private instance behind your firewall and the public
library can appear in the same dashboard without either repository knowing the
other exists.

[Repository Design]: ./DESIGN.md
[Style Guide]: ./STYLE-GUIDE.md
[Tiredize]: https://github.com/tired-labs/tiredize
[Updating Tiredize]: #updating-tiredize
