#!/usr/bin/env python3
"""Minimal MCP stdio client for Konnect, for scripted (non-chat) use.

Usage:
  python3 tools/konnect_mcp.py list [toolset]          # list tools (optionally after load_toolset)
  python3 tools/konnect_mcp.py call <tool> '<json>'    # call one tool, print JSON result
  python3 tools/konnect_mcp.py seq calls.json          # run [[tool, args], ...] in one session

KONNECT env var overrides the server binary path.
"""
import json
import os
import subprocess
import sys

KONNECT = os.environ.get(
    "KONNECT",
    os.path.expanduser("~/Documents/KiCad/10.0/3rdparty/plugins/com_github_mixelpixx_konnect/bin/konnect"))


class Client:
    def __init__(self):
        self.p = subprocess.Popen([KONNECT], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.n = 0
        self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "ece-souvenir-script", "version": "1"}})
        self.notify("notifications/initialized")

    def notify(self, method, params=None):
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method,
                                       **({"params": params} if params else {})}) + "\n")

    def rpc(self, method, params):
        self.n += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method,
                                       "params": params}) + "\n")
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("konnect exited")
            msg = json.loads(line)
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(json.dumps(msg["error"]))
                return msg["result"]

    def call(self, tool, args=None):
        res = self.rpc("tools/call", {"name": tool, "arguments": args or {}})
        text = "\n".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
        try:
            body = json.loads(text)
        except ValueError:
            body = text
        return {"isError": res.get("isError", False), "result": body}

    def tools(self):
        return self.rpc("tools/list", {})["tools"]

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=10)


def main():
    c = Client()
    try:
        cmd = sys.argv[1]
        if cmd == "list":
            if len(sys.argv) > 2:
                print(json.dumps(c.call("load_toolset", {"name": sys.argv[2]}))[:400])
            for t in c.tools():
                print(f"{t['name']}: {t.get('description', '')[:110]}")
        elif cmd == "schema":
            if len(sys.argv) > 3:
                c.call("load_toolset", {"name": sys.argv[3]})
            for t in c.tools():
                if t["name"] == sys.argv[2]:
                    print(json.dumps(t, indent=1))
        elif cmd == "call":
            print(json.dumps(c.call(sys.argv[2], json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}),
                             indent=1))
        elif cmd == "seq":
            for tool, args in json.load(open(sys.argv[2])):
                r = c.call(tool, args)
                print(f"### {tool}\n{json.dumps(r, indent=1)}", flush=True)
                if r["isError"]:
                    break
    finally:
        c.close()


if __name__ == "__main__":
    main()
