# Implementation Plan: Foundation

## Architecture
- Python 3.11+ core and CLI.
- Typed domain models and extensible language registry.
- Provider-neutral AI protocol and capability-aware registry.
- Skills registry with strict tool allowlist.
- Graphify adapter that degrades safely when graph artifacts are absent or malformed.
- Deterministic library strategy ranking.
- SQLite knowledge store with fingerprints, evidence, project scope, and explicit cross-project sharing.
- Bounded agent runtime that accepts only validated JSON actions and allowlisted tools.
- Evidence-derived final review status.
- CI across supported Python versions.

## Data flow
1. Validate source, target, and output paths.
2. Inventory source files and inspect optional graph artifacts.
3. Produce a plan with warnings, unresolved items, and validation gates.
4. For future execution, use the provider/skill/graph layers to propose a migration strategy.
5. Execute only registered actions in an isolated workspace.
6. Run build, tests, behavior comparison, and security gates.
7. Persist only eligible knowledge and produce the final review.

## Security considerations
- Provider errors must not echo request bodies or credentials.
- Skills cannot expand the platform allowlist.
- Tool results must be bounded and JSON serializable.
- No arbitrary shell tool is enabled by default.
- Knowledge sharing is opt-in.
- Output path must not overwrite source.

## Validation
- Unit tests: language registry, strategy ranking, knowledge reuse rules, provider capabilities, skills, reporting.
- Integration tests: CLI to planner, invalid path handling, degraded Graphify.
- E2E tests: temporary source project to deterministic plan.
- CI: compile and test matrix for Python 3.11, 3.12, and 3.13.

## Limitations
This foundation plans migrations and provides reusable infrastructure; it does not yet perform general-purpose end-to-end code migration. Live provider calls and Graphify CLI/schema compatibility require environment-specific verification.
