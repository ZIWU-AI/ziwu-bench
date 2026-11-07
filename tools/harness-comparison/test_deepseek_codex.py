import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import AsyncMock, patch

from harbor.agents.factory import AgentFactory
from harbor.agents.installed.codex import Codex
from harbor.models.trial.config import AgentConfig

from deepseek_codex import (
    API_BASE, CATALOG_PATH, CONTEXT_TOKENS, DeepSeekCodex,
    REMOTE_CATALOG, VERSION, build_route, catalog_content,
)


class DeepSeekRouteTests(unittest.TestCase):
    def test_official_catalog_and_container_path_are_wired_without_credentials(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "synthetic-do-not-copy"}):
                route = build_route(td)
            config = tomllib.loads(Path(route["kwargs"]["config"]).read_text())
            self.assertEqual(config["model_catalog_json"], REMOTE_CATALOG)
            self.assertNotIn(td, config["model_catalog_json"])
            self.assertEqual(config["model_context_window"], CONTEXT_TOKENS)
            self.assertEqual(config["model_auto_compact_token_limit"], 943718)
            self.assertEqual(config["web_search"], "disabled")
            provider = config["model_providers"]["deepseek_official"]
            self.assertEqual(provider["base_url"], API_BASE)
            self.assertEqual(provider["wire_api"], "responses")
            self.assertFalse(provider["supports_websockets"])
            self.assertEqual(provider["env_key"], "OPENAI_API_KEY")
            self.assertEqual(route["credential_env_names"], ["OPENAI_API_KEY"])
            self.assertNotIn("synthetic-do-not-copy", json.dumps(route) + json.dumps(config) + catalog_content())

    def test_catalog_preserves_model_instructions_and_only_requested_model(self):
        catalog = json.loads(catalog_content())
        self.assertEqual([m["slug"] for m in catalog["models"]], ["deepseek-flash"])
        model = catalog["models"][0]
        self.assertEqual(model["input_modalities"], ["text", "image"])
        self.assertEqual(model["apply_patch_tool_type"], "freeform")
        self.assertTrue(model["base_instructions"])
        self.assertTrue(model["model_messages"]["instructions_template"])

    def test_harbor_factory_accepts_route_and_rejects_unpinned_client(self):
        with tempfile.TemporaryDirectory() as td:
            route = build_route(td)
            config = AgentConfig(import_path=route["import_path"], model_name=route["model_name"],
                                 kwargs=route["kwargs"], env=route["env"])
            agent = AgentFactory.create_agent_from_config(config, logs_dir=Path(td)/"logs")
            self.assertIsInstance(agent, DeepSeekCodex)
            self.assertEqual(agent.version(), VERSION)
            config.kwargs["version"] = "latest"
            with self.assertRaisesRegex(ValueError, "requires"):
                AgentFactory.create_agent_from_config(config, logs_dir=Path(td)/"other")


class CatalogUploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_setup_uploads_catalog_after_native_setup(self):
        with tempfile.TemporaryDirectory() as td:
            route = build_route(td)
            agent = DeepSeekCodex(logs_dir=Path(td)/"logs", model_name=route["model_name"],
                                 extra_env=route["env"], **route["kwargs"])
            agent._upload_config_text = AsyncMock()
            environment = object()
            with patch.object(Codex, "setup", new_callable=AsyncMock) as native_setup:
                await agent.setup(environment)
            native_setup.assert_awaited_once_with(environment)
            agent._upload_config_text.assert_awaited_once_with(
                environment, content=CATALOG_PATH.read_text(), remote_path=REMOTE_CATALOG,
                filename="deepseek-model-catalog.json",
            )


if __name__ == "__main__":
    unittest.main()
