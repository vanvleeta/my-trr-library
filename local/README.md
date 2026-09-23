# Instance-specific content

Everything in this directory belongs to **this deployment** of the TRR library
template. The template itself ships nothing here except this file and
`config.example.json`.

That is the invariant the design rests on: because upstream never places content
under `local/`, pulling template updates can never conflict with anything you
own.

## Setting up

Copy the example configuration and edit it:

```bash
cp local/config.example.json local/config.json
```

`config.json` holds this repository's ID prefix, its platform map, and its
tactic vocabulary. The example ships `id_prefix` as `XXXX`, which every tool
rejects, so an unconfigured instance fails loudly rather than quietly
publishing reports under a placeholder identifier.

See [../docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md) for the full setup.

## What does not go here

Core tooling, workflows, schemas, and the documentation examples. If you find
yourself wanting to change one of those, consider whether the change belongs
upstream instead: a fix made in the template reaches every deployment, while a
local edit to a core file is exactly the merge conflict this directory exists
to prevent.
