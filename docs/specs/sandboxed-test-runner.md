# Spec: Sandboxed pytest Tool Provider

## Objective

Move untrusted pytest execution out of the Policy Broker host process into a
fresh, short-lived Docker sandbox. AgentTeams Workers continue to authenticate
through Higress and request governed tool calls; they do not receive Docker
access, Broker secrets, model credentials, or a writable host workspace.

## Threat model

Untrusted tests may try to read process credentials, modify the approved
snapshot, traverse paths, access the host or network, fork indefinitely, exhaust
memory, produce unbounded output, or survive after the request. Assets are the
Policy Broker signing key, gateway assertion, model/API credentials, Matrix
identity, host filesystem, Docker daemon, immutable task snapshot, and Evidence.

The Docker daemon remains a privileged trusted dependency controlled only by
the Policy Broker host. Agent- or task-controlled input never selects the image,
mounts, Docker flags, environment variables, or container name.

## Contract

`SandboxProvider` accepts `agentloom.sandbox-execution/v1alpha1` and returns
`agentloom.sandbox-result/v1alpha1`. The request binds:

- server-generated execution ID;
- trusted snapshot URI and expected SHA-256 tree digest;
- normalized Python/pytest argument array;
- normalized relative working directory;
- timeout and combined output limit.

The governed tool parameters require `workspaceDigest`. Because
`ToolExecutionRequest.parameterDigest` covers the complete parameters object,
the signed Grant is bound to the expected snapshot. The Provider recomputes the
tree digest before authorization and immediately before and after execution.

## Runtime controls

- Image reference is trusted deployment configuration and must be an immutable
  image ID or repository digest.
- `docker run --pull never --rm` creates a uniquely named container per call.
- Network is `none`; root filesystem and workspace bind mount are read-only.
- Runtime user is `65534:65534`; all Linux capabilities are dropped;
  `no-new-privileges` and the default seccomp profile remain active.
- CPU, memory, PID, file-descriptor, core-dump, timeout, output, and `/tmp`
  limits are fixed by trusted code.
- Only non-secret Python/pytest environment settings are passed explicitly.
- Timeout, output overflow, Docker failure, cleanup failure, snapshot mismatch,
  or snapshot drift fails closed and never invokes the host runner.

## Deployment boundary

Production Policy Broker tool configuration requires
`AGENTLOOM_SANDBOX_BACKEND=docker` and `AGENTLOOM_SANDBOX_IMAGE=<immutable-ref>`.
The legacy `LocalTestRunnerProvider` remains available only through the explicit
`local-development` backend plus a separate host-execution acknowledgement. The
AgentTeams launcher always selects Docker and has no local fallback.

## Runner image

`deploy/sandbox/Dockerfile` uses the official Python 3.12.14 image by immutable
digest. Pytest and its pure-Python dependencies are pinned with wheel hashes
copied from the repository's `uv.lock`. The build script records the resulting
content-addressed image ID; runtime never pulls an image.

## Testing

- Small tests validate contracts, image references, tree hashing, command
  construction, failure mapping, cleanup, and environment composition.
- A Docker integration proof runs benign and adversarial pytest fixtures in a
  real container and proves read-only workspace, absent host secret, disabled
  network, bounded timeout/output, and container cleanup.
- All tests are model-free. No Provider API or AgentTeams model is contacted.

## Non-goals

- Giving Workers direct Docker access.
- Running untrusted code in long-lived business Worker containers.
- Supporting arbitrary images, commands, mounts, environment variables, or
  network policies supplied by an Agent.
- Claiming Docker is a VM-grade boundary. OpenSandbox remains a future
  `SandboxProvider` implementation for deployments requiring stronger isolation.
