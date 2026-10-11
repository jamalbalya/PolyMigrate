# Behavior Preservation Skill

1. Derive contracts from tests, API schemas, documentation, and observable source behavior.
2. Cover normal input, boundaries, invalid input, errors, ordering, numeric precision, side effects, and concurrency where relevant.
3. Run the same test vectors against source and target when practical.
4. Record differences and distinguish confirmed facts from assumptions.
5. Do not change expected results or remove tests merely to obtain a green build.
6. Mark the migration PARTIAL or BLOCKED when required behavior cannot be verified.
