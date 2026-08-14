# Release readiness and wheel smoke plan

1. Audit version sources, build tooling, CI, changelog, tags, and release notes.
2. Add the bounded build dependency and isolated wheel smoke gate to CI.
3. Align the Unreleased changelog and write an explicitly unshipped RC.2 draft.
4. Build sdist/wheel locally and verify isolated installation, version, CLI, and
   artifact contents.
5. Run repository gates, review the change, and record durable evidence.
