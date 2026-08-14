# Task evidence and ExperienceRecord binding plan

1. Add failing contract tests for task/stage/producer binding, evidence closure,
   and SUCCEEDED/FAILED/UNCERTAIN ExperienceRecord invariants.
2. Add the minimal additive contracts without changing the existing generic
   detection pipeline interface.
3. Add failing main-task tests for real L1/L2/L3 artifacts and role separation.
4. Extend the deterministic repair runner with an Implementer-side dynamic run,
   three task-bound DetectionResults, and a final ExperienceRecord/bundle.
5. Execute the main case, inspect/hash the strict bundle, run full gates, and
   update the design checklist only for directly proven behavior.
