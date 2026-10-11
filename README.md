# PolyMigrate

PolyMigrate is an early-stage, provider-agnostic foundation for autonomous cross-language software migration. Its design combines a spec-driven workflow, extensible language metadata, AI provider interfaces, reusable migration knowledge, Graphify integration points, skills, and evidence-based validation.

## Current status

**Experimental migration milestone; not production-ready.** The CLI supports planning and opt-in AI translation of source files, with bounded manifest analysis/reconstruction when source manifests exist. It is not yet a complete autonomous project migrator: target builds, dependency wiring, framework/test migration, behavior equivalence, and security review are not comprehensively verified.

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
- Deterministic Python-to-Go, Python-to-JavaScript, Python-to-Rust, Python-to-Java, Python-to-PHP, Python-to-Ruby, Python-to-C++, and Python-to-C# translators for explicitly constrained syntax subsets, with target validation and explicit validation-gate reporting.
- Spec-kit documents, initial skills, and GitHub Actions CI.

The provider adapters have not yet been verified against live credentials in this repository environment. They intentionally do not advertise native tool calling. Graphify reads an existing graph and can query it through the graphify CLI; graph construction and updates are handled by the local Graphify workflow. Graphify runtime/version compatibility is not a CI validation gate for this project.

## Requirements

- Python 3.11 or newer.
- No third-party runtime dependency is required for the planning path; offline Tree-sitter parsing is optional.
- Install richer parser support with `python -m pip install -e ".[parsers]"`; only already-available local grammars are used, with heuristic fallback.
- Install Semgrep and Bandit with `python -m pip install -e ".[security]"`. The `gitleaks` and `osv-scanner` executables are also required on `PATH`; Go additionally requires `gosec`.
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

To opt in to a live connectivity check, send a small source-free health request to each configured provider:

    polymigrate providers --check

This can incur a small provider charge and verifies connectivity/response shape only; it does not prove that a model can migrate a real project correctly.

### Deterministic translation subset

The offline deterministic strategy currently supports these deliberately narrow pairs:
- Python → Go
- Python → C++
- Python → C#
- Python → JavaScript
- Python → Rust
- Python → Java
- Python → PHP
- Python → Ruby

For example:

    polymigrate migrate --source ./small-python-project --from python --to javascript --output ./migration-output --strategy deterministic

