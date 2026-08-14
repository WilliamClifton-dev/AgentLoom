# Release readiness and wheel smoke specification

## Purpose

Prepare the repository for a post-competition release candidate without
creating a tag, publishing a GitHub Release, changing repository visibility, or
claiming that the Human submission checkpoint is complete.

## Requirements

- The development extra includes a bounded PEP 517 build frontend.
- CI builds both an sdist and wheel after the existing test, lint, type, audit,
  and deployment-script gates.
- CI installs the wheel in a fresh virtual environment, verifies distribution
  and package version parity, imports `agentloom`, and runs `agentloom --help`.
- The Unreleased changelog reflects Tasks 11-19 and states the current Skill,
  Provider, PR, package, and Human-checkpoint boundaries.
- A release-candidate draft records the Task 17/18 evidence baseline, release
  verification commands, rollback path, and explicit publish blockers.
- Historical `v0.1.0-rc.1` documentation remains unchanged.

## Acceptance

- `python -m build` succeeds from the declared development environment.
- The generated sdist and wheel reopen and contain no credential or private
  evidence artifact.
- A fresh virtual environment can install the wheel and run the package/CLI
  smoke checks.
- Existing repository quality gates remain green.
- No tag, GitHub Release, push, repository visibility change, or paid model call
  occurs as part of this task.
