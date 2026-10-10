# PolyMigrate

PolyMigrate is an early-stage, provider-agnostic foundation for autonomous cross-language software migration. Its design combines a spec-driven workflow, extensible language metadata, AI provider interfaces, reusable migration knowledge, Graphify integration points, skills, and evidence-based validation.

## Current status

**Foundation / planning milestone.** The current CLI inventories a source project and produces a migration plan. It does not yet translate or refactor source code end-to-end. Do not use it as a production migration tool.

Implemented in this foundation:
- Language registry for Python, Go, JavaScript, TypeScript, Java, Rust, C#, C/C++, Kotlin, Ruby, PHP, and Swift.
- Deterministic project inventory and output-path safety checks.
- Provider-neutral capability registry and HTTP adapters for OpenAI-compatible Chat Completions, Anthropic Messages, and Gemini generateContent.
- Bounded agent runtime with JSON action validation and allowlisted tools.
- Skill metadata registry with permission checks.
- Library replacement strategy ranking.
- Optional Graphify JSON artifact reader with degraded-mode reporting.
- SQLite migration knowledge store with fingerprints, validation status, and opt-in cross-project reuse.
- Evidence-derived final review status.
- Spec-kit documents, initial skills, and GitHub Actions CI.

The provider adapters have not yet been verified against live credentials in this repository environment. They intentionally do not advertise native tool calling. Graphify is read-only and schema-conservative; full CLI integration and incremental graph updates remain future work.

## Requirements

- Python 3.11 or newer.
- No third-party runtime dependency is required for the current planning path.
- Live AI use requires credentials for the chosen provider; no credentials are committed.
- Install the project in editable mode to use the polymigrate command.

## Quick start

Create a virtual environment, install the project, then run:

    python -m venv .venv
    source .venv/bin/activate
    python -m pip install -e .
    polymigrate plan --source ./my-project --from python --to go --output ./migration-output

The command creates migration-plan.json in the output directory. It does not modify source files and does not claim that code has been migrated.

## Development and tests

    python -m compileall -q src tests
    PYTHONPATH=src python -m unittest discover -s tests -v

The CI workflow runs compilation and unit/integration/E2E contract tests across Python 3.11, 3.12, and 3.13.

## Architecture

- src/polymigrate/languages.py: language metadata registry.
- src/polymigrate/planner.py: deterministic planning and source inventory.
- src/polymigrate/ai/: provider protocols, capability registry, and HTTP adapters.
- src/polymigrate/agent/: bounded decision loop and tool allowlist.
- src/polymigrate/skills/: validated skill metadata.
- src/polymigrate/graph/: optional Graphify artifact adapter.
- src/polymigrate/migration/: library replacement strategy ranking.
- src/polymigrate/knowledge.py: persistent evidence-gated knowledge store.
- src/polymigrate/reporting.py: final status derivation.
- specs/001-foundation/: feature spec, plan, and tasks.
- skills/: initial migration skill packages.

## Security and correctness

Migration work must use an isolated workspace, preserve source input, validate generated output, and report unresolved issues rather than claiming success without evidence. Treat source files, skills, package metadata, and model output as untrusted data. Never place API keys in prompts, logs, or reusable knowledge. Cross-project knowledge reuse is opt-in and only verified records are eligible.

## Roadmap

1. Verify provider contracts and Graphify integration against supported versions.
2. Add source/target parser and generator adapters.
3. Implement the autonomous transformation and dependency-reconstruction engine.
4. Add sandboxed build/test execution and bounded automated repair.
5. Add differential behavior testing and multi-language E2E fixtures.
6. Expand skills and reusable migration patterns based on verified evidence.

## License

MIT. See LICENSE.
