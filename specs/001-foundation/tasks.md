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
- [x] T020 Run CI contract suite on Python 3.11, 3.12, and 3.13; verified run `38220835987` on commit `5a7d6c38` passed 676 tests per Python version with 8 environment-dependent skips, verified all 6 packaged skill assets, and passed the dedicated C, C++, C#, Kotlin, PHP, Ruby, Swift, TypeScript, and sandboxed Docker behavior E2E suites.
- [x] T021 Add experimental per-file AI translation with explicit source-upload opt-in and an unverified review report.
- [ ] T022 Verify provider adapters against current API contracts and live credentials; mocked request/response contract tests exist, but live provider responses and model-specific behavior remain unverified.
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
- [x] T059 Implement and test an evidence-backed security-review gate for the declared scanner scope: trusted Semgrep, Gitleaks secret scanning, OSV-Scanner dependency vulnerability scanning, Bandit for Python or gosec for Go, operator-managed binary/rules SHA-256 pins, bounded static review, and dependency-wiring checks. Missing tools, incomplete reports, findings, or untrusted provenance fail closed. The gate is explicit that it is not proof of zero vulnerabilities; a live scan passes only when the operator installs the required tools and supplies matching SHA-256 pins.
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

- [x] T070 Extend the deterministic Python-to-JavaScript subset with bounded if/else conditions, short-circuit boolean combinations, and runtime-tested output; at this milestone branch assignments, chained comparisons, and string ordering were unsupported. Existing-variable branch assignments were later added under T094.

- [x] T071 Extend the deterministic Python-to-Go subset with bounded if/else conditions, boolean combinations, and integer/string truthiness mapping; validate generated code with Go formatting and runtime fixtures.

- [x] T072 Extend the deterministic Python-to-Rust subset with bounded if/else conditions, boolean combinations, and integer/string truthiness mappings, verified by offline Cargo execution.

- [x] T073 Extend deterministic Python-to-Go/JavaScript/Rust subsets with bounded `range()` loops over statically known bounds, enforce a 10,000-iteration cap, and reject loop-index reassignment; loop bodies may update previously assigned variables without changing types, verified with runtime output fixtures.
- [x] T074 Add bounded Python `if`/`elif`/`else` chain support to deterministic Go, JavaScript, and Rust translators; cap chains at 20 branches and verify generated runtime output.
- [x] T075 Fail closed when dependency-gap planning fails or library decisions remain unresolved/custom; do not treat an empty candidate list as proof that dependency integration passed.
- [x] T076 Support statically known positive and negative non-zero `range()` steps in deterministic Go, JavaScript, and Rust translators; cap actual iteration count and reject target-integer overflow, with runtime-equivalence tests.
- [x] T077 Support boolean literals/variables in deterministic Go, JavaScript, and Rust subsets, preserve Python-style boolean output, and reject boolean arithmetic or ordering comparisons; verify target runtime behavior.
- [x] T078 Expand bounded static security heuristics for dynamic SQL interpolation, unsafe temporary paths, disabled TLS verification, Rust unsafe blocks, and process launching; keep the overall security gate explicitly non-comprehensive.

- [x] T079 Require an operator-managed SHA-256 pin for the bundled Semgrep rules file before scanner provenance is trusted; regression-test missing, malformed, and mismatched rules pins. This authenticates configured inputs only and does not close the comprehensive security audit gate T059.

- [x] T080 Keep `security_review` INCOMPLETE even when local scanner binaries and bundled Semgrep rules are authenticated; add regression coverage so scanner provenance cannot be mistaken for a comprehensive audit. T059 remains open.

- [x] T082 Add an offline deterministic Python-to-Java translator for a strict single-file assignment/expression/print subset; reject unsupported control flow, run `javac` and a runtime smoke check when available, and cover the target with explicit output fixtures. This expands one pair only and does not complete T023.

- [x] T083 Extend the strict Python-to-Java subset with bounded `if`/`elif`/`else` chains, safe numeric/boolean comparisons, Java string equality, and print-only branches; at this milestone chained comparisons and branch assignments were rejected. Existing-variable branch assignments were later added under T094 and covered by JDK-backed output fixtures.

