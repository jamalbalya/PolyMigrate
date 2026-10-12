# Language-pair coverage

## Language catalog

The current registry contains 13 language IDs:

`c`, `cpp`, `csharp`, `go`, `java`, `javascript`, `kotlin`, `php`, `python`, `ruby`, `rust`, `swift`, and `typescript`.

There are 156 directed non-identity pairs in this catalog (13 source choices × 12 different targets). A pair such as Go → JavaScript is distinct from JavaScript → Go; testing one direction does not validate the reverse.

## Three separate levels of support

1. **Orchestration route exists** — the experimental LLM strategy can construct a request for a registered source/target pair, map the target file extension, and isolate generated output. The deterministic fake-provider matrix tests only this contract. It does not assess generated code correctness.
2. **Deterministic subset exists** — a handwritten translator supports a documented subset for that particular direction. Unsupported syntax must fail closed. This is narrower than full language support.
3. **Behavioral migration is proven** — real source and generated target programs compile/run under their actual toolchains, tests and behavior contracts pass, dependencies and manifests are resolved, security evidence is complete, and the report reflects all required gates. This must be established per pair and representative project type.

Passing level 1 must never be described as passing levels 2 or 3. Live provider behavior also requires explicitly configured credentials and must not be inferred from mocked tests.

## Current deterministic directions (not complete language support)

- Python → Go
- Go → Python
- Python → JavaScript
- JavaScript → Python
- Python → TypeScript
- TypeScript → Python
- Python → Java
- Python → Kotlin
- Python → C
- Python → C++
- Python → C#
- Python → PHP
- Python → Rust
- Python → Ruby
- Python → Swift

Each implementation remains bounded by its own documented syntax and project-shape constraints. Every other directed pair is not automatically a deterministic translation merely because the LLM orchestration path exists.

## Required next validation

- Keep a test covering every directed pair in the current registry.
- Add real runtime equivalence fixtures by language family and pair, including Go → JavaScript, JavaScript → C#, and their reverse directions when the implementation can support them safely.
- Record required compiler/runtime availability and explicit skips; do not count skipped toolchain tests as passes.
- Validate multi-file projects, project manifests, dependency/API substitutions, tests, behavior, security, and autonomous repair before claiming broad project migration.
- Grow the deterministic pair coverage only with focused parsers/generators and differential tests; do not silently route an unsupported deterministic pair through a generic generator.
