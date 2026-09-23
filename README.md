# Technique Research Report (TRR) Library Template

> This is the TIRED Labs records library template. Deployed libraries — the
> public TRR library and any private library an organization runs — are
> instances of this repository.

## Overview

This repository is the template for a Technique Research Report (TRR) library:
a collection of reports documenting attack technique research and modeling, for
use in understanding, emulating, and detecting cyber attacks. It contains the
tooling, workflows, documentation, and report templates that a library needs,
but no reports of its own.

For more information on TRRs, see the [TRR Guide]. To read about the
initiative's goals, see the [Project Overview]. Questions about the project? See
the [FAQ].

## Deploying your own library

Any organization can run its own library, public or private, and keep its
research entirely under its own control. Reports are identified with a prefix
you choose, so a private library and the public one can be read side by side
without their identifiers colliding — and neither repository needs to know the
other exists.

To stand one up, follow the [Deployment Guide]. To understand how the pieces fit
together first, read the [Repository Design].

## Contributing to a library

If you want to write a report rather than deploy a library, follow the
[Contribution Guide]. Note that reports are contributed to a deployed library,
not to this template.

## Where this fits

TRR libraries hold technique research. Coverage libraries, deployed from their
own template, hold the Coverage Records that track what an organization actually
detects. Insomnia reads any number of both repos and joins them into a single
searchable view with coverage mapping. See [Repository Design] for the full
picture.

[Contribution Guide]: ./docs/CONTRIBUTING.md
[Deployment Guide]: ./docs/DEPLOYMENT.md
[Repository Design]: ./docs/DESIGN.md
[TRR Guide]: ./docs/TECHNIQUE-RESEARCH-REPORT.md
[Project Overview]: ./docs/PROJECT-OVERVIEW.md
[FAQ]: ./docs/FAQ.md
