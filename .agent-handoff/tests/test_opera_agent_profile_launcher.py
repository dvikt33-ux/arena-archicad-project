"""Offline contracts for one-time isolated Opera agent profile activation."""
import unittest
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parents[1] /
          "start-opera-agent-profile.ps1").read_text(encoding="ascii")


class OperaAgentLauncher(unittest.TestCase):
    def test_only_opera_and_loopback_port(self):
        self.assertIn("'--remote-debugging-port=9224'", SCRIPT)
        self.assertIn("'--remote-debugging-address=127.0.0.1'", SCRIPT)
        self.assertIn("--user-data-dir=", SCRIPT)
        self.assertIn("AI-Dispatcher\\Opera-Agent-Profile", SCRIPT)
        self.assertIn("'127.0.0.1','::1'", SCRIPT)
        self.assertNotIn("chrome.exe", SCRIPT.lower())
        self.assertNotIn("Stop-Process", SCRIPT)
        self.assertNotIn("taskkill", SCRIPT.lower())
        self.assertNotIn("copy-item", SCRIPT.lower())

    def test_existing_turn_is_never_repushed(self):
        self.assertIn("[int]$state.inflight.turn_id -ne 88", SCRIPT)
        self.assertIn("[bool]$state.inflight.submitted", SCRIPT)
        self.assertIn("[bool]$state.inflight.send_intent", SCRIPT)
        self.assertIn("send_attempts", SCRIPT)
        self.assertIn("'c82202ac54bcd9675bd5786d5f12f784ac6a5c27'", SCRIPT)
        self.assertIn("$doc.sha -ne $signalBlob", SCRIPT)
        self.assertNotIn("Invoke-RestMethod -Method Put", SCRIPT)
        self.assertNotIn("git push", SCRIPT.lower())

    def test_http_debugger_probe_retries_and_bypasses_proxy(self):
        self.assertIn("$request.Proxy = $null", SCRIPT)
        self.assertIn("$request.Timeout = 2000", SCRIPT)
        self.assertIn("HTTP_OK_NO_VALID_BROWSER_WEBSOCKET", SCRIPT)
        self.assertIn("OPERA_CDP_WAIT_FAILED", SCRIPT)
        self.assertIn("OPERA_CDP_NOT_READY", SCRIPT)
        self.assertIn("for($attempt=0; $attempt -lt 24; $attempt++)", SCRIPT)
        self.assertIn("if ($verified) { break }", SCRIPT)
        self.assertNotIn("Invoke-RestMethod -UseBasicParsing -TimeoutSec 3 -Uri 'http://127.0.0.1:9224/json/version'", SCRIPT)

    def test_original_control_and_arena_are_the_only_opened_pages(self):
        self.assertIn("6ad27341-1ea4-83eb-8238-5ce1cada094a", SCRIPT)
        self.assertIn("01a09014-9139-71e7-b51b-5b3f8a49d904", SCRIPT)
        self.assertNotIn("user-data-dir=$env:APPDATA", SCRIPT)
        self.assertIn("Sign in to ChatGPT and Arena", SCRIPT)


if __name__ == "__main__":
    unittest.main()
