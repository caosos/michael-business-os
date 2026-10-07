"""Static check: no external-effect capability outside the gateway's effectors.

Fails if any Python file outside `mbos_governance/effectors.py` (or an
`mbos_governance/effectors/` package) imports a network / messaging / payment library.
Run in CI and from the test suite. Usage: python -I tools/check_no_bypass.py <root> [...]
Exit 0 = clean, 1 = violations (printed).

INFERENCE: a static check catches accidental bypass in this repo; the structural controls
(no effector credentials in agent processes, egress proxy deny-by-default) are what stop
a deliberate one.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

FORBIDDEN = {
    "socket", "ssl", "smtplib", "poplib", "imaplib", "ftplib", "telnetlib", "http.client", "urllib.request",
    "xmlrpc.client", "requests", "httpx", "aiohttp", "urllib3", "websocket", "websockets", "grpc",
    "twilio", "telnyx", "vonage", "plivo", "sendgrid", "mailgun", "postmarker", "stripe", "paypalrestsdk",
    "square", "boto3", "botocore", "googleapiclient", "slack_sdk", "telegram", "discord", "selenium",
    "playwright", "nodriver", "subprocess",
}
ALLOWED_SUFFIXES = ("mbos_governance/effectors.py",)
ALLOWED_DIRS = ("mbos_governance/effectors/",)


def _imports(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                yield node.lineno, n.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.lineno, node.module
        elif isinstance(node, ast.Call) and getattr(node.func, "id", None) == "__import__" and node.args \
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            yield node.lineno, node.args[0].value


def violations(root: Path) -> list[str]:
    out = []
    for path in sorted(root.rglob("*.py")):
        rel = path.as_posix()
        if rel.endswith(ALLOWED_SUFFIXES) or any(d in rel for d in ALLOWED_DIRS):
            continue
        try:
            tree = ast.parse(path.read_text("utf-8"), filename=rel)
        except SyntaxError as exc:
            out.append(f"{rel}: unparsable ({exc})")
            continue
        for lineno, mod in _imports(tree):
            top = {mod, mod.split(".")[0]}
            if top & FORBIDDEN:
                out.append(f"{rel}:{lineno}: imports {mod} — external effects must go through the Action Gateway")
    return out


def main(argv: list[str]) -> int:
    roots = [Path(a) for a in argv] or [Path("src")]
    found = [v for r in roots for v in violations(r)]
    for v in found:
        print(v)
    print("no-bypass check: " + ("FAIL" if found else "PASS"))
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