- [x] T084 Add bounded Python `range()` loops to the strict Java subset with statically known bounds, non-zero signed steps, a 10,000-iteration cap, overflow checks, print-only bodies at the initial milestone, and actual JDK runtime fixtures. Safe assignments to existing variables in loop bodies were later covered by T100.

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
- [x] T097 Build a deterministic, content-free project index from parser-derived file paths, symbols, dependencies, and hashes; enforce file/item/serialized-size caps and include the index in each AI translation request for cross-file context.
- [x] T098 Include the exact mapped target-relative path in each AI translation prompt and require target naming conventions (including Java public type/file-name alignment), with prompt contract tests.
- [x] T099 Add bounded parser-derived call-reference hints to source units, the project context index, and per-file model prompts; Python references use AST calls and other languages use installed Tree-sitter grammars when available.

- [x] T100 Add runtime-equivalence fixtures for safe assignments to previously assigned variables inside bounded `range()` loops across Python-to-Go, Python-to-JavaScript, Python-to-Rust, and Python-to-Java; reject loop-local declarations and loop-index reassignment.

- [x] T101 Add Unicode-code-point-aware `len(string)` support to deterministic Python-to-Go, JavaScript, Rust, and Java translators; reject builtin shadowing, invalid argument forms, and non-string values, enforce target integer bounds, and compare generated runtime output with Python fixtures.

- [x] T102 Add an offline deterministic Python-to-PHP translator for simple assignments, bounded signed-32-bit integer expressions, strings/booleans, `str()`, `abs()`, and positional `print()`; reject unsupported syntax, add a dedicated CI job that installs PHP CLI and verifies lint plus runtime output, and keep T023 open because general parser/generator coverage across all language pairs remains incomplete.

- [x] T103 Extend the deterministic Python-to-PHP subset with print-only `if`/`elif`/`else` chains, safe single comparisons, and Python-compatible truthiness; reject branch assignments, nested control flow, and chained comparisons, with real PHP runtime tests passing in CI.

- [x] T104 Add bounded Python `for i in range(...)` loops to the deterministic Python-to-PHP subset, with static integer/overflow checks, a 10,000-iteration cap, Python-compatible post-loop variable behavior, reserved-variable checks, and real PHP runtime fixtures passing in CI.

- [x] T105 Add an offline deterministic Python-to-Ruby translator for simple assignments, signed-32-bit integer/string/boolean expressions, `str()`, `abs()`, and positional `print()`; reject unsupported syntax and reserved local names, add Ruby syntax/runtime CI coverage, and keep general parser/generator coverage open.

- [x] T106 Extend deterministic Python-to-Ruby translation with print-only `if`/`elif`/`else` chains and bounded `range()` loops; preserve Python truthiness, comparison, iteration, overflow, and loop-variable semantics, with real Ruby runtime fixtures passing in CI.

- [x] T107 Add an offline deterministic Python-to-C++17 translator for a single source file with simple assignments, signed-32-bit integer/string/boolean expressions, `str()`, `abs()`, and positional `print()`; reject unsupported syntax, compile with warnings-as-errors, and validate runtime output in CI.

- [x] T108 Extend deterministic Python-to-C++17 translation with print-only `if`/`elif`/`else` chains and bounded `range()` loops; preserve Python truthiness, comparison, iteration, overflow, and loop-variable semantics with real C++17 runtime fixtures passing in CI.

- [x] T109 Add an offline deterministic Python-to-C#/.NET 8 translator for a single source file with simple assignments, signed-32-bit integer/string/boolean expressions, `str()`, `abs()`, and positional `print()`; generate a minimal project file, reject unsupported syntax, and validate build/runtime output in CI.

- [x] T110 Extend the deterministic Python-to-C# subset with print-only `if`/`elif`/`else` chains, safe single comparisons, Python truthiness, and short-circuit boolean conditions; reject branch assignments, nested control flow, and chained comparisons, with real .NET 8 runtime-equivalence fixtures passing in CI.
- [x] T111 Add bounded Python `range()` loops to the deterministic Python-to-C# subset only where static analysis proves integer safety and loop semantics; preserve Python loop-variable behavior, cap actual iterations, and reject unsupported bodies and overflow, with real .NET 8 runtime-equivalence fixtures passing in CI.

