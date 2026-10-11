# Tasks: PolyMigrate Foundation

- [x] T001 Write constitution and feature specification.
- [x] T002 Define architecture and validation plan.
- [x] T003 Implement typed migration models and final status rules.
- [x] T004 Implement extensible language registry.
- [x] T005 Implement provider-neutral protocol and capability registry.
- [x] T006 Implement skill metadata registry and permission checks.
- [x] T007 Implement library replacement strategy ranking.
- [x] T008 Implement optional Graphify artifact adapter.
- [x] T009 Implement deterministic migration planner and output-path validation.
- [x] T010 Implement CLI plan command and JSON output.
- [x] T011 Add unit, integration, and E2E contract tests.
- [x] T012 Add CI workflow, package installation check, and development documentation.
- [x] T013 Add persistent evidence-gated migration knowledge store.
- [x] T014 Add bounded agent runtime and allowlisted tool execution.
- [x] T015 Add HTTP adapters for OpenAI-compatible, Anthropic, and Gemini APIs; no live-credential claim.
- [x] T016 Add environment-based provider configuration and offline provider diagnostics.
- [x] T017 Add best-effort secret redaction for model-boundary payloads.
- [x] T018 Add evidence-constrained AI library decision engine that rejects unknown candidate names.
- [x] T019 Add pluggable source/target adapter contracts and bounded safe output writing.
- [x] T020 Run CI contract suite on Python 3.11, 3.12, and 3.13; 503 tests passed in the latest verified workflow across all three versions (6 environment-dependent tests skipped); the dedicated Docker behavior E2E job and wheel packaging check passed on commit `8cb5db7a`; rerun CI after subsequent commits before release.
- [x] T021 Add experimental per-file AI translation with explicit source-upload opt-in and an unverified review report.
- [ ] T022 Verify provider adapters against current API contracts and live credentials.
- [ ] T023 Implement production source parsers and target generators across language pairs.
- [x] T024 Orchestrate the current experimental stages end-to-end: inventory, dependency/library resolution, translation, bounded manifest reconstruction, repair, validation, optional behavior comparison, knowledge-store handling, and review reporting. Generated dependencies remain unverified and are never installed automatically.
- [x] T025 Add isolated build/test execution and bounded automated repair loop.
- [x] T026 Add safe Graphify CLI query adapter and include graph context in experimental migration; live version compatibility and incremental graph invalidation remain unverified.
- [x] T027 Add migration E2E fixtures across language pairs and behavior-equivalence checks; real sandboxed Python→Node and Python→Go output comparisons pass, while each result remains limited to explicitly declared cases.
- [x] T028 Add opt-in same-project draft caching keyed by source, target, toolchain, and Graphify context fingerprints.
- [x] T029 Add restricted Docker validation runner with no network, no shell, resource limits, timeout cleanup, and no automatic image pulls.
- [x] T030 Add language-aware validation command selection and integrate optional build/test results into the final migration review.
- [x] T031 Add AI translation budgets for file count, total source context, and total generated output.
- [x] T032 Add bounded package discovery for npm, crates.io, Maven Central, NuGet, RubyGems, Packagist, PyPI search, and GitHub repository fallback.
- [x] T033 Add AI-guided library resolution that constrains package choices to discovered metadata or recommends custom reconstruction.
- [x] T034 Register package search, Graphify inspection, and library resolution as allowlisted agent tools.
- [x] T035 Add bounded import inventory and AI dependency-gap planning grounded in observed imports.
- [x] T036 Integrate library discovery decisions into the CLI migration context and final review summary.
- [x] T037 Require explicit PASS evidence for all required gates before knowledge can be marked verified or shared.
- [x] T038 Inject packaged migration skills into CLI model context and enforce per-skill tool scopes in the agent runtime.
- [x] T039 Add configurable provider output-token budgets and a 2 MB response-body limit.
- [x] T040 Distinguish passing test evidence from zero-test and unconfirmed test runs.
- [x] T041 Add bounded post-validation repair attempts that cannot modify test files or write outside the generated project.