All deterministic translators reject unsupported syntax rather than guessing. The Go, JavaScript, Rust, and Java subsets support `str()` and `abs()` for bounded integer/string/boolean values, plus Unicode-code-point-aware `len(string)`; builtin shadowing and keyword arguments are rejected. These four targets support bounded `while` loops only when static simulation proves termination within 10,000 iterations, and bounded `if`/`elif`/`else` chains whose bodies print or update existing variables without changing types. Go, JavaScript, and Rust also support bounded `range()` loops. Integer overflow, unsupported comparisons, nested control flow, and new branch-local variables are rejected. The PHP subset is intentionally narrower: per-file simple assignments, signed 32-bit integer arithmetic, string concatenation, booleans, `str()`, `abs()`, positional `print()` with Python-style boolean text, print-only `if`/`elif`/`else` chains, and bounded `for i in range(...)` loops with one to three statically known integer arguments, non-zero steps, and at most 10,000 actual iterations. Loop bodies may only print; the loop variable retains Python's final yielded value, and zero-iteration loops do not define it. Conditions support safe single comparisons and Python-compatible truthiness for known integer/string/boolean values. Branches cannot assign variables or contain nested control flow; chained comparisons, functions, imports, classes, collections, and manifest reconstruction are rejected. PHP files are linted with `php -l`, and `main.php` receives a runtime smoke check when PHP is installed. The Ruby subset supports simple per-file assignments, signed 32-bit integer arithmetic, strings/booleans, `str()`, `abs()`, positional `print()` with Python-style boolean text, print-only `if`/`elif`/`else` chains, and bounded print-only `for i in range(...)` loops. Conditions use Python-compatible truthiness for known values and safe single comparisons; loops require one to three statically known integer arguments, a non-zero step, and at most 10,000 iterations. The loop variable retains Python's final yielded value, while zero-iteration loops leave it undefined. Branch assignments, nested control flow, chained comparisons, functions, imports, classes, collections, uppercase local names, Ruby reserved words, and unsupported control characters are rejected. Ruby files are linted with `ruby -c`, and `main.rb` receives a runtime smoke check when Ruby is installed. JavaScript arithmetic is restricted to the safe-integer range; Rust and Java use signed 32-bit integers. Java emits `Main.java` and runs `javac` plus a runtime smoke check when the JDK is available. A generated file is not a complete project migration, and a successful syntax/build check does not prove behavior equivalence; review the migration report and supply a behavior spec when applicable. The C++ subset supports a single Python source file with simple assignments, signed 32-bit integer arithmetic, strings/booleans, `str()`, `abs()`, and positional `print()` with Python-style boolean text. It supports print-only `if`/`elif`/`else` chains and bounded print-only `for i in range(...)` loops with Python-compatible truthiness, loop-variable behavior, and overflow checks. It rejects branch assignments, nested control flow, chained comparisons, multi-file source projects, functions, imports, classes, collections, C++ reserved/implementation-reserved identifiers, unsupported control characters, and integer overflow. Generated `.cpp` files are compiled with C++17 warnings-as-errors and the standalone executable is smoke-tested when `g++` is installed. The C# subset supports a single Python source file with simple assignments, signed 32-bit integer/string/boolean expressions, `str()`, `abs()`, and positional `print()` with Python-style boolean text. It emits a minimal .NET 8 console project, rejects unsupported syntax, type changes, C# reserved/builtin identifiers, multiple source files, unsupported control characters, and integer overflow. CI builds with warnings-as-errors and runs the generated assembly when .NET 8 is available.

### Experimental AI file translation

The current experimental migrate command translates supported source files one file at a time. Each model request also receives a size-bounded, content-free project index of parser-derived file paths, symbols, imports/dependencies, call references, and content hashes to help preserve cross-file relationships without duplicating source contents. It scans a bounded allowlist of source manifests and can attempt constrained AI reconstruction of allowlisted target manifests when source manifests or resolved dependency-gap evidence exist; these outputs remain unverified and dependencies are never installed automatically. Dependency wiring, frameworks, tests, deployment configuration, and database schemas are not yet migrated end-to-end, and full-project target builds/regression tests are not yet run automatically for every project. Its output status is GENERATED_UNVERIFIED.

Configure a provider key and explicit model ID, then opt in to sending source code to that external provider:

    export OPENAI_API_KEY=...
    export OPENAI_MODEL=...
    polymigrate migrate --source ./my-project --from python --to go --output ./migration-output --provider openai --allow-source-upload

A project-specific behavior contract can compare expected source and target output inside pre-pulled, network-disabled Docker images:

    polymigrate migrate --source ./my-project --from python --to go --output ./migration-output --provider openai --allow-source-upload --behavior-spec ./behavior.json

Example `behavior.json`:

<escape>{
  "source_command": ["python", "main.py"],
  "target_command": ["go", "run", "main.go"],
  "cases": [
    {"name": "basic", "expected_stdout": "42\\n"}
  ]
}</escape>

Set both `POLYMIGRATE_DOCKER_IMAGE_PYTHON` and `POLYMIGRATE_DOCKER_IMAGE_GO` to images already present locally. The harness rejects shell/inline-code commands, copies source and target into isolated temporary workspaces, and compares exact stdout for each declared case. It does not pull images or install dependencies.

