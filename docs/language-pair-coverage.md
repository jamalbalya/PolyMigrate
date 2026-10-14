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
- JavaScript → Go (composed bounded JavaScript → Python → Go subset)
- JavaScript → C# (composed bounded JavaScript → Python → C# subset)
- JavaScript → TypeScript (composed bounded JavaScript → Python → TypeScript subset)
- JavaScript → Rust (composed bounded JavaScript → Python → Rust subset)
- Go → Python
- Go → JavaScript (composed bounded Go → Python → JavaScript subset)
- Go → TypeScript (composed bounded Go → Python → TypeScript subset)
- Go → C# (composed bounded Go → Python → C# subset)
- Go → PHP (composed bounded Go → Python → PHP subset)
- Go → Rust (composed bounded Go → Python → Rust subset)
- Python → JavaScript
- JavaScript → Python
- Python → TypeScript
- TypeScript → Python
- TypeScript → JavaScript (composed bounded TypeScript → Python → JavaScript subset)
- TypeScript → Go (composed bounded TypeScript → Python → Go subset)
- TypeScript → Rust (composed bounded TypeScript → Python → Rust subset)
- TypeScript → C# (composed bounded TypeScript → Python → C# subset)
- Python → Java
- Python → Kotlin
- Python → C
- Python → C++
- Python → C#
- Python → PHP
- Python → Rust
- Python → Ruby
- Python → Swift

Each implementation remains bounded by its own documented syntax and project-shape constraints. In the current registry, 28 of the 156 directions have a deterministic subset listed above; the remaining 128 directions have only the experimental LLM orchestration route and must not be presented as deterministic support or proven migrations. Every direction still needs pair-specific behavioral and project-level evidence.

## Required next validation

- Keep a test covering every directed pair in the current registry.
- Add real runtime equivalence fixtures by language family and pair, including C# → JavaScript and its reverse direction when the implementation can support it safely.
- Record required compiler/runtime availability and explicit skips; do not count skipped toolchain tests as passes.
- Validate multi-file projects, project manifests, dependency/API substitutions, tests, behavior, security, and autonomous repair before claiming broad project migration.
- Grow the deterministic pair coverage only with focused parsers/generators and differential tests; do not silently route an unsupported deterministic pair through a generic generator.
