"""Mocked effectors. Wave one sends NOTHING (MICHAEL_DECISIONS #4: outbound disabled).

The only effector is `DryRunEffector`: it records what *would* have been sent in
the local `dryrun_outbox` table, keyed by idempotency key so a retry after a
crash returns the original response instead of "sending" twice (A5), and it
refuses any call with dry_run=False. There is no code path in this package that
reaches Telnyx, Postmark, Vapi/Retell or any network service.
"""

from . import TOOL_NAME, __version__
from .util import sha256_of

CHANNELS = {"comms.email": "email", "comms.sms": "sms", "comms.voice": "voice", "comms.call": "voice"}


class LiveEffectorForbidden(RuntimeError):
    pass


class DryRunEffector:
    provider = "mock-dryrun"
    tool_name = f"{TOOL_NAME}.dry_run_effector"
    tool_version = __version__

    def __init__(self, store):
        self.store = store
        self.calls = 0  # real invocations (not replays) — used by tests

    def execute(self, areq, dry_run):
        if dry_run is not True:
            raise LiveEffectorForbidden("wave one: live effectors are not implemented; dry_run must be True")
        key = "exec:" + areq["idempotency_key"]
        prior = self.store.dryrun_sent(key)
        if prior is not None:
            return prior, True
        self.calls += 1
        resp = {
            "provider": self.provider,
            "provider_msg_id": "dryrun_" + sha256_of({"k": key, "p": areq["payload_hash"]})[7:31],
            "status": "accepted_dry_run",
            "dry_run": True,
        }
        with self.store.tx() as tx:
            tx.record_dryrun(key, areq["action_request_id"], resp)
        return resp, False

    @staticmethod
    def details_for(areq):
        """Receipt `details` block. kind=comms carries Agent 06's comms fields."""
        cap = areq["capability"]
        channel = next((v for k, v in CHANNELS.items() if cap.startswith(k)), None)
        if channel is None:
            return {"kind": "generic", "note": "dry-run; no external effect"}
        p = areq["payload"]
        return {
            "kind": "comms",
            "channel": channel,
            "direction": "outbound",
            "template_id": p.get("template_id"),
            "to_ref": p.get("to_ref") or (areq.get("target") or {}).get("ref"),
            "dry_run": True,
            # Honest about what did NOT happen: the consent/DNC ledger and quiet-hours
            # check are not built in wave one, so nothing could be sent anyway.
            "consent_check": {"result": "not_evaluated", "reason": "dry-run mock; consent/DNC ledger not built"},
            "dnc_check": {"result": "not_evaluated", "reason": "dry-run mock"},
            "quiet_hours_check": {"result": "not_evaluated", "reason": "dry-run mock"},
        }