- [x] T112 Add a fail-closed deterministic Python-to-TypeScript subset using the fixed int/string/boolean model, strict TypeScript compiler validation, bounded expressions/control flow, runtime-equivalence fixtures, and a clear unsupported-syntax boundary; Python 3.11–3.13 CI and the dedicated strict `tsc` plus Node runtime fixtures pass.

- [x] T113 Add a fail-closed deterministic Python-to-Kotlin subset with explicit supported expression/control-flow rules, Kotlin compiler/runtime and CLI fixtures, correct Kotlin string-template escaping, and documented unsupported syntax; the expanded pinned Kotlin compiler/runtime suite passes 18 translator/CLI tests, including runtime comparison with Python.

- [x] T114 Add bounded Python `range()` loops to the Kotlin subset, preserving positive/negative step and post-loop variable semantics; enforce a 10,000-iteration budget and reject zero steps, unsafe integer expressions, empty-range undefined loop-variable reads, nested control flow, and unsupported bodies. The pinned Kotlin compiler/runtime suite passes 11 translator/CLI tests, including output comparison against Python.
- [x] T115 Add Unicode-code-point-aware `len(string)` to the Kotlin subset for statically known strings, track literal/concatenated string values for overflow-safe length analysis, reject non-string arguments and builtin shadowing, and compare supplementary Unicode output against Python in pinned compiler/runtime tests.
- [x] T116 Add bounded Python `while` loops to the Kotlin subset only when integer-condition simulation proves termination; support print statements and assignments to existing integer variables, cap at 10,000 iterations, and reject no-progress/non-terminating loops, nested control flow, `while/else`, non-integer conditions, and overflow-prone expressions. The pinned compiler/runtime fixture compares Kotlin output with Python.
- [x] T117 Add same-type simple assignments to existing variables inside Kotlin `if`/`elif`/`else` branches; simulate each branch from pre-branch facts and merge only integer/string facts that agree across every possible path, including the implicit no-op path without `else`. Reject new variables, type changes, and nested control flow; the pinned compiler/runtime fixture verifies branch output against Python.
- [x] T118 Support bounded integer `+=`, `-=`, `*=` and statically known string `+=` at top level and in conditionals; permit only integer augmented updates inside statically bounded `while` loops, prove signed-32-bit safety on each iteration, and reject unsupported augmented operators/types. Pinned Kotlin runtime fixtures verify integer and string augmented assignment output against Python.

- [x] T118 Add bounded Kotlin `range()` loop assignments to previously assigned integer variables, statically simulate every iteration to reject signed-32-bit overflow, reject loop-index reassignment/new variables/type changes, preserve zero-iteration state, and compare generated Kotlin runtime output with Python.

- [x] T119 Support integer `+=`, `-=`, and `*=` updates to existing variables inside bounded Kotlin `range()` loops; statically simulate every iteration, reject loop-index and non-integer augmented assignments, validate overflow, and compare generated runtime output with Python.

- [x] T120 Add a constrained offline Python-to-C11 translator for one file with signed 32-bit integer arithmetic, simple string/boolean values, `abs()`, and Python-style positional `print()`; reject unsupported syntax, add compiler/runtime equivalence fixtures, wire CLI build checks, and run the C suite in CI.

- [x] T121 Extend the constrained Python-to-C11 subset with print-only `if`/`elif`/`else` chains, short-circuit boolean conditions, scalar truthiness, and string equality via `strcmp`; reject branch assignments, nested control flow, chained comparisons, and string ordering, with GCC runtime-equivalence tests.

- [x] T122 Extend the constrained Python-to-C11 translator with bounded print-only `for i in range(...)` loops; statically validate one to three integer arguments, reject zero steps and ranges above 10,000 iterations, preserve the last loop value when referenced, and compare compiled C output with Python including negative steps and zero-iteration semantics.

