# Repository Design

This document explains how a TRR library repository is put together: how it is
configured, how reports are identified and validated, how automation works, and
how an organization stands up its own instance. If you only want to write a
report, read the [Contribution Guide] instead — this is for people deploying or
maintaining a library.

## Where this repo fits

The TIRED Labs ecosystem separates *research* from *coverage* from
*presentation*, and each lives in its own place:

- **TRR libraries** (this repository) hold Technique Research Reports: how an
  attack technique works, the procedures that make it up, and the detection
  data models that describe the evidence it leaves behind. A TRR describes the
  technique itself and says nothing about any particular organization's
  detections.
- **Coverage libraries** hold Procedure Coverage Records (PCRs), which track
  what a given organization actually detects. Coverage is organization-specific
  and lives in its own repository, deployed from its own template.
- **Insomnia** is the dashboard. It reads one or more TRR libraries and one or
  more coverage libraries, joins them, and produces a unified view — searchable
  research, matrix views, and coverage mapping across every configured source.

The separation matters for a practical reason: research is shareable, coverage
usually is not. Keeping them apart lets an organization consume public research
while keeping its detection posture entirely private.

### Repositories do not know about each other

Every library repository is self-contained. It has no awareness of any other
library, holds no links to one, and needs no coordination with one. A repository
produces a well-formed `index.json` describing its own contents, and that is the
whole of its obligation.

Unification happens in Insomnia, which is configured with the list of
repositories to read. Repository name, base URL, and visibility are Insomnia
configuration, not repository configuration — the repository does not know how
it will be displayed or who else is being displayed alongside it. This is what
allows a private instance to sit behind a firewall and still appear in the same
dashboard as the public library.

## Template and instance model

This repository is a **template**. The public TRR library is an instance of it,
and so is every private library an organization deploys. The template holds the
tooling, workflows, documentation, and examples; an instance holds all of that
plus its own reports and configuration.

Tooling is **copied into** each instance rather than referenced from a shared
location. This is deliberate. Many organizations restrict which GitHub Actions
may run, and any design that reaches out to a central tooling repository at
workflow run time will fail in those environments. A self-contained instance
runs anywhere.

The cost of copying is that instances must pull updates when tooling changes,
which is what the `upstream` remote is for. See [Keeping an instance current].

## Repository configuration