- [x] T042 Prevent cross-project draft record collisions and prevent unverified records from downgrading verified/shareable knowledge; regression-tested.
- [x] T043 Add bidirectional migration orchestration contract fixtures for representative language pairs; these tests do not claim semantic equivalence.
- [x] T044 Add executable Python↔Go arithmetic fixtures that compare source and generated output; the broader behavior harness and real Docker comparisons are covered by T056–T057.
- [x] T045 Reject Graphify artifact paths and symlinks that resolve outside the selected project root.
- [x] T046 Add an opt-in, source-free live provider connectivity check; live verification with real credentials remains unverified in this environment.
- [x] T047 Add bounded allowlisted source-manifest inventory with secret redaction, traversal limits, and prompt-context regression tests.
- [x] T048 Feed bounded, redacted source-manifest evidence into dependency-gap planning without trusting manifest contents as instructions.
- [x] T049 Extract bounded Python AST symbols/imports and heuristic structure hints for other registered languages, then include those hints in translation prompts; production parsers remain open under T023.
- [x] T050 Add allowlisted AI target-manifest reconstruction with bounded output, path validation, secret checks, and executable-hook rejection; manifests remain unverified and are not installed automatically.
- [x] T051 Exercise source-manifest discovery through the CLI and verify the constrained target manifest is written while the migration remains explicitly unverified.
- [x] T052 Bound source inventory traversal, prune ignored/symlink directories, and test fail-closed behavior at the configured entry limit.
- [x] T053 Include a source-manifest fingerprint in library-resolution cache keys and regression-test invalidation when manifest contents change.
- [x] T054 Keep source files inventoried when Python AST parsing fails safely, and emit a warning rather than aborting the migration.
- [x] T055 Add an optional offline Tree-sitter parser extra with bounded parse/source limits and heuristic fallback; verify syntax diagnostics when the grammar is available.
- [x] T056 Add an opt-in sandboxed behavior contract that compares source and target stdout against explicit expected outputs, rejects shell/inline execution, and records the gate in the migration review.
- [x] T058 Verify target dependency declarations and library wiring through real target builds/integration tests; candidate status requires declared dependencies, production and integration-test imports, and PASSED build/integration/behavior gates. Real local-package fixtures cover Python, Go, JavaScript, Ruby, Rust, and Java, including exact class provenance for Java local JARs.
- [ ] T059 Implement a comprehensive security-review gate for generated code and manifests; keep verified knowledge promotion blocked until this gate has trustworthy evidence.
- [x] T060 Add a bounded static security scan for generated files, report high/medium/low findings without echoing secret values, block on high-risk findings, and explicitly keep the comprehensive security-review gate unverified.
- [x] T061 Add a static dependency-wiring review for Python, Go, Rust, and JavaScript/TypeScript imports versus target manifests; missing declarations block output, while build/API compatibility remains explicitly unverified.

- [x] T062 Run `go vet ./...` in the restricted target-validation container for Go outputs and cover command selection in tests; this adds static analysis but does not replace build, integration, behavior, or security gates.

- [x] T063 Add fail-closed local scanner evidence aggregation and record scanner execution details; keep the comprehensive security-review gate INCOMPLETE until scanner provenance is authenticated and the audit is comprehensive.
- [x] T064 Add real offline candidate-dependency proof fixtures for Go, Python, JavaScript/TypeScript, and Ruby; public package equivalence and unsupported target languages remain open under T058.
- [x] T065 Reduce false-positive Go import inventory and avoid heuristic symbol union when Tree-sitter parsing is available; production parser and generator coverage remains open under T023.

- [x] T066 Add an offline deterministic Python-to-JavaScript translator for a strict, tested syntax subset and wire it into the CLI; this expands one pair only and does not complete T023.

- [x] T067 Verify locally executed scanner binary identity against operator-managed SHA-256 pins; missing or mismatched pins remain untrusted, and T059 stays open because authenticated binaries alone do not constitute a comprehensive audit.

- [x] T068 Add a deterministic Python-to-Rust subset that emits a minimal Cargo project, validates signed-i32 arithmetic, and has offline build/run fixtures; this is still a constrained pair and does not complete T023.

- [x] T069 Add Rust Cargo manifest/import consistency checks and candidate-specific crate proof using an offline local crate, actual Cargo build/test execution, and runtime output; public registry availability remains unverified without an explicit real-project build.

- [x] T070 Extend the deterministic Python-to-JavaScript subset with bounded if/else conditions, short-circuit boolean combinations, and runtime-tested output; branch assignments, chained comparisons, and string ordering remain explicitly unsupported.

- [x] T071 Extend the deterministic Python-to-Go subset with bounded if/else conditions, boolean combinations, and integer/string truthiness mapping; validate generated code with Go formatting and runtime fixtures.

- [x] T072 Extend the deterministic Python-to-Rust subset with bounded if/else conditions, boolean combinations, and integer/string truthiness mappings, verified by offline Cargo execution.

