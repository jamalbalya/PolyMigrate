"""Core contract tests for the PolyMigrate foundation."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from polymigrate.ai.protocols import ModelRequest, ModelResponse, ProviderCapabilities
from polymigrate.ai.registry import ProviderCapabilityError, ProviderRegistry
from polymigrate.agent.tools import AgentTool, ToolRegistry
from polymigrate.agent.runtime import AgentRuntime
from polymigrate.graph.graphify import GraphifyAdapter
from polymigrate.knowledge import KnowledgeRecord, MigrationKnowledgeStore, fingerprint_payload
from polymigrate.languages import Language, LanguageRegistry
from polymigrate.migration.library_resolution import rank_candidates
from polymigrate.models import Evidence, FinalReviewSummary, LibraryCandidate, MigrationRequest, MigrationStatus, ValidationResult
from polymigrate.planner import PlanningError, create_plan
from polymigrate.reporting import build_final_summary
from polymigrate.skills.registry import Skill, SkillRegistry


class FakeProvider:
    provider_id = "fake"
    def __init__(self, responses):
        self.responses = iter(responses)
    def get_capabilities(self):
        return ProviderCapabilities(structured_output=True, tool_calling=True)
    def generate(self, request: ModelRequest):
        return ModelResponse(next(self.responses), "fake", "fake-test-model")


class LanguageTests(unittest.TestCase):
    def test_registry_has_multiple_languages(self):
        registry = LanguageRegistry()
        self.assertTrue({"python", "go", "rust", "typescript"}.issubset({x.id for x in registry.all()}))
    def test_unknown_language_has_actionable_error(self):
        with self.assertRaisesRegex(ValueError, "Unsupported language"):
            LanguageRegistry().get("unknown")
    def test_duplicate_language_is_rejected(self):
        registry = LanguageRegistry()
        with self.assertRaises(ValueError):
            registry.register(Language("python", "Python", (".py",)))


class PlannerTests(unittest.TestCase):
    def test_plan_inventories_source_and_does_not_migrate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            root.mkdir()
            (root / "app.py").write_text("print('hello')", encoding="utf-8")
            out = Path(tmp) / "out"
            plan = create_plan(MigrationRequest(root, "python", "go", out))
            self.assertEqual(plan.source_file_count, 1)
            self.assertEqual(plan.source_files, ["app.py"])
            self.assertTrue(any("plan only" in warning for warning in plan.warnings))
            self.assertFalse(out.exists())
    def test_output_inside_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            root.mkdir()
            with self.assertRaises(PlanningError):
                create_plan(MigrationRequest(root, "python", "go", root / "output"))
    def test_graphify_missing_artifact_degrades_gracefully(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = GraphifyAdapter().load_artifact(Path(tmp))
            self.assertEqual(result.status, "unavailable")
            self.assertIsNotNone(result.warning)
    def test_graphify_valid_json_is_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "graphify-out" / "graph.json"
            artifact.parent.mkdir()
            artifact.write_text('{"nodes":[]}', encoding="utf-8")
            result = GraphifyAdapter().load_artifact(root)
            self.assertEqual(result.status, "available")
            self.assertEqual(result.data, {"nodes": []})


class ResolutionAndReportTests(unittest.TestCase):
    def test_library_candidates_are_ranked_by_score(self):
        candidates = [
            LibraryCandidate("low", "custom_implementation", .5, .5, .5, .5, .5),
            LibraryCandidate("high", "direct_replacement", .95, .9, .8, .9, .2,
                             (Evidence("test", "differential suite passed", True),)),
        ]
        ranked = rank_candidates(candidates)
        self.assertEqual(ranked[0].candidate.name, "high")
        self.assertTrue(ranked[0].evidence_verified)
    def test_invalid_strategy_is_rejected(self):
        with self.assertRaises(ValueError):
            rank_candidates([LibraryCandidate("bad", "magic", .5, .5)])
    def test_success_requires_mandatory_gates_and_no_risks(self):
        passed = [ValidationResult("build", True, "passed"), ValidationResult("tests", True, "passed")]
        self.assertEqual(build_final_summary("python", "go", passed).status, MigrationStatus.SUCCESS)
        self.assertEqual(build_final_summary("python", "go", passed, risks=["unverified behavior"]).status, MigrationStatus.PARTIAL)
    def test_failed_gate_never_reports_success(self):
        summary = build_final_summary("python", "go", [ValidationResult("build", False, "failed")])
        self.assertIn(summary.status, {MigrationStatus.PARTIAL, MigrationStatus.BLOCKED})


class ProviderAndAgentTests(unittest.TestCase):
    def test_provider_capability_is_enforced(self):
        registry = ProviderRegistry()
        registry.register(FakeProvider([]))
        result = registry.generate("fake", ModelRequest("test", "prompt", {}, require_tool_calling=True))
        self.assertEqual(result.provider_id, "fake")
    def test_tool_allowlist_blocks_unregistered_action(self):
        tools = ToolRegistry()
        with self.assertRaises(PermissionError):
            tools.execute("run_shell", {})
    def test_tool_result_must_be_json_serializable(self):
        tools = ToolRegistry()
        tools.register(AgentTool("read_source", "Read source", lambda _: object()))
        with self.assertRaises(ValueError):
            tools.execute("read_source", {})
    def test_agent_can_call_allowlisted_tool_then_finish(self):
        provider = FakeProvider([
            json.dumps({"action": "tool", "tool": "emit_report", "arguments": {"message": "done"}}),
            json.dumps({"action": "final", "result": {"summary": "complete"}}),
        ])
        providers = ProviderRegistry()
        providers.register(provider)
        tools = ToolRegistry()
        tools.register(AgentTool("emit_report", "Emit report", lambda args: {"message": args["message"]}))
        result = AgentRuntime(providers, tools, max_steps=3).run("fake", "test task", {})
        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(result.steps, 2)
        self.assertEqual(result.observations[0]["result"]["message"], "done")
    def test_agent_stops_at_step_limit(self):
        provider = FakeProvider([json.dumps({"action": "tool", "tool": "read_source", "arguments": {}})] * 3)
        providers = ProviderRegistry()
        providers.register(provider)
        tools = ToolRegistry()
        tools.register(AgentTool("read_source", "Read source", lambda _: {"ok": True}))
        result = AgentRuntime(providers, tools, max_steps=2).run("fake", "test", {})
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.steps, 2)


class KnowledgeAndSkillsTests(unittest.TestCase):
    def test_fingerprint_is_deterministic(self):
        self.assertEqual(fingerprint_payload({"a": 1, "b": 2}), fingerprint_payload({"b": 2, "a": 1}))
    def test_unverified_knowledge_is_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MigrationKnowledgeStore(Path(tmp) / "knowledge.sqlite")
            store.save(KnowledgeRecord("r1", "problem", "python", "go", "toolchain", "project-a",
                                       {"strategy": "adapter"}, (), False, True))
            found = store.find_reusable(problem_fingerprint="problem", source_language="python",
                                        target_language="go", toolchain_fingerprint="toolchain",
                                        project_scope="project-b")
            self.assertEqual(found, [])
    def test_verified_shared_knowledge_can_be_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MigrationKnowledgeStore(Path(tmp) / "knowledge.sqlite")
            store.save(KnowledgeRecord("r1", "problem", "python", "go", "toolchain", "project-a",
                                       {"strategy": "adapter"}, ({"test": "passed"},), True, True))
            found = store.find_reusable(problem_fingerprint="problem", source_language="python",
                                        target_language="go", toolchain_fingerprint="toolchain",
                                        project_scope="project-b")
            self.assertEqual(len(found), 1)
    def test_skill_cannot_expand_tool_permissions(self):
        registry = SkillRegistry()
        with self.assertRaisesRegex(ValueError, "outside the platform allowlist"):
            registry.register(Skill("unsafe", "1.0", "bad skill", (), (), ("run_shell",), ""))
    def test_duplicate_skill_is_rejected(self):
        registry = SkillRegistry()
        skill = Skill("safe-skill", "1.0", "safe", (), (), (), "")
        registry.register(skill)
        with self.assertRaises(ValueError):
            registry.register(skill)


if __name__ == "__main__":
    unittest.main()