- [x] T123 Add bounded Python `while`-to-C translation using a single integer comparison and statically simulated existing-integer assignments/`+=`/`-=`/`*=` updates; reject unproven termination, no-progress loops, overflow, `while/else`, nested control flow, and iteration counts above 10,000, with GCC runtime-equivalence tests.

- [x] T124 Extend bounded C `range()` loops to update previously assigned integer variables with simple assignments or integer `+=`/`-=`/`*=`; statically simulate every iteration for overflow, reject loop-index mutation/new variables/type changes, preserve zero-iteration facts, and compare compiled C output with Python.

- [x] T125 Support same-type assignments and integer augmented assignments to existing variables in C `if`/`elif`/`else` branches; merge static facts across all branches, retain facts only when every path agrees, reject undeclared/type-changing assignments and unprovable downstream arithmetic, and compare compiled output with Python.

- [x] T126 Add a deterministic Python-to-Swift subset for one file with signed-Int32-safe arithmetic, strings/booleans, `str()`, `abs()`, Unicode-scalar-aware `len(string)`, and Python-style positional `print()`; reject unsupported syntax, add Swift compiler/runtime equivalence fixtures and a dedicated CI job, and keep T023 open because broad production parser/generator coverage remains incomplete.

- [x] T127 Extend the deterministic Python-to-Swift subset with bounded `if`/`elif`/`else` chains, simple same-type comparisons, short-circuit boolean conditions, and print-only branch bodies; reject chained/string-ordering/boolean-ordering comparisons, branch assignments, and nested control flow, with Swift compiler/runtime equivalence fixtures and CLI coverage.

- [x] T128 Extend deterministic Python-to-Swift with statically bounded `for i in range(...)` loops, negative steps, at most 10000 iterations, per-iteration signed-Int32 safety checks, print-only bodies, and explicit rejection of loop-variable escape and unsupported statements; validate with Swift compiler/runtime and CLI E2E fixtures.

- [x] T129 Support same-type assignments to existing variables inside Swift `if`/`elif`/`else` branches, merge integer/string/boolean static facts only when every path agrees, emit mutable bindings when reassigned, and reject unsafe post-branch arithmetic when facts disagree; add compiler/runtime and CLI fixtures.

- [x] T130 Allow bounded Swift `range()` loop bodies to update existing variables with same-type assignments, simulate every iteration for overflow and static-fact updates, preserve post-loop facts only when the loop executes, and reject new variables, loop-target reassignment, type changes, and nested control flow; add compiler/runtime and CLI fixtures.
- [x] T131 Extend the constrained Python-to-C# range-loop subset to permit same-type assignments to existing variables, simulate each iteration to prove signed-32-bit safety, preserve zero-iteration semantics, and reject loop-target mutation, new/type-changing assignments, and writes to variables used to compute range bounds; verify compiled .NET 8 runtime output against Python fixtures.
- [x] T132 Extend the constrained Python-to-PHP range-loop subset to support same-type assignments to existing variables, simulate each iteration to reject signed-32-bit overflow, preserve zero-iteration semantics, and reject loop-target mutation, new/type-changing assignments, and writes to variables used to compute range bounds; add PHP lint/runtime equivalence fixtures.
- [x] T133 Extend the constrained Python-to-C++ range-loop subset to allow same-type assignments to existing variables, simulate each iteration for signed-32-bit overflow and static facts, preserve zero-iteration semantics, and reject loop-target mutation, new/type-changing assignments, and writes to variables used to compute range bounds; add C++17 compile/runtime equivalence fixtures.
- [x] T134 Reject OpenAI-compatible, Anthropic, and Gemini responses explicitly marked as output-truncated or provider-filtered; add mocked response fixtures so incomplete generated code is never accepted as a complete model response.
- [x] T135 Extend the constrained Python-to-Ruby range-loop subset to support same-type assignments to existing variables, simulate each iteration for signed-32-bit overflow and post-loop facts, preserve zero-iteration semantics, and reject loop-target mutation, new/type-changing assignments, and writes to variables used to compute range bounds; add Ruby syntax/runtime equivalence fixtures.
- [x] T136 Map JavaScript and TypeScript file suffixes using the source/target language pair (`.js`/`.ts`, `.jsx`/`.tsx`, `.mjs`/`.mts`, `.cjs`/`.cts`) and add regression tests for both migration directions while preserving suffixes for same-language migrations.
- [x] T137 Correct escaped regular expressions in target manifest reconstruction so Python `[build-system]` sections and Cargo `[build-dependencies]` (including target-specific sections) / `build =` directives are actually detected; add regressions proving these unsafe manifest patterns are rejected.
- [x] T138 Reject executable SwiftPM `Package.swift` manifests outside a narrow static DSL and reject Maven XML DTD/entity/external identifiers; malicious and positive fixtures pass in the verified full CI run.
- [x] T139 Add a fail-closed deterministic JavaScript-to-Python scalar subset with CLI integration, Python syntax/runtime smoke validation, and regression tests; full T023 parser/generator coverage remains open.

