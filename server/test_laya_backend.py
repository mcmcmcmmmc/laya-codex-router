"""Adapter contract without model downloads or paid inference."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import jev_server as server
import laya_backend as backend
from routing_policy import ROUTE_PAIRS


class LayaBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name) / "backend"
        path.write_text("laya", encoding="utf-8")
        patch = mock.patch.object(server, "BACKEND_PATH", str(path))
        patch.start()
        self.addCleanup(patch.stop)

    def test_no_key_or_external_api_needed(self):
        with mock.patch.object(backend, "predict", return_value={"answers": {}}) as local:
            with mock.patch.object(server, "call_jev") as remote:
                key = server.load_key()
                server.call_jev_routed(key, {"task": "test"})
                local.assert_called_once_with({"task": "test"}, None)
                remote.assert_not_called()

    def test_laya_is_the_default_backend(self):
        missing = Path(self.tmp.name) / "missing-backend-file"
        with mock.patch.object(server, "BACKEND_PATH", str(missing)):
            self.assertEqual(server.decision_backend(), "laya")

    def test_joint_contract_is_preserved(self):
        self.assertEqual(set(backend._labels.values()), set(ROUTE_PAIRS))
        self.assertEqual(set(backend.QUESTIONS["route"]["criteria"]), set(backend._labels))

    def test_header_identifies_engine_and_fallback_and_is_removed_on_replay(self):
        with mock.patch.object(server.os.path, "exists", return_value=False):
            for gate in ("apply", "laya_error:RuntimeError", "codex_dry(retry):gpt-6-astra"):
                header = server.answer_signature({
                    "model": server.ASTRA, "effort": "medium", "gate": gate})
                self.assertIn("Laya local" if gate == "apply" else "Laya fallback", header)
                payload = {"input": [{"role": "assistant", "content": header + "answer"}]}
                self.assertEqual(server.strip_signatures(payload), 1)
                self.assertEqual(payload["input"][0]["content"], "answer")
