"""Manual-assist output packets + the dry-run effector that emits them. Owner: Agent 07 (lane G / marketing).

In SYSTEM_MODE round_one|mvp every outbound effector is replaced by this one: instead of sending or
posting, it renders the exact approved payload into a human-readable packet that Michael can act on by
hand if he chooses. Nothing leaves the system. The packet is content-addressed (sha256) and its hash is
recorded on the ACTION_EXECUTED receipt (`artifact_hashes`).

The `comms` instance stands in for Agent 06's effectors (MOCK of lane 06 send path, dry-run only).
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
import threading

from .core import sha256_ref

PACKET_VERSION = "manual-assist-packet/1"

MANUAL_STEPS = {
    "publishing": [
        "Confirm the item is actually in hand / repaired before posting (resale listing).",
        "Open the platform named under Channel in your own browser and log in yourself.",
        "Paste Title and Body exactly as shown; set price to the Price shown.",
        "Attach your own photos (none are attached by the system).",
        "Do not add claims that are not in the approved text.",
        "After posting, paste the listing URL back into the Operator UI so an OUTCOME can be recorded.",
    ],
    "email": [
        "Use the platform relay address on file (target ref above); the system never stores raw contact values here.",
        "Send the Subject and Body exactly as shown, or do not send at all.",
        "If the counterparty replies, log the reply so the item can move forward.",
    ],
}

COMPLIANCE = {
    "publishing": [
        "No misleading condition claims (copy is limited to verified facts + disclosed unknowns).",
        "Platform rules: one listing per item, no keyword stuffing, no reposting spam.",
    ],
    "email": [
        "One-to-one reply to a public listing / inbound request — not bulk marketing.",
        "No pressure tactics; no binding offer language (tier-0 external commitment rule).",
    ],
    "review_request": [
        "Google review policy: no review gating, no incentives, same ask to every customer.",
    ],
}


def render_packet(areq: dict, approval: dict) -> tuple[str, dict]:
    p = areq["payload"]
    content = p["content"]
    kind = "publishing" if areq["category"] == "publishing" else "email"
    lines = [
        "# MANUAL-ASSIST PACKET — DRY-RUN",
        "",
        "> **Nothing was sent, posted, or paid by the system.** This packet is the exact text Michael",
        "> approved. Acting on it is a manual choice outside the system.",
        "",
        f"- Packet format: `{PACKET_VERSION}`",
        f"- Action request: `{areq['action_request_id']}` (item `{areq['item_id']}`)",
        f"- Capability / category: `{areq['capability']}` / `{areq['category']}` · tier {areq['tier']} · {areq['reversibility']}",
        f"- Channel: {p.get('channel', 'n/a')}",
        f"- Target ref: `{(areq.get('target') or {}).get('ref', 'n/a')}`",
        f"- Approved by: {approval['decider']} via `{approval['channel']}` at {approval['decided_at']} (`{approval['approval_id']}`)"
        + (" — **SIMULATED fixture decision, not Michael**" if (approval.get("auth_context") or {}).get("method") == "fixture_simulation" else ""),
        f"- Approved payload hash: `{areq['payload_hash']}`",
        f"- Draft content hash: `{p['content_hash']}` · template `{p['template_id']}@{p['template_version']}` · model `{p['model_id']}`",
        f"- AI-generated content: {'yes' if p.get('ai_generated') else 'no (deterministic template)'}",
        "",
        "## Content",
        "",
    ]
    for k in ("subject", "title", "price", "body"):
        if k in content:
            v = content[k]
            if k == "price":
                v = f"${v:,.0f}"
            if k == "body":
                lines += ["**Body:**", "", "```text", v, "```", ""]
            else:
                lines += [f"**{k.capitalize()}:** {v}", ""]
    lines += ["## Manual steps (only if you choose to act)", ""]
    lines += [f"{i}. {s}" for i, s in enumerate(MANUAL_STEPS[kind], 1)]
    lines += ["", "## Compliance checklist", ""]
    lines += [f"- [ ] {s}" for s in COMPLIANCE[kind] + [c for c in p.get("policy_checks", [])]]
    lines += ["", "## Provenance", ""]
    lines += [f"- `{pid}`" for pid in areq["provenance_ids"]]
    lines += ["", f"Verify: `sha256(canonical(payload)) == {areq['payload_hash']}`", ""]
    md = "\n".join(lines)
    meta = {
        "packet_version": PACKET_VERSION, "dry_run": True, "action_request_id": areq["action_request_id"],
        "approval_id": approval["approval_id"], "payload_hash": areq["payload_hash"],
        "content_hash": p["content_hash"], "packet_sha256": sha256_ref(md),
    }
    return md, meta


class ManualAssistEffector:
    """Dry-run effector. Provider-side call log lives in its own DB (simulates the external provider),
    so crash recovery can ask "did this key already go out?" before any retry (A5)."""

    dry_run = True

    def __init__(self, *, name: str, details_kind: str, effect: str, log_path: str | pathlib.Path,
                 out_dir: str | pathlib.Path):
        self.name, self.details_kind, self.effect = name, details_kind, effect
        self.tool_name = f"{name}@{PACKET_VERSION}"
        self.out_dir = pathlib.Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.db = sqlite3.connect(str(log_path), isolation_level=None, check_same_thread=False, timeout=30)
        self.db.execute("CREATE TABLE IF NOT EXISTS calls (key TEXT PRIMARY KEY, response TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS attempts (n INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT)")

    def call_count(self, key: str | None = None) -> int:
        with self._lock:
            if key:
                return self.db.execute("SELECT count(*) FROM attempts WHERE key=?", (key,)).fetchone()[0]
            return self.db.execute("SELECT count(*) FROM attempts").fetchone()[0]

    def lookup(self, key: str) -> dict | None:
        with self._lock:
            r = self.db.execute("SELECT response FROM calls WHERE key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else None

    def execute(self, areq: dict, approval: dict, key: str) -> dict:
        md, meta = render_packet(areq, approval)
        packet_hash = meta["packet_sha256"]
        (self.out_dir / f"{areq['action_request_id']}.md").write_text(md)
        (self.out_dir / f"{areq['action_request_id']}.json").write_text(json.dumps(meta, indent=2, sort_keys=True))
        resp = {
            "provider": self.name, "provider_msg_id": f"dryrun-{packet_hash[7:23]}",
            "status": "dry_run_packet_written", "dry_run": True, "artifact_hashes": [packet_hash],
            "details": {"kind": self.details_kind, "manual_assist_packet": f"{areq['action_request_id']}.md",
                        "sent": False, "published": False},
        }
        with self._lock:
            self.db.execute("INSERT INTO attempts (key) VALUES (?)", (key,))
            self.db.execute("INSERT OR IGNORE INTO calls VALUES (?,?)", (key, json.dumps(resp)))
        return resp
