# Security Policy

## Current security posture

PolyMigrate is an early-stage research foundation. The experimental migration command sends source files to the selected provider only when the caller explicitly supplies the --allow-source-upload flag. Recognizable credential patterns are redacted on a best-effort basis; this is not a guarantee that all secrets are detected.

Generated code is untrusted. Optional validation runs only in a locally available, explicitly configured Docker image, without network access, with a read-only container root filesystem, dropped capabilities, resource limits, and only the generated workspace mounted. Images are never pulled automatically. Docker is not a perfect isolation boundary; use a disposable VM or stronger sandbox for hostile projects and do not expose a privileged/shared Docker daemon to untrusted workloads.

The Graphify adapter queries an existing local graph through an argument list and does not invoke a shell. Graph-derived context can be included in prompts to the selected provider when source upload is explicitly enabled.

Migration draft caching is disabled by default. If enabled, the local SQLite database can contain generated code. Unverified drafts are scoped to the same project and are never shared across projects. Only verified, explicitly shareable knowledge records can be reused across projects.

The current CLI does not deploy to production and does not claim behavior equivalence. Review migration-review.json; any gate marked NOT_RUN is not evidence of correctness.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting for this repository if it is enabled. Avoid posting credentials, exploit payloads, or sensitive project code in public issues.
