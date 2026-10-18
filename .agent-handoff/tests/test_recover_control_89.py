"""Read-only/static safety invariants for pending turn 89 Opera repair."""
import unittest
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "recover-control-89.ps1").read_text(encoding="ascii")

class RecoverTurn89(unittest.TestCase):
    def test_single_expected_queue_and_source(self):
        for marker in (
            "[int]$s.last_turn_id -ne 88",
            "[int]$s.inflight.turn_id -ne 89",
            "[string]$s.inflight.target -ne 'GPT'",
            "!$s.inflight.terminal_report",
            "[bool]$s.inflight.submitted",
            "[bool]$s.inflight.send_intent",
            "[int]$s.inflight.send_attempts -gt 0",
            "ea2eb306a4159a8f4e9244cc630a403e495bf02c",
            "OPERA_E2E_SMOKE_88_RECEIVED",
            "45270c1a55c98fd70a88d0d8a66f8fb363a92e0a",
        ):
            self.assertIn(marker, SRC)

    def test_no_github_writes_no_manual_wakes_no_chrome(self):
        for forbidden in ("Invoke-RestMethod -Method Put", "git push", "ARENA-ПУСК",
                          "GPT-ПУСК", "chrome.exe", "Stop-Process -Name opera"):
            self.assertNotIn(forbidden.lower(), SRC.lower())
        self.assertIn("CheckQueue", SRC)
        self.assertIn("BrowserPort", SRC)
        self.assertIn("--user-data-dir=", SRC)
        self.assertIn("--remote-debugging-address=127.0.0.1", SRC)
        self.assertIn("Documents\\arena-archicad-project", SRC)

    def test_safely_update_both_cores_and_restart(self):
        self.assertIn(".pre-control89-", SRC)
        self.assertIn("Get-NetTCPConnection -LocalPort 9224", SRC)
        self.assertIn("$req.Proxy = $null", SRC)
        self.assertIn("Get-Content (Join-Path $HOME 'ai-dispatcher.log')", SRC)
        self.assertIn("Start-Process -FilePath ([string]$python).Trim()", SRC)
        self.assertIn("no GitHub signal written", SRC)

if __name__ == "__main__":
    unittest.main()