All repository-specific parameters live in a single file at the repository root,
`local/config.json`:

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
    }
  }
}
```

| Key         | Required | Purpose                                          |
|-------------|----------|--------------------------------------------------|
| `schema`    | Yes      | Config format version, for forward compatibility |
| `id_prefix` | Yes      | Identifier prefix for reports in this repository |
| `platforms` | Yes      | Map of platform display name to folder short code|
| `tactics`   | No       | Permitted tactic vocabulary; unset disables the check |

The template ships with `id_prefix` set to `XXXX`, which every tool rejects with
an explicit error. An unconfigured instance therefore fails loudly on its first
workflow run rather than quietly publishing reports under a placeholder
identifier.

Organizations extend `platforms` freely. A private library covering internal
systems can add entries that will never exist upstream, and because platform
data lives in the instance's own config rather than a shared file, those
additions survive upstream merges cleanly.

## Report identifiers

Reports are identified as `<PREFIX><NNNN>` — `TRR0034` in the public library,
`ACME0034` in an instance configured with `id_prefix: "ACME"`. Folder names use
the lowercase form. Because the prefix is what distinguishes one library's
reports from another's, Insomnia can display reports from many sources without
ambiguity, and it infers each library's prefix from the identifiers it finds.

Prefixes should be unique across the libraries an organization consumes. Nothing
enforces this globally — it cannot be enforced across independent repositories —
but Insomnia flags collisions between configured sources.

### The `trr0000` placeholder

Newly written reports always use `trr0000`, in every instance regardless of
prefix. Identifiers are scarce and must not be claimed before a report is
accepted, so assignment happens at merge time: the automation renames the folder
and rewrites its contents to the next available identifier *and* the
repository's configured prefix in one step. A contributor never picks a number,
and two contributors working simultaneously never collide.

This is also why the placeholder is uniform. Contribution documentation and
report templates say `trr0000` in every deployment, so instances inherit them
from upstream without modification.

## Repository layout

```text
root
|_ local/config.json          repository parameters
|_ index.json               generated report index
|_ reports/
|  \_ <prefix><nnnn>/
|     \_ <platform>/
|        |_ images/
|        |_ ddms/
|        \_ README.md       the report itself
|_ .tiredize/
|  |_ schema.yaml           expected section structure
|  |_ rules.yaml            style rules, run on pull requests
|  |_ rules-links.yaml      link checking, run weekly
|  \_ requirements.txt      pinned Tiredize version
|_ docs/
|  |_ examples/             report templates and worked examples
|  \_ ...                   guides
\_ tools/                   indexer, validator, assignment scripts
```

Reports live under `reports/`. Everything in `docs/examples/` is documentation
rather than published research: those files keep the `trr` prefix permanently,
in every instance, because they are part of the template.

## The index

`index.json` is a flat array of report entries, generated from the reports
themselves and committed to the repository. It is the only file Insomnia reads,
and it is what makes a library consumable without cloning it.

Each entry carries the report's name, identifier, tactics, contributors,
external framework identifiers, platforms, procedures, available emulation
tests, publication date, and last update date. The array is deliberately plain —
no envelope, no repository metadata — so that a library remains a drop-in source
for any consumer that already understands the format.

The index is regenerated automatically when reports are merged. It should not be
edited by hand.

## Validation

Two independent checks run against every report, and they answer different
questions.

**Structural validation** asks whether the document is well-formed: correct
headings in the correct order, required tables present with the right columns,
formatting and line-length conventions observed. This is handled by [Tiredize],
a schema-driven markdown linter installed as a Python package and configured by
two files the repository owns: `.tiredize/schema.yaml` for section structure and
`.tiredize/rules.yaml` for style. Tiredize knows nothing about TRRs
specifically -- it enforces whatever definition it is given.

**Semantic validation** asks whether the content is legal for *this* repository,
which requires knowledge a generic linter does not have. It runs as a mode of
the indexer, reusing the same parser that builds the index so the two can never
disagree about what a report says. Run it against named files or, with no
arguments, against every report in the repository — which is how an existing
corpus gets rechecked after validation rules change. It checks that:

- The identifier matches the configured prefix, or is the `trr0000` placeholder
- The identifier agrees with the folder the report lives in
- The platform folder is a known short code, the metadata platform names are
  known display names, and the two agree with each other
- Procedure identifiers are well-formed, unique, and unbroken
- Emulation test rows refer to procedures that exist
- Every procedure has a Detection Data Model subsection
- Referenced images and detection data model files are present on disk
- No other report already claims this identifier and platform
- Tactics fall within the configured vocabulary, when one is defined

A report that is structurally perfect can still fail semantic validation — for
example, by naming a platform this library does not recognize.

### The index envelope

`index.json` is a document, not a bare array:

```json
{
  "schema": 2,
  "generated": "2026-09-22T14:03:00Z",
  "platforms": { "Active Directory": "ad", "Windows": "win" },
  "records": [ ... ]
}
```

`schema` lets a consumer decide whether it understands the file rather than
inferring that from its shape. `generated` is when the index was last written,
so a dashboard can show real freshness instead of the time it happened to
fetch. `platforms` is copied verbatim from the repository configuration, which
means a consumer can resolve a report's platform short code without fetching
anything else -- and because validation rejects a report naming an
unconfigured platform, every platform appearing in `records` is guaranteed to
be in the map.

The indexer still reads a bare array, so a repository written by an earlier
version reindexes without a migration step.

## Automation

Three workflows do the work.

**On pull request**, the report is linted, semantically validated, and run
through the indexer in test mode to confirm it will index cleanly after merge.
Nothing is written.

**On any push to `main`**, any new report is assigned its identifier, its folder
and files are renamed, the index is regenerated, and the result is committed
back to `main`.

The push itself is the trigger, rather than a pull request closing. GitHub does
not reliably queue the merge commit job for closed pull requests, and a merge
that bypasses branch protection can leave a pull-request-triggered workflow
unfired even though `main` did receive the commits. A push always fires, however
the change arrived. Since the job's purpose is "`main` changed, reindex it",
that is also the more accurate description of when it should run.

Two consequences follow. The job runs one at a time (`concurrency`), because two
reports merged close together would otherwise read the same index and be
assigned the same identifier. And its own commit is tagged `[skip ci]` and
skipped on the next run, because a GitHub App token — unlike the token GitHub
issues to a workflow — does trigger workflows, so the reindexing push would
otherwise re-trigger the job.

**Weekly**, external links in reports are checked and a single tracking issue is
kept up to date with any that fail. This is deliberately not a pull request
check: link rot is a maintenance concern, and a contribution should not fail
because a third-party site was down that morning.

### Third-party actions

The workflows use only GitHub-owned actions. Changed-file detection is done with
`git diff` in a run step rather than a third-party action, because organizations
that restrict runnable actions commonly permit the `actions/*` namespace and
little else. Instances in restricted environments should be able to run the
workflows unmodified.

### Pushing to a protected branch

The merge workflow writes to `main`, which is normally protected by rules
requiring review and passing checks. The token GitHub issues to a workflow
cannot bypass those rules, and the identity behind it cannot be added to a
bypass list — GitHub does not treat it as a bypassable actor. A GitHub App can
be, which is why the workflow authenticates as one.

Each instance therefore needs its own GitHub App, installed on the repository
and added to the branch protection bypass list, with its credentials stored as
repository secrets. Step-by-step setup is in the [Deployment Guide].

## Contribution lifecycle

1. A contributor copies the report template into `reports/trr0000/<platform>/`
   and writes the report.
2. They open a pull request. Structural linting, semantic validation, and an
   indexing dry run all execute.
3. Maintainers review. Failures are the contributor's to fix.
4. On merge, automation assigns the identifier, renames files and folders,
   regenerates the index, and commits to `main`.
5. Insomnia picks up the new report the next time it reads the index.

## Creating an instance

An instance is created by cloning the template and pushing it to a new
repository, rather than through GitHub's "Use this template" button. The button
produces a repository with no shared history, which permanently forecloses the
update path described below. The fork button is also unsuitable when the
instance must be private, since a fork of a public repository cannot be made
private.

The full procedure, including configuration and GitHub App setup, is in the
[Deployment Guide]. In outline:

1. Clone the template and push it to the new repository, retaining `upstream`.
2. Set `id_prefix` in `local/config.json` and adjust
   `platforms` and `core_fields` as needed.
3. Create and install the GitHub App; store its credentials as secrets.
4. Configure branch protection and add the App to the bypass list.
5. Replace the root `README.md` with your library's own description.

An instance that will not host public research can delete `reports/` entirely
and start from an empty index.

## Keeping an instance current

Because tooling is copied rather than shared, improvements to the linter schema,
the indexer, the validator, or the workflows reach an instance only when it
merges from upstream:

```bash
git fetch upstream
git merge upstream/main
```

Conflicts are confined to the small set of files an instance owns — chiefly
`local/config.json`, `README.md`, and `index.json`. Reports never conflict,
because upstream does not contain them.

Instances are encouraged to merge upstream periodically rather than only when
something breaks. Validation rules gain checks over time, and a long-unmerged
instance will accumulate reports that would not pass current rules.

[Contribution Guide]: ./CONTRIBUTING.md
[Deployment Guide]: ./DEPLOYMENT.md
[Keeping an instance current]: #keeping-an-instance-current
[Tiredize]: https://github.com/tired-labs/tiredize
