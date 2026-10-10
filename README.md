# PolyMigrate

PolyMigrate is an early-stage, provider-agnostic foundation for autonomous cross-language software migration. It combines a spec-driven workflow, language adapters, AI provider interfaces, reusable migration knowledge, Graphify integration points, and automated validation.

## Project status

This repository is in foundation development. It currently focuses on migration planning and supporting infrastructure; it does not yet perform general-purpose end-to-end source-code migration. Provider adapters and Graphify integration must be validated in the target environment before being considered production-ready.

## Development

The reference implementation is Python 3.11+ and uses the standard library for runtime components. Install development tools as needed, then run:

```bash
python -m compileall -q src tests
python -m unittest discover -s tests -v
```

See `specs/001-foundation/` for the specification, design, and implementation tasks.

## Security and correctness

Migration work must run in an isolated workspace, preserve the source project, validate generated output, and report unresolved issues rather than claiming success without evidence. Cross-project knowledge reuse is opt-in and must be gated by validation evidence.

## License

MIT. See `LICENSE`.
