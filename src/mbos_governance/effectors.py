"""Effectors — the only code allowed to touch the outside world, and only via the gateway.

Wave one ships exactly one effector, DryRunEffector, which performs NO I/O. Every
effector call requires a GuardToken minted by the ActionGateway after all 8 guard checks
passed; the token is an HMAC over (action_request_id, payload_hash, idempotency_key,
dry_run) keyed by a per-process secret that only the gateway holds.

INFERENCE: inside one Python process this stops *accidental* bypass, not a determined
in-process attacker. The real boundary is structural (ADR-0005): effector credentials
live only in the gateway process, agents run as separate Unix users, and the egress
proxy denies agent processes. tools/check_no_bypass.py enforces "no network/effector
libraries outside mbos_governance.effectors" in this repository.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from .ids import new_ulid


@dataclass(frozen=True)
class GuardToken:
    action_request_id: str
    payload_hash: str
    idempotency_key: str
    dry_run: bool
    mac: str


class TokenMinter:
    def __init__(self, secret: bytes):
        self._secret = secret

    def _mac(self, areq: str, ph: str, key: str, dry_run: bool) -> str:
        msg = "\x1f".join([areq, ph, key, "1" if dry_run else "0"]).encode()
        return hmac.new(self._secret, msg, hashlib.sha256).hexdigest()

    def mint(self, areq: str, ph: str, key: str, dry_run: bool) -> GuardToken:
        return GuardToken(areq, ph, key, dry_run, self._mac(areq, ph, key, dry_run))

    def verify(self, token: GuardToken) -> bool:
        return isinstance(token, GuardToken) and hmac.compare_digest(
            token.mac, self._mac(token.action_request_id, token.payload_hash, token.idempotency_key, token.dry_run))


class EffectorRefused(RuntimeError):
    pass


class Effector:
    name = "abstract"
    supports_dry_run = False

    def __init__(self, minter: TokenMinter):
        self._minter = minter

    def execute(self, token: GuardToken, action_request: dict) -> dict:
        if not self._minter.verify(token):
            raise EffectorRefused("invalid guard token — effectors are reachable only through the Action Gateway")
        if token.action_request_id != action_request["action_request_id"] or token.payload_hash != action_request["payload_hash"]:
            raise EffectorRefused("guard token does not match this action request")
        if token.dry_run and not self.supports_dry_run:
            raise EffectorRefused(f"effector {self.name} cannot dry-run")
        return self._execute(token, action_request)

    def _execute(self, token: GuardToken, action_request: dict) -> dict:  # pragma: no cover
        raise NotImplementedError

    def lookup(self, token: GuardToken, action_request: dict) -> dict | None:
        """Provider-side query by idempotency key (E-05 reconciliation): the provider's record of this
        call, or None if the provider has no record. Raises if the provider cannot answer — callers
        must then leave the claim alone. Read-only: never sends."""
        if not self._minter.verify(token) or token.action_request_id != action_request["action_request_id"]:
            raise EffectorRefused("invalid guard token for lookup")
        return self._lookup(token, action_request)

    def _lookup(self, token: GuardToken, action_request: dict) -> dict | None:  # pragma: no cover
        raise NotImplementedError


class DryRunEffector(Effector):
    """Simulates any capability. No network, no files, no spend."""

    name = "dryrun"
    supports_dry_run = True

    def __init__(self, minter: TokenMinter):
        super().__init__(minter)
        # The simulated provider's own record, keyed by idempotency key (in-process; a real provider
        # keeps this server-side and answers lookups by its Idempotency-Key / message id).
        self.deliveries: dict[str, dict] = {}

    def _execute(self, token: GuardToken, action_request: dict) -> dict:
        if not token.dry_run:
            raise EffectorRefused("DryRunEffector refuses live execution")
        if token.idempotency_key in self.deliveries:   # provider-level idempotency: never twice
            return self.deliveries[token.idempotency_key]
        resp = {
            "provider": "dryrun",
            "provider_msg_id": f"dryrun_{new_ulid()}",
            "status": "simulated",
            "dry_run": True,
        }
        self.deliveries[token.idempotency_key] = resp
        return resp

    def _lookup(self, token: GuardToken, action_request: dict) -> dict | None:
        return self.deliveries.get(token.idempotency_key)
