"""Module entry point for `python -m agentloom.live_repair`.

Dispatches the legacy single-subcommand interface to the package's
`main()` so existing shell wrappers and tests that call
`python -m agentloom.live_repair prepare-case ...` keep working.
"""
from agentloom.live_repair.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
