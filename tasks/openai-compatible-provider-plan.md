# OpenAI-compatible Provider Profile plan

1. Freeze the JSON contract and add model-free validation/abuse tests.
2. Implement a validation-only slice in the PowerShell entrypoint.
3. Add bounded CoPaw configuration with opt-in connection testing.
4. Add a secret-free example Profile and deployment documentation.
5. Run focused and full local gates, review security, and update durable state.

Risks: SSRF through endpoint configuration, secret disclosure, unintended paid
calls, and provider/model capability mismatch. Mitigations are administrator-only
Profiles, HTTPS/public-host validation, environment-only secrets, opt-in probes,
and mandatory post-switch AgentTeams E2E before claiming compatibility.
