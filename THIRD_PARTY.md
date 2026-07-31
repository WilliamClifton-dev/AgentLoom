# Third-Party Software and References

AgentLoom preserves upstream attribution. Entries marked `design-reference` did
not contribute copied source code to the current repository.

## Runtime and Content

| Project | Relationship | License | Pinned version / status |
| --- | --- | --- | --- |
| [agentscope-ai/AgentTeams](https://github.com/agentscope-ai/AgentTeams) | Mandatory runtime | Apache-2.0 | `v1.1.2`, commit `a99457830fafb99c991bdb666aa8a1eef2f83b12` |
| [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills) | Quarantined Skill source metadata; upstream content not vendored | MIT | Commit `7829ffd90d973b6325f5f12f1b1226dcace74443`; five selected paths hashed, not evaluated or published |

Python packages used by AgentLoom are declared in `pyproject.toml` and resolved
in `uv.lock`. Each package remains subject to its upstream license.

## Design References

| Project | License / status | Referenced idea |
| --- | --- | --- |
| [vercel-labs/skills](https://github.com/vercel-labs/skills) | MIT | Git Skill discovery and installation workflow |
| [invariantlabs-ai/mcp-scan](https://github.com/invariantlabs-ai/mcp-scan) | Apache-2.0 | MCP and Skill risk classification |
| [promptfoo/promptfoo](https://github.com/promptfoo/promptfoo) | MIT | Declarative evaluation matrices |
| [princeton-nlp/SWE-bench](https://github.com/princeton-nlp/SWE-bench) | Repository and dataset terms apply | Issue/patch/container verification structure |
| [vercel-labs/deepsec](https://github.com/vercel-labs/deepsec) | Apache-2.0 | Staged, resumable, independently verified execution |
| [Unclecheng-li/VulnClaw](https://github.com/Unclecheng-li/VulnClaw) | MIT | Evidence gates and role-based tool allowlists |
| [opensandbox-group/OpenSandbox](https://github.com/opensandbox-group/OpenSandbox) | Apache-2.0 | Optional stronger sandbox backend |
| [stacklok/toolhive](https://github.com/stacklok/toolhive) | Apache-2.0 | MCP identity, policy, and audit model |
| [openlit/openlit](https://github.com/openlit/openlit) | Apache-2.0 | OpenTelemetry conventions for coding agents |
| [modelcontextprotocol/registry](https://github.com/modelcontextprotocol/registry) | Repository terms apply | Tool naming, version, source, and publication model |

Design references are informational. Their names and trademarks belong to their
respective owners. Before vendoring any upstream content, AgentLoom records the
exact commit, file hash, license, and transformation in `provenance/sources.yaml`.