- [x] T140 Extend the constrained JavaScript-to-Python subset with print-only `if`/`else` branches and bounded integer `for` loops; reject unsupported control flow, unsafe bounds, nested branch/loop bodies, and loop-variable scope leaks, with Python syntax/runtime equivalence fixtures and dedicated CI validation.

- [x] T141 Extend JavaScript-to-Python translation to flat `if`/`else if`/`else` chains with print-only branch bodies; preserve branch ordering, reject nested control flow and unsupported expressions, and verify generated Python syntax and runtime output.

- [x] T142 Support JavaScript `&&`, `||`, and unary `!` in scalar conditions with JavaScript-compatible short-circuit precedence and scalar truthiness; validate both true and false branch outcomes against generated Python runtime output.

- [x] T143 Add a constrained deterministic Go-to-Python translator for a single root `main.go`, with CLI integration, scalar type checks, signed-64-bit arithmetic guards, and syntax/runtime regression tests.

- [x] T144 Extend Go-to-Python translation with boolean `if`/`else` and statically bounded C-style `for` loops; reject unsupported/nested control flow, unsafe bounds, arithmetic on dynamic loop variables, and scope leaks.

- [x] T145 Add constrained TypeScript-to-Python deterministic migration for a single root `main.ts`, validate `number`/`string`/`boolean` annotations, reject unsupported module/type syntax, and add CLI plus runtime regression tests.

- [x] T146 Add end-to-end deterministic behavior-equivalence tests for Python ↔ Go and Python ↔ TypeScript: execute both original and generated artifacts, compile Go/TypeScript outputs where applicable, and compare stdout. Expanded beyond arithmetic to string/boolean formatting, branching, and bounded loops in PR #104. Evidence remains limited to these explicit fixtures and does not establish general pair/project equivalence.

- [x] T147 Expand migration orchestration contract coverage to every directed non-identity pair in the registered language catalog; separately track deterministic translator support, AI-assisted experimental support, and proven semantic equivalence so registry coverage is never mistaken for production migration coverage. Verified in PR #102: 156 directed routes, duplicate/missing-pair assertions, and separate coverage documentation; this does not claim semantic equivalence.

- [x] T148 Add a fail-closed deterministic JavaScript-to-Go adapter by composing the validated JavaScript-to-Python and Python-to-Go subsets, normalize only the generated print-argument form, reject boolean output where casing would diverge, add CLI/runtime tests, and document that this is a single-file subset rather than full-project support. The latest verified branch CI passed on Python 3.11, 3.12, and 3.13 and all configured language-specific E2E jobs; broader parser/generator coverage remains open under T023.

- [x] T149 Add a fail-closed deterministic Go-to-JavaScript adapter by composing the Go-to-Python and Python-to-JavaScript subsets, normalize only generated print expansion, reject unsupported boolean literals and multi-file inputs, add CLI and runtime equivalence tests, and validate the route with a dedicated Go/Node CI job. This remains a single-file subset.

- [x] T150 Add a fail-closed deterministic Go-to-TypeScript adapter by composing the Go-to-Python and Python-to-TypeScript subsets, normalize only generated print expansion, reject unsupported boolean literals and multi-file inputs, add CLI and runtime equivalence tests, and validate with strict TypeScript compilation and Node runtime output comparison in CI. This remains a single-file subset; T023 remains open.

