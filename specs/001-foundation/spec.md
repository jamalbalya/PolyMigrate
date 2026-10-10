# Feature Specification: PolyMigrate Foundation

**Status:** Foundation baseline

## Problem
Cross-language migration requires more than syntax translation. The platform must understand projects, choose target strategies, handle missing library equivalents, use AI providers and skills, leverage code graphs, validate behavior, recover from defects, and report evidence honestly.

## Goals
- Establish provider-neutral interfaces for language adapters, AI providers, skills, graph intelligence, and validation.
- Generate a deterministic migration plan from source/target inputs.
- Rank library-gap strategies: target standard library, compatible package, composite adapter, custom implementation, or architectural alternative.
- Keep output separate from source.
- Record decisions and validation evidence.
- Support optional Graphify and opt-in reusable migration knowledge.

## Non-goals for this milestone
- Claiming every language/framework pair is supported.
- Production deployment or production data mutation.
- Treating generated code as safe without isolation.
- Guaranteeing equivalence when source behavior cannot be observed or specified.
- Claiming native tool calling for providers that do not advertise it.

## User stories and acceptance criteria

### US1 — Plan a migration
- Valid inputs produce a deterministic plan and inventory.
- Invalid language IDs and missing source directories return actionable errors.
- Output and plan JSON must remain outside the source tree.

### US2 — Select AI providers
- Provider registration is independent of orchestration.
- Providers declare capabilities.
- Unsupported capability requests fail explicitly.
- Tests use deterministic fakes without network calls.

### US3 — Load skills
- Skills declare ID, version, description, contracts, and allowed tools.
- Duplicate IDs, malformed metadata, and unapproved tools are rejected.
- Skill text cannot grant permissions.

### US4 — Resolve library gaps
- Candidate strategies are ranked by capability, compatibility, maintenance/security evidence, and implementation cost.
- Custom implementations and architecture changes are considered when direct replacements are unsuitable.
- Unverified recommendations are never represented as proven equivalents.

### US5 — Use Graphify
- Graphify is optional and behind an adapter.
- Missing or malformed artifacts produce a warning and degraded planning, not a false success.
- Reuse must respect fingerprints and tool versions.

### US6 — Final review
- SUCCESS requires every mandatory gate to pass.
- Failed mandatory gates produce PARTIAL or BLOCKED.
- Reports distinguish facts, inferred decisions, and unverified assumptions.

## Functional requirements
- FR-001: CLI supports deterministic planning and an explicitly experimental per-file AI translation command. The translation command requires an explicit source-upload opt-in and must report all unrun validation gates as NOT_RUN.
- FR-002: Language registry is extensible and validates canonical IDs.
- FR-003: Provider registry checks structured-output and tool-calling capabilities.
- FR-004: Skill registry validates metadata and tool permissions.
- FR-005: Library-gap strategy ranking and bounded, allowlisted agent tools are available.
- FR-006: Graphify integration is optional and fault-tolerant.
- FR-007: Generated changes are isolated from source.
- FR-008: Execution budgets, retry limits, and audit logs are required before autonomous migration ships.
- FR-009: Final status is evidence-derived: SUCCESS, PARTIAL, or BLOCKED.
- FR-010: Secrets must not enter prompts, logs, or reusable knowledge.
- FR-011: Knowledge is fingerprinted; only verified records are reusable and cross-project reuse is opt-in.

## Quality requirements
- Core planning works offline without AI credentials.
- Unit tests cover registries, ranking, validation, and status derivation.
- Integration tests cover CLI and degraded Graphify/provider paths.
- E2E tests use a temporary fixture project.
- CI runs tests on supported Python versions.
- Project content is not sent to an AI provider unless configured.
- Model output and skills are untrusted; tool execution is allowlisted.

## Acceptance gate
Accept the foundation only when implemented criteria have tests, local results are recorded, CLI smoke tests pass, CI is configured, and unsupported capabilities are explicitly documented.
