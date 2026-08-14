# Retry delay cap returns the larger value

`cap_retry_delay` should retain a requested delay below the configured maximum
and cap larger values. It currently raises a small request to the maximum.

This is a team-authored synthetic defect for the versioned AgentLoom benchmark.