- [x] T151 Add a fail-closed deterministic JavaScript-to-C# adapter by composing the JavaScript-to-Python and Python-to-C# subsets, normalize only generated print expansion, exclude boolean literals to avoid cross-runtime formatting drift, add CLI and real Node/.NET stdout-equivalence tests, and validate through the dedicated C# CI job. This remains a single-file subset; C# → JavaScript is still not deterministic support.

- [x] T152 Add a fail-closed deterministic Go-to-C# adapter by composing the Go-to-Python and Python-to-C# subsets, normalize only the generated print expansion AST, intentionally exclude boolean literals, add CLI and real Go/.NET stdout-equivalence tests, and validate in the C# CI job with pinned Go and .NET SDKs. This remains a single-file subset; T023 remains open.

- [x] T153 Add a fail-closed deterministic JavaScript-to-TypeScript adapter by composing the checked JavaScript-to-Python and Python-to-TypeScript subsets, normalize only generated print expansion, add CLI integration and strict TypeScript/Node runtime-equivalence fixtures for arithmetic, multi-argument output, booleans, branches, and bounded loops; keep single-file and subset limitations explicit. T023 remains open.

- [x] T154 Add a fail-closed deterministic TypeScript-to-JavaScript adapter by composing the validated TypeScript-to-Python and Python-to-JavaScript subsets, normalize only generated multi-argument print expansion, add CLI integration and runtime comparison against compiled TypeScript for arithmetic, booleans, multi-argument output, branches, and bounded loops; document the root-main.ts single-file boundary. T023 remains open.

- [x] T156 Add a fail-closed deterministic Go-to-PHP adapter by composing Go-to-Python and Python-to-PHP, normalize only the generated print expansion, reject booleans when output casing would drift, and add Go/PHP runtime-equivalence plus CLI tests in CI. This is a single-file subset and does not establish full project migration.

- [x] T155 Add a fail-closed deterministic TypeScript-to-Go adapter composed from the checked TypeScript-to-Python and Python-to-Go subsets, normalize only generated multi-argument print expansion, reject boolean output drift, and add strict TypeScript/Node/Go runtime-equivalence and CLI tests. This is a single-file subset; full project migration remains open.

- [x] T157 Add a fail-closed deterministic Go-to-Rust adapter composed from the checked Go-to-Python and Python-to-Rust subsets, normalize only generated multi-argument print expansion, reject boolean output drift, and add offline Go/Cargo runtime-equivalence plus CLI tests. This is a single-file subset; full project migration remains open.

- [x] T158 Add a fail-closed deterministic JavaScript-to-Rust adapter composed from the checked JavaScript-to-Python and Python-to-Rust subsets, normalize only generated multi-argument print expansion, reject boolean output drift, and add Node/Rust runtime-equivalence plus CLI tests. This is a single-file subset; full project migration remains open.

- [x] T159 Add a fail-closed deterministic TypeScript-to-Rust adapter composed from the checked TypeScript-to-Python and Python-to-Rust subsets, normalize only generated multi-argument print expansion, reject boolean output drift, and add strict TypeScript/Node/Rust runtime-equivalence plus CLI tests. This is a single-file subset; full project migration remains open.

- [x] T160 Add a fail-closed deterministic TypeScript-to-C# adapter composed from the checked TypeScript-to-Python and Python-to-C# subsets, normalize only generated multi-argument print expansion, reject boolean output drift, and add strict TypeScript/Node/.NET runtime-equivalence plus CLI tests. This is a single-file subset; full project migration remains open.

- [x] T161 Add a fail-closed deterministic JavaScript-to-PHP adapter composed from the checked JavaScript-to-Python and Python-to-PHP subsets, normalize only generated multi-argument print expansion, reject boolean output drift, and add Node/PHP runtime-equivalence plus CLI tests. This is a single-file subset; full project migration remains open.


