# Agent Tool Policy Gateway Tasks

- [x] Write the product specification.
- [x] Write the implementation plan.
- [ ] Confirm the first non-AgentTeams client.
- [ ] Confirm whether `SkillExecutionGrant` remains the public Grant name.
- [x] Fix the existing repository quality blockers before the first gateway code change:
  - [x] full-repository Ruff errors in `scripts/dev/historical-splits/` (historical scripts excluded; runtime and tests remain linted);
  - [x] CI `test-results.txt` local/CI snapshot mismatch (Lite and Docker Full snapshots are separate);
  - [x] inconsistent release and second-host documentation.
- [ ] Extract transport-neutral policy interfaces.
- [ ] Add a standalone local MCP Gateway profile.
- [ ] Prove one allowed sandbox call and five denied calls.
- [ ] Move AgentTeams identity mapping behind an adapter.
- [ ] Publish a short standalone Gateway quickstart.
- [ ] Run three external user trials before expanding the provider surface.
