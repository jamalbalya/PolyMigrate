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
- Optional Graphify JSON artifact reader and safe CLI query adapter with degraded-mode reporting.
- SQLite migration knowledge store with fingerprints, validation status, and opt-in cross-project reuse.
- Evidence-derived final review status.
- Spec-kit documents, initial skills, and GitHub Actions CI.

The provider adapters have not yet been verified against live credentials in this repository environment. They intentionally do not advertise native tool calling. Graphify reads an existing graph and can query it through the graphify CLI; it does not build or update the graph. Live compatibility with the exact installed Graphify version and incremental graph invalidation remain to be verified.

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

Inspect provider configuration without making network requests:

    polymigrate providers

### Experimental AI file translation

The current experimental migrate command translates supported source files one file at a time. It does not yet migrate project manifests, dependencies, frameworks, tests, deployment configuration, or database schemas, and it does not run target builds or regression tests. Its output status is GENERATED_UNVERIFIED.

Configure a provider key and explicit model ID, then opt in to sending source code to that external provider:

    export OPENAI_API_KEY=...
    export OPENAI_MODEL=...
    polymigrate migrate --source ./my-project --from python --to go --output ./migration-output --provider openai --allow-source-upload

Optional isolated validation images use environment variables named POLYMIGRATE_DOCKER_IMAGE_PYTHON, POLYMIGRATE_DOCKER_IMAGE_GO, POLYMIGRATE_DOCKER_IMAGE_JAVASCRIPT, POLYMIGRATE_DOCKER_IMAGE_TYPESCRIPT, POLYMIGRATE_DOCKER_IMAGE_JAVA, POLYMIGRATE_DOCKER_IMAGE_RUST, POLYMIGRATE_DOCKER_IMAGE_CSHARP, and similarly for supported language IDs. Images must already exist locally; no image pull is performed.

Provider configuration variables:
- OpenAI-compatible API: OPENAI_API_KEY, OPENAI_MODEL, optional OPENAI_BASE_URL.
- OpenRouter: OPENROUTER_API_KEY, OPENROUTER_MODEL, optional OPENROUTER_BASE_URL.
- Anthropic: ANTHROPIC_API_KEY, ANTHROPIC_MODEL, optional ANTHROPIC_BASE_URL.
- Gemini: GEMINI_API_KEY, GEMINI_MODEL, optional GEMINI_BASE_URL.

The source-upload flag is required to transmit source text to an external model. Recognizable secrets are redacted on a best-effort basis, but redaction is not guaranteed to find every secret and may alter source semantics. Do not send confidential code to an external provider unless your data-handling policy permits it. Review the generated migration-review.json. By default all validation gates are NOT_RUN. If a target-language Docker image is already available locally and configured, selected build and unit-test commands run in a restricted container with no network, a read-only root filesystem, dropped capabilities, resource limits, and only the generated workspace mounted. The image is never pulled automatically. Security review and behavior-equivalence checks remain NOT_RUN in this experimental mode.

### Optional local knowledge cache

Set POLYMIGRATE_KNOWLEDGE_DB to a local SQLite file to enable evidence-gated migration knowledge lookup. To also cache unverified translation drafts within the same project scope, set POLYMIGRATE_CACHE_DRAFTS=1. Draft caching is disabled by default because the local database may contain generated source code. Drafts are never treated as verified and are not shared across projects. Source-content and Graphify-context fingerprints invalidate stale draft matches. Only explicitly shareable, verified knowledge records can be reused across projects.

Graphify CLI reference: https://github.com/Graphify-Labs/graphify

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
- src/polymigrate/migration/: library strategy ranking, evidence-constrained AI decisions, and a safe adapter execution pipeline.
- src/polymigrate/knowledge.py: persistent evidence-gated knowledge store.
- src/polymigrate/security/: best-effort secret redaction at model boundaries.
- src/polymigrate/ai/config.py: environment-based provider setup; use the providers command to inspect configuration without network calls.
- src/polymigrate/reporting.py: final status derivation.
- specs/001-foundation/: feature spec, plan, and tasks.
- skills/: initial migration skill packages.

## Security and correctness

Migration work must use an isolated workspace, preserve source input, validate generated output, and report unresolved issues rather than claiming success without evidence. Treat source files, skills, package metadata, and model output as untrusted data. Never place API keys in prompts, logs, or reusable knowledge. Cross-project knowledge reuse is opt-in and only verified records are eligible.

## Roadmap

1. Verify provider contracts and Graphify integration against supported versions.
2. Add production-ready source/target parser and generator adapters; current pipeline exposes tested adapter contracts but ships no universal production translator.
3. Implement the autonomous transformation and dependency-reconstruction engine.
4. Add sandboxed build/test execution and bounded automated repair.
5. Add differential behavior testing and multi-language E2E fixtures.
6. Expand skills and reusable migration patterns based on verified evidence.

## License

MIT. See LICENSE.

### Library replacement research

The package discovery module queries fixed public endpoints for npm, crates.io, Maven Central, NuGet, RubyGems, Packagist, PyPI search, and GitHub repository fallback for selected languages. With --allow-source-upload, the CLI builds a bounded import inventory, asks the selected AI provider to identify possible gaps grounded in observed imports, searches for alternatives, and records a decision or custom-reconstruction recommendation. Registry descriptions are untrusted metadata, not proof of semantic equivalence; package installation is never automatic. In this experimental milestone, dependency manifests are not migrated, so a selected package is reported as CANDIDATE_IDENTIFIED_NOT_WIRED and the translator is instructed not to introduce an unresolved external import. These tools can also be registered with an agent through the package and Graphify tooling helpers.
