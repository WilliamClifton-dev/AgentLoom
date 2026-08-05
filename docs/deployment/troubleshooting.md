# Deployment troubleshooting

Run the health check first:

```powershell
.\scripts\health-check.ps1
Get-Content -Raw .\artifacts\agentteams\health.json
```

The `failureCode` identifies the failed layer.

| Code | Meaning | Action |
| --- | --- | --- |
| `docker-cli` | Docker CLI is unavailable | Install Docker Desktop and reopen PowerShell |
| `docker-daemon` | Docker Desktop is stopped or unhealthy | Start Docker Desktop and wait for the engine |
| `controller` | `hiclaw-controller` is absent, stopped, or not pinned | Reinstall/start AgentTeams v1.1.2 |
| `images` | A locked image is missing or has the wrong digest | Pull the pinned image and investigate unexpected replacement |
| `resources` | HiClaw cannot return AgentLoom resources | Inspect `docker logs hiclaw-controller`, then rerun Full bootstrap |

## Human disappears from the Team Room

AgentTeams `v1.1.2` can report an existing Team as configured while silently
dropping `spec.humanMembers` during update. Do not keep repairing Matrix room
membership manually: rerun `deploy\agentteams\deploy.ps1`. AgentLoom applies a
version-scoped Kubernetes merge patch and verifies the persisted Team spec. If
that step fails, preserve the error and controller logs; do not bypass it, or the
Team controller can remove the Human again.

## Python version rejected

AgentLoom requires exactly Python 3.12. Check it with `py -3.12 --version`. When
multiple installations exist, pass the executable explicitly:

```powershell
.\scripts\bootstrap.ps1 -Profile lite -PythonExecutable C:\Python312\python.exe
```

## Model configuration fails

Confirm only the variable name and never print its value:

```powershell
[bool][Environment]::GetEnvironmentVariable("DEEPSEEK_API_KEY", "Process")
```

The result should be `True`. A configured key can still fail because of quota,
account model access, network restrictions, or an invalid endpoint. The bounded
provider scripts do not accept arbitrary endpoints.

## Port or login problems

Check the controller and published ports:

```powershell
docker ps --filter name=hiclaw
docker port hiclaw-controller
```

The local Element endpoint is normally `http://127.0.0.1:18088/#/login`. Never
put its credential in an issue, log bundle, repository, or screenshot.
