"""Agent runtime tests for skill injection, tool scoping, and bounded retries."""
import json
import unittest
from polymigrate.ai.protocols import ModelRequest, ModelResponse, ProviderCapabilities
from polymigrate.ai.registry import ProviderRegistry
from polymigrate.agent.runtime import AgentRuntime
from polymigrate.agent.tools import AgentTool, ToolRegistry
from polymigrate.skills.registry import Skill, SkillRegistry


class FakeProvider:
    provider_id="fake"
    def __init__(self,responses): self.responses=iter(responses); self.requests=[]
    def get_capabilities(self): return ProviderCapabilities()
    def generate(self,request:ModelRequest):
        self.requests.append(request)
        return ModelResponse(next(self.responses),"fake","test-model")


class AgentSkillTests(unittest.TestCase):
    def _registry(self, provider):
        providers=ProviderRegistry()
        providers.register(provider)
        return providers

    def test_skill_instructions_are_injected_and_tools_are_scoped(self):
        provider=FakeProvider([json.dumps({"action":"final","result":{"summary":"done"}})])
        tools=ToolRegistry()
        tools.register(AgentTool("search_package_registry","search",lambda args:{"ok":True}))
        tools.register(AgentTool("emit_report","report",lambda args:{"ok":True}))
        skills=SkillRegistry()
        skills.register(Skill("library-research","1.0","Research libraries",(),(),
                              ("search_package_registry",),"Search registry candidates before deciding."))
        result=AgentRuntime(self._registry(provider),tools,skills=skills).run("fake","resolve a missing library",{})
        prompt=provider.requests[0].prompt
        self.assertEqual(result.status,"SUCCESS")
        self.assertIn("Search registry candidates before deciding.",prompt)
        self.assertIn("search_package_registry",prompt)
        self.assertNotIn('"emit_report"',prompt)

    def test_tool_outside_active_skill_allowlist_is_not_executed(self):
        provider=FakeProvider([
            json.dumps({"action":"tool","tool":"emit_report","arguments":{"message":"done"}}),
            json.dumps({"action":"final","result":{"summary":"done"}}),
        ])
        calls=[]
        tools=ToolRegistry()
        tools.register(AgentTool("search_package_registry","search",lambda args:{"ok":True}))
        tools.register(AgentTool("emit_report","report",lambda args:calls.append(args) or {"ok":True}))
        skills=SkillRegistry()
        skills.register(Skill("library-research","1.0","Research libraries",(),(),
                              ("search_package_registry",),"Use package search."))
        result=AgentRuntime(self._registry(provider),tools,skills=skills).run("fake","research",{})
        self.assertEqual(result.status,"SUCCESS")
        self.assertEqual(calls,[])
        self.assertFalse(result.observations[0]["ok"])

    def test_repeated_model_failures_stop_before_max_step_limit(self):
        provider=FakeProvider(["not json","still not json","unused"])
        runtime=AgentRuntime(self._registry(provider),ToolRegistry(),max_steps=8,max_consecutive_model_errors=2)
        result=runtime.run("fake","test",{})
        self.assertEqual(result.status,"BLOCKED")
        self.assertEqual(result.steps,2)
        self.assertEqual(len(provider.requests),2)

    def test_unknown_skill_is_rejected_before_model_call(self):
        provider=FakeProvider([json.dumps({"action":"final","result":{}})])
        skills=SkillRegistry()
        runtime=AgentRuntime(self._registry(provider),ToolRegistry(),skills=skills)
        with self.assertRaisesRegex(KeyError,"Unknown skill"):
            runtime.run("fake","test",{},skill_ids=("missing",))
        self.assertEqual(provider.requests,[])

    def test_packaged_builtin_skills_load_from_installable_module_path(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]/"src"/"polymigrate"/"skills"/"builtin"
        loaded=SkillRegistry().load_directory(root)
        self.assertGreaterEqual(len(loaded),3)
        self.assertIn("library-replacement",{skill.id for skill in loaded})


if __name__ == "__main__":
    unittest.main()
