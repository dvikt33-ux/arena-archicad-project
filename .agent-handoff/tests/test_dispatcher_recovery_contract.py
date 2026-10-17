"""Check dispatcher CDP recovery and durable-state fail-stop contracts.

Offline source assertions; these do not manipulate Chrome or the live queue.
"""
import ast
import unittest
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / "dispatcher.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)

def function_body(name):
    matches = [node for node in TREE.body
               if isinstance(node, ast.FunctionDef) and node.name == name]
    assert len(matches) == 1
    return ast.get_source_segment(SOURCE, matches[0])

class RecoveryContracts(unittest.TestCase):
    def test_invalid_queue_before_connecting_opera(self):
        body = function_body("watch")
        self.assertLess(body.index("state = load_state()"),
                        body.index("require_opera_cdp()"))

    def test_queue_write_failure_is_fatal(self):
        body = function_body("watch")
        self.assertIn("except DispatcherStateWriteError:", body)
        self.assertIn("raise", body[body.index("except DispatcherStateWriteError:"):
                                      body.index("except GitHubNetworkError:")])
        self.assertLess(body.index("except DispatcherStateWriteError:"),
                        body.index("except Exception as exc:"))

    def test_durable_save_fsync_before_replace(self):
        body = function_body("save_state")
        self.assertLess(body.index("os.fsync("), body.index("os.replace("))
        self.assertIn('raise DispatcherStateWriteError("STATE_WRITE_FAILED_STOP")',body)

    def test_github_network_does_not_restart_cdp(self):
        body = function_body("watch")
        section=body[body.index("except GitHubNetworkError:"):
                     body.index("except GitHubSignalError:")]
        self.assertNotIn("require_opera_cdp",section)
        self.assertNotIn("browser = None",section)

    def test_ui_timeout_does_not_restart_cdp(self):
        body = function_body("watch")
        section=body[body.index("except PlaywrightTimeoutError as exc:"):
                     body.index("except RuntimeError as exc:")]
        self.assertNotIn("start_service_chrome",section)
        self.assertNotIn("browser = None",section)

    def test_unknown_cdp_failure_does_not_restart_user_opera(self):
        body=function_body("watch")
        self.assertIn("browser = None",body)
        self.assertIn("require_opera_cdp()",body)
        self.assertIn("p.chromium.connect_over_cdp(CDP)",body)
        self.assertNotIn("start_service_chrome",body)
        self.assertNotIn("stop_owned_chrome",body)
        self.assertNotIn("subprocess.Popen",body)
        self.assertNotIn("force=",body)

    def test_attach_only_probe_has_no_browser_creation(self):
        body=function_body("require_opera_cdp")
        self.assertIn("cdp_http_ready()",body)
        self.assertIn("opera_owns_cdp_port()",body)
        self.assertNotIn("subprocess.Popen",body)
        self.assertNotIn("start_service_chrome",SOURCE)
        self.assertNotIn("CHROME_PATH",SOURCE)

if __name__ == "__main__":
    unittest.main()