- [x] T162 Add a fail-closed deterministic TypeScript-to-PHP adapter composed from the checked TypeScript-to-Python and Python-to-PHP subsets, normalize only the generated multi-argument print expansion, reject boolean output drift and multi-file inputs, and add strict TypeScript/Node/PHP runtime-equivalence plus CLI tests. This is a single-file subset; full project migration remains open.

- [x] T163 Add a fail-closed deterministic JavaScript-to-Java adapter composed from the checked JavaScript-to-Python and Python-to-Java subsets, normalize only generated multi-argument print expansion, reject boolean output drift, and add Node/JDK runtime-equivalence plus CLI tests. This is a single-file subset; full project migration remains open.

- [x] T164 Add a fail-closed deterministic JavaScript-to-Kotlin adapter composed from the checked JavaScript-to-Python and Python-to-Kotlin subsets, normalize only generated multi-argument print expansion, reject boolean output drift, and add Node/Kotlin runtime-equivalence plus CLI tests. This is a single-file subset; full project migration remains open.

- [x] T165 Add a fail-closed deterministic TypeScript-to-Java adapter composed from the checked TypeScript-to-Python and Python-to-Java subsets, normalize only generated multi-argument print expansion, reject boolean literals and boolean-valued output expressions, and add strict TypeScript/Node/JDK runtime-equivalence plus CLI tests. This is a single-file subset; full project migration remains open.

- [ ] T166 Add a fail-closed deterministic TypeScript-to-Kotlin adapter composed from the checked TypeScript-to-Python and Python-to-Kotlin subsets, normalize only generated multi-argument print expansion, reject boolean output drift and multi-file inputs, and add strict TypeScript/Node/Kotlin runtime-equivalence plus CLI tests. This is a single-file subset; full project migration remains open.

- [ ] T169 Add a fail-closed deterministic Go-to-Swift adapter composed from the checked Go-to-Python and Python-to-Swift subsets, normalize only generated multi-argument print expansion, reject boolean output drift and multi-file inputs, and add strict Go/Swift runtime-equivalence plus CLI tests. This is a single-file subset; full project migration remains open.

- [ ] T170 Add a fail-closed deterministic Go-to-Ruby adapter composed from the checked Go-to-Python and Python-to-Ruby subsets, normalize only generated multi-argument print expansion, reject boolean output drift and multi-file inputs, and add strict Go/Ruby runtime-equivalence plus CLI tests. This is a single-file subset; full project migration remains open.

- [ ] T171 Add a fail-closed deterministic Go-to-C++ adapter composed from the checked Go-to-Python and Python-to-C++ subsets, normalize only generated multi-argument print expansion, reject boolean output drift and multi-file inputs, and add strict Go/C++ runtime-equivalence plus CLI tests. This is a single-file subset; full project migration remains open.

- [ ] T172 Add a fail-closed deterministic Go-to-C adapter composed from the checked Go-to-Python and Python-to-C subsets, normalize only generated multi-argument print expansion, reject boolean output drift and multi-file inputs, and add strict Go/C runtime-equivalence plus CLI tests. This is a single-file subset; full project migration remains open.

- [ ] T173 Add a fail-closed deterministic JavaScript-to-C adapter composed from the checked JavaScript-to-Python and Python-to-C subsets, normalize only generated multi-argument console output, reject boolean output drift and multi-file inputs, and add strict Node/C runtime-equivalence plus CLI tests. This is a single-file subset; full project migration remains open.

- [ ] T174 Add a fail-closed deterministic JavaScript-to-C++ adapter composed from the checked JavaScript-to-Python and Python-to-C++ subsets, normalize only generated multi-argument console output, reject boolean output drift and multi-file inputs, and add strict Node/C++ runtime-equivalence plus CLI tests. This is a single-file subset; full project migration remains open.

- [ ] T175 Add a fail-closed deterministic JavaScript-to-Ruby adapter composed from the checked JavaScript-to-Python and Python-to-Ruby subsets, normalize only generated multi-argument console output, reject boolean output drift and multi-file inputs, and add strict Node/Ruby runtime-equivalence plus CLI tests. This is a single-file subset; full project migration remains open.
