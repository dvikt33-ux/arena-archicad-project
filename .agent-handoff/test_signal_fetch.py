"""Dispatcher signal-fetch tests. No network and no Playwright."""
from __future__ import annotations

import ast
import base64
import http.client
import json
import socket
import ssl
import urllib.error
import urllib.request
from pathlib import Path

CORE = Path(__file__).with_name("dispatcher.py")

WANTED = {
    "_is_network_exception",
    "parse_signal",
    "parse_signal_text",
    "parse_api_contents",
    "_signal_request",
    "_read_response",
    "fetch_signal",
}


def load_fetchers():
    tree = ast.parse(CORE.read_text(encoding="utf-8"))
    keep = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if names and names[0] in {
                "VERSION",
                "SIGNAL_URL",
                "SIGNAL_API_URL",
                "SIGNAL_FETCH_TIMEOUT",
                "CHECK_INTERVAL",
            }:
                keep.append(node)
        elif isinstance(node, ast.ClassDef) and node.name in {"GitHubNetworkError", "GitHubSignalError"}:
            keep.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in WANTED:
            keep.append(node)
    logs: list[str] = []
    ns = {
        "base64": base64,
        "json": json,
        "time": __import__("time"),
        "urllib": urllib,
        "http": http,
        "ssl": ssl,
        "socket": socket,
        "PlaywrightTimeoutError": type("PlaywrightTimeoutError", (Exception,), {}),
        "log": logs.append,
    }
    exec(compile(ast.Module(keep, []), str(CORE), "exec"), ns)
    ns["logs"] = logs
    return ns


class Response:
    def __init__(self, payload: bytes):
        self.payload = payload

    def read(self) -> bytes:
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *args) -> bool:
        return False


class Opener:
    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[tuple[str, float]] = []

    def __call__(self, req: urllib.request.Request, timeout: float):
        url = req.full_url
        self.calls.append((url, timeout))
        host = "api" if "api.github.com" in url else "raw"
        spec = self.routes[host]
        if isinstance(spec, Exception):
            raise spec
        return Response(spec)


def signal_bytes(**overrides) -> bytes:
    data = {
        "protocol": 1,
        "turn_id": 36,
        "target": "ARENA",
        "source": "GPT",
        "status": "ready",
        "message": "SECRET-TURN-BODY",
    }
    data.update(overrides)
    return json.dumps(data).encode("utf-8")


def api_bytes(payload: bytes, content: str | None = None, encoding: str = "base64") -> bytes:
    encoded = content if content is not None else base64.b64encode(payload).decode("ascii")
    encoded = "\n".join(encoded[i : i + 60] for i in range(0, len(encoded), 60))
    return json.dumps({"encoding": encoding, "content": encoded}).encode("utf-8")


def main() -> None:
    ns = load_fetchers()
    assert ns["VERSION"] == "2.2.14"
    assert ns["CHECK_INTERVAL"] == 5
    assert ns["SIGNAL_FETCH_TIMEOUT"] == 8
    assert "api.github.com" in ns["SIGNAL_API_URL"]
    assert "ref=agent-handoff" in ns["SIGNAL_API_URL"]
    assert ".agent-handoff/signal.json" in ns["SIGNAL_API_URL"]
    fetch_fn = next(
        node
        for node in ast.parse(CORE.read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef) and node.name == "fetch_signal"
    )
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "sleep" for node in ast.walk(fetch_fn))
    source = CORE.read_text(encoding="utf-8")
    assert "except GitHubSignalError:" in source
    assert "CDP не перезапускаю." in source

    opener = Opener({"raw": signal_bytes()})
    got = ns["fetch_signal"](opener=opener)
    assert got["turn_id"] == 36
    assert got["target"] == "ARENA"
    assert got["message"] == "SECRET-TURN-BODY"
    assert len(opener.calls) == 1
    assert opener.calls[0][0].startswith(ns["SIGNAL_URL"])
    assert opener.calls[0][1] == 8
    assert not any("SECRET-TURN-BODY" in line for line in ns["logs"])

    ns["logs"].clear()
    opener = Opener({
        "raw": urllib.error.URLError("timed out"),
        "api": api_bytes(signal_bytes(turn_id=37)),
    })
    got = ns["fetch_signal"](opener=opener)
    assert got["turn_id"] == 37
    assert [host for host, _ in (("raw", opener.calls[0][0]), ("api", opener.calls[1][0]))]
    assert "raw.githubusercontent.com" in opener.calls[0][0]
    assert opener.calls[1][0] == ns["SIGNAL_API_URL"]
    assert any(line == "GITHUB: endpoint=raw error=URLError" for line in ns["logs"])
    assert any(line == "GITHUB: endpoint=api ok" for line in ns["logs"])
    assert not any("SECRET-TURN-BODY" in line or "timed out" in line for line in ns["logs"])

    ns["logs"].clear()
    opener = Opener({"raw": b"not-json", "api": api_bytes(signal_bytes())})
    try:
        ns["fetch_signal"](opener=opener)
    except ns["GitHubSignalError"] as exc:
        assert str(exc) == "signal_json_invalid"
    else:
        raise AssertionError("malformed raw json was accepted")
    assert len(opener.calls) == 1

    malformed = {
        "api_json": b"{",
        "api_base64": api_bytes(b"", content="!!!!"),
        "api_inner_json": api_bytes(b"not-json"),
        "api_object": api_bytes(b"[]"),
    }
    expected = {
        "api_json": "api_json_invalid",
        "api_base64": "api_base64_invalid",
        "api_inner_json": "signal_json_invalid",
        "api_object": "signal_not_object",
    }
    for name, payload in malformed.items():
        opener = Opener({"raw": urllib.error.URLError("down"), "api": payload})
        try:
            ns["fetch_signal"](opener=opener)
        except ns["GitHubSignalError"] as exc:
            assert str(exc) == expected[name], (name, exc)
        else:
            raise AssertionError(f"{name} was accepted")
        assert len(opener.calls) == 2

    opener = Opener({
        "raw": urllib.error.URLError("raw down"),
        "api": urllib.error.URLError("api down"),
    })
    try:
        ns["fetch_signal"](opener=opener)
    except ns["GitHubNetworkError"] as exc:
        assert str(exc) == "github_endpoints_unavailable"
    else:
        raise AssertionError("double network failure was accepted")
    assert len(opener.calls) == 2
    assert all(timeout == 8 for _, timeout in opener.calls)

    print("test_signal_fetch: OK")


if __name__ == "__main__":
    main()
