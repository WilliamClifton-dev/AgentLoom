# Sandboxed pytest Tool Provider plan

1. Freeze the SandboxProvider request/result contracts and abuse cases.
2. Implement deterministic bounded workspace hashing.
3. Implement a pinned, no-network, read-only Docker SandboxProvider.
4. Wrap it with the governed pytest ToolProvider and Evidence output.
5. Make Policy Broker deployment select Docker without host fallback.
6. Build the hashed runner image and run a real model-free isolation proof.
7. Run full quality/security gates and record Task 15 evidence.
