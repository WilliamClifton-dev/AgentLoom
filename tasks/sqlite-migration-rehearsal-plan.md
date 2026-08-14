# SQLite migration rehearsal plan

1. Write failing integration tests for the revision cycle, evidence shape, empty
   output requirement, and CLI result.
2. Implement the smallest migration rehearsal service and JSON evidence writer.
3. Add a thin Typer command with an ignored default output location.
4. Run the focused tests and a real CLI rehearsal; inspect the evidence.
5. Run full gates, review, and update durable/design completion state.
