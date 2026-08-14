# Tool route rollback rehearsal plan

1. Add failing integration tests for actual Provider selection, rollback digest,
   caller environment restoration, output ownership, and CLI JSON.
2. Expose the existing Policy Broker Provider factory as a documented function.
3. Implement the bounded route rehearsal and thin CLI.
4. Run two independent rehearsals and compare Evidence hashes.
5. Run full gates, review, and close the combined migration/route design item.