Optional isolated validation images use environment variables named POLYMIGRATE_DOCKER_IMAGE_PYTHON, POLYMIGRATE_DOCKER_IMAGE_GO, POLYMIGRATE_DOCKER_IMAGE_JAVASCRIPT, POLYMIGRATE_DOCKER_IMAGE_TYPESCRIPT, POLYMIGRATE_DOCKER_IMAGE_JAVA, POLYMIGRATE_DOCKER_IMAGE_RUST, POLYMIGRATE_DOCKER_IMAGE_CSHARP, and similarly for supported language IDs. Images must already exist locally; no image pull is performed.

Provider configuration variables:
- OpenAI-compatible API: OPENAI_API_KEY, OPENAI_MODEL, optional OPENAI_BASE_URL.
- Local 9Router Proxy: POLYMIGRATE_9ROUTER_API_KEY, POLYMIGRATE_9ROUTER_MODEL, optional POLYMIGRATE_9ROUTER_BASE_URL (defaults to http://localhost:20128/v1) and POLYMIGRATE_9ROUTER_MAX_OUTPUT_TOKENS. This uses the same OpenAI-compatible Chat Completions adapter and does not advertise native tool calling.
- OpenRouter: OPENROUTER_API_KEY, OPENROUTER_MODEL, optional OPENROUTER_BASE_URL.
- Anthropic: ANTHROPIC_API_KEY, ANTHROPIC_MODEL, optional ANTHROPIC_BASE_URL.
- Gemini: GEMINI_API_KEY, GEMINI_MODEL, optional GEMINI_BASE_URL.

To use a local 9Router instance, set its key in a local environment variable or an untracked .env file; do not paste it into shell history or commit it. You can discover model IDs before selecting a generation model: if the 9Router key is present but POLYMIGRATE_9ROUTER_MODEL is empty, model listing remains available while generation and connectivity checks fail safely until a model is selected. After filling the 9Router key/base URL in your local .env file, load them into your shell and list models:

    set -a
    . ./.env
    set +a
    polymigrate providers --list-models

After choosing an exact returned model ID, set POLYMIGRATE_9ROUTER_MODEL in .env, reload the environment, then run:

    polymigrate providers
    polymigrate providers --check

The model-list command queries the OpenAI-compatible /models endpoint and prints model IDs without printing credentials. Select an exact ID for POLYMIGRATE_9ROUTER_MODEL, then run the connectivity check. The check sends a source-free health prompt and verifies a valid JSON response; it does not prove migration quality. The localhost URL works only from a machine/network namespace that can reach the running 9Router process. GitHub-hosted CI cannot reach a developer localhost automatically. After connectivity succeeds, test an actual migration with:

    polymigrate migrate --source ./sample-python-project --from python --to go --output ./migration-output --provider 9router --allow-source-upload

This sends source code to the configured model. Use a disposable, non-confidential sample project for live tests and review the generated output and migration-review.json; the result remains GENERATED_UNVERIFIED until all target validation gates pass.

The source-upload flag is required to transmit source text to an external model. Recognizable secrets are redacted on a best-effort basis, but redaction is not guaranteed to find every secret and may alter source semantics. Do not send confidential code to an external provider unless your data-handling policy permits it. Review the generated migration-review.json. By default validation gates are NOT_RUN. If a target-language Docker image is already available locally and configured, selected build and unit-test commands run in a restricted container with no network, a read-only root filesystem, dropped capabilities, resource limits, and only the generated workspace mounted. The image is never pulled automatically. A bounded heuristic static security scan runs on generated output and records findings in `migration-review.json`. The local security gate separately invokes locally installed Semgrep with a repository-bundled offline ruleset, plus Gitleaks for secrets, OSV-Scanner for dependency vulnerabilities, Bandit for Python, and gosec for Go. If required scanners are missing, fail, time out, or produce malformed reports, `security_review` is `INCOMPLETE` and the final report is blocked. Scanner binaries are authenticated against operator-managed SHA-256 pins, and Semgrep's bundled rules file must also match `POLYMIGRATE_TRUSTED_SEMGREP_RULES_SHA256`. Missing or mismatched pins keep scanner provenance unverified. The gate returns `PASSED` only when every required scan is complete and pinned, the bounded static review is clean, and dependency-wiring review passes. This is an evidence-backed gate for the declared scanner scope, not proof of zero vulnerabilities. Install the `security` extra plus the external Gitleaks and OSV-Scanner binaries; Go also needs `gosec`. These checks improve coverage but do not guarantee the absence of vulnerabilities. Static dependency-wiring checks cover Python, Go, Java, JavaScript/TypeScript, Kotlin, Ruby, and PHP to varying levels; Java package-to-Maven/Gradle coordinate mapping remains explicitly `UNVERIFIED` until real build/integration evidence resolves the mapping; ambiguous mappings remain `UNVERIFIED`. Candidate library integration is only marked verified when the package is declared and imported by production code and a recognized test file, and target build, integration tests, and behavior comparison all pass. That candidate-specific dependency proof currently supports Go, Rust, Python, JavaScript, TypeScript, and Ruby when their declared dependencies, production imports, target build, integration tests, and behavior comparison all pass; Java candidate proof is currently limited to a declared project-local system-scope JAR whose exact imported class is found in the archive and whose target build, integration test, and behavior checks pass; public Maven/Gradle coordinate resolution remains `NOT_RUN`. Behavior comparison runs only when a project-specific `--behavior-spec` is supplied.

### Deterministic Python-to-Go translation

The experimental deterministic strategy translates a deliberately limited subset of Python into one standalone Go source file. It does not initialize an AI provider and does not transmit source code to an external model.

Run it without `--provider` or `--allow-source-upload`:

    polymigrate migrate --source ./sample-python-project --from python --to go --output ./migration-output --strategy deterministic

Currently supported syntax is intentionally constrained:
- Integer, string, and boolean literals; simple assignments to one variable.
- `print()` with up to 32 positional arguments or no arguments; keyword arguments such as `sep` and `end` are rejected.
- Integer arithmetic with `+`, `-`, and `*`, string concatenation with `+`, and unary `+`/`-` on integers.
- Supported `str()`, `abs()`, and Unicode-aware `len(string)` calls, `not`, boolean conditions, and bounded `+=`, `-=`, and `*=` with type and overflow checks.
- Bounded `if`/`elif`/`else` chains and `range()` loops with statically known bounds/steps and at most 10,000 iterations. Supported branch and loop bodies may print or update previously assigned variables without changing types.
- `while` loops only when static integer simulation proves termination within 10,000 iterations.

The adapter rejects unsupported statements and expressions rather than attempting speculative translation. It accepts exactly one inventoried Python source file. Functions, classes, imports, project dependencies, frameworks, nested control flow, and multi-file applications are not translated.

Integer values and integer arithmetic are conservatively restricted to the signed 32-bit range (-2147483648 through 2147483647). Integer literals and statically evaluated arithmetic that exceed this range are rejected rather than translated with potentially different Go integer behavior. Expressions whose integer safety cannot be proven are also rejected.

When `go` and `gofmt` are available, the strategy formats and builds the generated Go source, then runs `go vet` if the build succeeds. If `POLYMIGRATE_DOCKER_IMAGE_GO` names an already-available target validation image, the strategy also runs the language-aware build/test discovery suite in the restricted Docker sandbox and records its executions and gate statuses. Unit, integration, or E2E gates remain `NOT_RUN` when the generated project has no corresponding tests or no validation image is configured; images are never pulled automatically. It also performs the existing static security and dependency-wiring reviews. These checks do not prove semantic equivalence or provide a comprehensive security audit.

Without `--behavior-spec`, behavior comparison remains `NOT_RUN`. With a behavior spec, comparison requires Docker and the configured, already-pulled Python and Go images (`POLYMIGRATE_DOCKER_IMAGE_PYTHON` and `POLYMIGRATE_DOCKER_IMAGE_GO`). The strategy never pulls images automatically. Missing validation prerequisites must be reported as blocked or unverified, not as successful validation.

The generated `migration-review.json` records the validation gates and overall status. Pass `--security-evidence path/to/evidence.json` to include externally produced scanner evidence. The JSON object must contain `required_scanners` (a list of scanner IDs) and `evidence` (a list of objects with `scanner_id`, `scanner_version`, `complete`, `exit_code`, `report_sha256`, and `findings`). Each finding requires a `severity` (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, or `INFO`) and a `rule_id`. Missing or malformed evidence is `INCOMPLETE`, not a pass. The report explicitly marks scanner provenance as unverified; this input is evidence aggregation only, not trusted scanner execution or a comprehensive audit. Treat this feature as an experimental, subset-specific translator, not a general-purpose or production-ready project migrator.

### Optional local knowledge cache

Set POLYMIGRATE_KNOWLEDGE_DB to a local SQLite file to enable evidence-gated migration knowledge lookup. To also cache unverified translation drafts within the same project scope, set POLYMIGRATE_CACHE_DRAFTS=1. Draft caching is disabled by default because the local database may contain generated source code. Drafts are never treated as verified and are not shared across projects. Source-content and Graphify-context fingerprints invalidate stale draft matches. Only explicitly shareable, verified knowledge records can be reused across projects.

Graphify CLI reference: https://github.com/Graphify-Labs/graphify

## Development and tests

    python -m compileall -q src tests
    PYTHONPATH=src python -m unittest discover -s tests -v

The CI workflow runs compilation and unit/integration/E2E contract tests across Python 3.11, 3.12, and 3.13. It also exercises bidirectional migration orchestration fixtures across representative language pairs and runs executable Python↔Go arithmetic fixtures to compare source and generated output. These deterministic fixtures validate only their covered examples; they do not establish general semantic equivalence for arbitrary projects.

## Architecture

- src/polymigrate/languages.py: language metadata registry.
- src/polymigrate/planner.py: deterministic planning and source inventory.
- src/polymigrate/ai/: provider protocols, capability registry, and HTTP adapters.
- src/polymigrate/agent/: bounded decision loop and tool allowlist.
- src/polymigrate/skills/: validated skill metadata.
- src/polymigrate/graph/: optional Graphify artifact adapter.
- src/polymigrate/migration/: bounded source-manifest inventory, library strategy ranking, evidence-constrained AI decisions, and a safe adapter execution pipeline.
- src/polymigrate/migration/python_go_target.py: experimental deterministic translator for a constrained Python-to-Go subset.
- src/polymigrate/migration/python_javascript_target.py, python_rust_target.py, python_java_target.py, python_php_target.py, python_ruby_target.py, python_cpp_target.py, and python_csharp_target.py: experimental deterministic translators for strict Python-to-JavaScript, Python-to-Rust, Python-to-Java, Python-to-PHP, and Python-to-Ruby, and Python-to-C++, and Python-to-C# subsets.
- src/polymigrate/validation/dependency_wiring.py: static manifest/import consistency checks for supported languages, including Rust Cargo projects; this is not proof of package API compatibility.
- src/polymigrate/knowledge.py: persistent evidence-gated knowledge store.
- src/polymigrate/security/: best-effort secret redaction at model boundaries.
- src/polymigrate/ai/config.py: environment-based provider setup; use the providers command to inspect configuration without network calls.
- src/polymigrate/reporting.py: final status derivation.
- specs/001-foundation/: feature spec, plan, and tasks.
- skills/: initial migration skill packages.

## Security and correctness

Migration work must use an isolated workspace, preserve source input, validate generated output, and report unresolved issues rather than claiming success without evidence. Treat source files, skills, package metadata, and model output as untrusted data. Never place API keys in prompts, logs, or reusable knowledge. Cross-project knowledge reuse is opt-in and only verified records are eligible.

## Roadmap

1. Verify provider adapters against current API contracts and live credentials, and document supported Graphify runtime compatibility.
2. Expand production parser and deterministic generator coverage beyond the current strict Python-to-Go/JavaScript/Rust/Java subsets; the AI path is still experimental and not a universal production translator.
3. Complete a comprehensive, evidence-backed security-review gate before allowing verified knowledge promotion.
4. Expand behavior-equivalence contracts and real sandboxed E2E fixtures across more source/target language pairs.
5. Expand skills and reusable migration patterns only when supported by repeatable validation evidence.

### Trusted local security-scanner binaries

PolyMigrate records scanner execution and report hashes, but it does not trust a scanner binary merely because it is found on `PATH`. To verify local scanner provenance, configure an operator-managed SHA-256 pin for every scanner required by the language profile:

- `POLYMIGRATE_TRUSTED_SCANNER_SHA256_SEMGREP`
- `POLYMIGRATE_TRUSTED_SCANNER_SHA256_GITLEAKS`
- `POLYMIGRATE_TRUSTED_SCANNER_SHA256_OSV_SCANNER`
- `POLYMIGRATE_TRUSTED_SCANNER_SHA256_BANDIT` (Python profile)
- `POLYMIGRATE_TRUSTED_SCANNER_SHA256_GOSEC` (Go profile)
- `POLYMIGRATE_TRUSTED_SEMGREP_RULES_SHA256` (the exact bundled `src/polymigrate/security/semgrep_rules.yml` file)

Each value must be the 64-character SHA-256 digest of the exact scanner executable. Obtain and review pins from a trusted distribution channel; do not blindly calculate a digest from the same untrusted machine and treat it as a trust anchor. Missing or mismatched pins keep scanner provenance unverified even when the scanner command reports a clean scan. Correct pins establish binary identity against the operator's configured trust values; they do **not** make the limited scanner set a comprehensive security audit or prove absence of vulnerabilities. The `security_review` gate can pass only when all required scanners and static/dependency checks pass with trusted provenance; even then it is evidence for the declared scope, not a guarantee of security.

## License

MIT. See LICENSE.

### Library replacement research

The package discovery module queries fixed public endpoints for npm, crates.io, Maven Central, NuGet, RubyGems, Packagist, PyPI search, and GitHub repository fallback for selected languages. With --allow-source-upload, the CLI builds a bounded import inventory, asks the selected AI provider to identify possible gaps grounded in observed imports, searches for alternatives, and records a decision or custom-reconstruction recommendation. Registry descriptions are untrusted metadata, not proof of semantic equivalence; package installation is never automatic. In this experimental milestone, a constrained target manifest reconstruction step may run when source manifests are found, but it is unverified and does not install dependencies. A selected package is reported as CANDIDATE_IDENTIFIED_NOT_WIRED unless its integration is actually proven, and the translator is instructed not to introduce an unresolved external import. These tools can also be registered with an agent through the package and Graphify tooling helpers.

### Autonomous repair and validation evidence

When a local validation image is configured with `POLYMIGRATE_DOCKER_IMAGE_<LANG>`, the CLI runs a bounded repair loop (up to three attempts by default) after build/test failures. Repairs are revalidated and may only modify existing production source files; test files, manifests, and files outside the generated output are not eligible. If Docker is unavailable or the image is not preloaded, the run is reported as blocked/unverified rather than pulling an image or claiming success. Test commands that report zero tests become NOT_RUN; successful commands whose test count cannot be confirmed become UNVERIFIED. Integration/E2E tests are run only when the project layout or configured scripts make them discoverable. Behavior comparison remains NOT_RUN unless `--behavior-spec` is supplied; it validates only the explicit cases and is not proof of general semantic equivalence. A bounded static security scan runs automatically. The `security_review` gate additionally requires trusted Semgrep, Gitleaks, OSV-Scanner, and where applicable Bandit/gosec evidence, plus clean dependency-wiring review; this remains a bounded assurance gate, not a substitute for a professional security audit.