- [x] T073 Extend deterministic Python-to-Go/JavaScript/Rust subsets with bounded `range()` loops over statically known bounds, enforce a 10,000-iteration cap, and reject loop-body assignments; verify generated runtime output for all three targets.
- [x] T074 Add bounded Python `if`/`elif`/`else` chain support to deterministic Go, JavaScript, and Rust translators; cap chains at 20 branches and verify generated runtime output.
- [x] T075 Fail closed when dependency-gap planning fails or library decisions remain unresolved/custom; do not treat an empty candidate list as proof that dependency integration passed.
- [x] T076 Support statically known positive and negative non-zero `range()` steps in deterministic Go, JavaScript, and Rust translators; cap actual iteration count and reject target-integer overflow, with runtime-equivalence tests.
- [x] T077 Support boolean literals/variables in deterministic Go, JavaScript, and Rust subsets, preserve Python-style boolean output, and reject boolean arithmetic or ordering comparisons; verify target runtime behavior.
- [x] T078 Expand bounded static security heuristics for dynamic SQL interpolation, unsafe temporary paths, disabled TLS verification, Rust unsafe blocks, and process launching; keep the overall security gate explicitly non-comprehensive.

- [x] T079 Require an operator-managed SHA-256 pin for the bundled Semgrep rules file before scanner provenance is trusted; regression-test missing, malformed, and mismatched rules pins. This authenticates configured inputs only and does not close the comprehensive security audit gate T059.

- [x] T080 Keep `security_review` INCOMPLETE even when local scanner binaries and bundled Semgrep rules are authenticated; add regression coverage so scanner provenance cannot be mistaken for a comprehensive audit. T059 remains open.

- [x] T082 Add an offline deterministic Python-to-Java translator for a strict single-file assignment/expression/print subset; reject unsupported control flow, run `javac` and a runtime smoke check when available, and cover the target with explicit output fixtures. This expands one pair only and does not complete T023.

- [x] T083 Extend the strict Python-to-Java subset with bounded `if`/`elif`/`else` chains, safe numeric/boolean comparisons, Java string equality, and print-only branches; reject chained comparisons and branch assignments and verify generated Java output with a real JDK.

- [x] T084 Add bounded Python `range()` loops to the strict Java subset with statically known bounds, non-zero signed steps, a 10,000-iteration cap, overflow checks, print-only bodies, and actual JDK runtime fixtures.

- [x] T085 Add Java import inventory and Maven/Gradle dependency declaration parsing; block external imports without a manifest and keep package-to-coordinate mapping UNVERIFIED when static evidence cannot prove the mapping.

- [x] T086 Align dependency-proof documentation with the existing Rust local-crate build/integration fixture and add a regression test that Java candidate integration remains NOT_RUN until artifact-to-import resolution is actually proven.

- [x] T087 Add narrowly scoped Java candidate-dependency proof only for a declared project-local system-scope JAR whose exact class import is verified in the archive and whose build, integration test, and behavior gates pass; leave public Maven/Gradle resolution unverified.

- [x] T088 Add safe Python `str()` conversion to the deterministic Java subset, preserving Python boolean spelling and rejecting shadowed/invalid calls; verify compiled runtime output.

- [x] T089 Extend deterministic Python-to-Java `print()` to support up to 32 positional values with Python-style space separators/boolean text and empty calls; reject unsupported keyword arguments and verify generated Java compilation/runtime output.
- [x] T090 Extend deterministic Python-to-Go, JavaScript, and Rust `print()` to support up to 32 positional values and empty calls, preserve Python-style boolean output, reject unsupported keyword arguments, and validate target runtime output.
- [x] T091 Add safe deterministic Python `str()` conversion for integer/string/boolean values in Go, JavaScript, and Rust; reject builtin shadowing and unsupported call forms, and verify generated target runtime output.
- [x] T092 Add deterministic `abs()` support for safe integer expressions across Python-to-Go, JavaScript, Rust, and Java; reject shadowing, invalid call forms, non-integer values, and overflow, with target-runtime fixtures.
- [x] T093 Support Python `not` expressions as boolean values in all four deterministic targets, reuse the constrained truthiness/comparison translator, and verify target runtime output for boolean and integer truthiness.
- [x] T094 Allow deterministic `if`/`elif`/`else` bodies to assign only to previously assigned variables of the same inferred type, reject branch-local declarations/type changes, invalidate stale integer facts after branches, and verify target runtime output across all four deterministic targets.
- [x] T095 Support bounded integer `+=`, `-=`, and `*=` across all four deterministic targets, plus string `+=` in Go/JavaScript/Java; validate type consistency, overflow, unsupported forms, and generated runtime output.
- [x] T096 Support bounded `while` loops across all four deterministic targets only when static integer simulation proves termination within 10,000 iterations; reject unsupported conditions, unmodified conditions, non-progress, overflow, `while/else`, and unsupported body statements, with target-runtime fixtures.
