"""PANIC / kill switch (ADR-0005 §5, merged design).

  L1 agent       — freeze one agent_id: it can neither propose nor execute.
  L2 capability  — freeze a capability ("money.payment.send"), a prefix ("money.*"),
                   or a whole category ("category:sms").
  L3 global      — system_state=FROZEN: the gateway refuses every execution and every
                   new proposal; queued (approved, not started) requests are cancelled.

State is a small JSON file written atomically (tmp + fsync + rename) and sealed with a
checksum. It is deliberately NOT in the governance database, so the host-local CLI can
engage a freeze even when the database is locked, corrupt or down.

FAIL CLOSED: a missing, unreadable, unparsable, wrongly-shaped or checksum-mismatched
state file is reported as FROZEN (L3) by `read()`. There is no code path that turns a
read failure into RUNNING.
"""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from .ids import canonical_json, fmt_ts, sha256_tagged, utcnow

SCHEMA = "mbos.governance.panic/1"
RUNNING, FROZEN = "RUNNING", "FROZEN"


@dataclass(frozen=True)
class PanicState:
    global_state: str
    frozen_agents: dict = field(default_factory=dict)
    frozen_capabilities: dict = field(default_factory=dict)
    revision: int = 0
    readable: bool = True
    error: str | None = None

    @property
    def globally_frozen(self) -> bool:
        return self.global_state != RUNNING or not self.readable

    def blocks(self, agent_id: str | None, capability: str | None, category: str | None) -> list[str]:
        """Return the reasons this (agent, capability, category) is blocked; empty = clear."""
        if not self.readable:
            return [f"PANIC_STATE_UNREADABLE:{self.error}"]
        reasons = []
        if self.global_state != RUNNING:
            reasons.append("PANIC_L3_FROZEN")
        if agent_id and agent_id in self.frozen_agents:
            reasons.append(f"PANIC_L1_AGENT:{agent_id}")
        for key in self.frozen_capabilities:
            if category and key == f"category:{category}":
                reasons.append(f"PANIC_L2_CATEGORY:{category}")
            elif capability and (key == capability or (key.endswith(".*") and capability.startswith(key[:-1]))):
                reasons.append(f"PANIC_L2_CAPABILITY:{key}")
        return reasons


def _frozen(error: str) -> PanicState:
    return PanicState(global_state=FROZEN, readable=False, error=error)


def _seal(body: dict) -> dict:
    body = {k: v for k, v in body.items() if k != "checksum"}
    return {**body, "checksum": sha256_tagged(canonical_json(body))}


class PanicStore:
    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)

    # ---- read: fail closed -------------------------------------------------
    def read(self) -> PanicState:
        try:
            raw = json.loads(self.path.read_text("utf-8"))
        except FileNotFoundError:
            return _frozen("state file missing (run `mbos-gov panic init`)")
        except Exception as exc:  # noqa: BLE001
            return _frozen(f"unreadable: {type(exc).__name__}: {exc}")
        try:
            if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
                return _frozen("wrong schema")
            if raw.get("checksum") != _seal(raw)["checksum"]:
                return _frozen("checksum mismatch")
            g = raw["global"]["state"]
            if g not in (RUNNING, FROZEN):
                return _frozen(f"unknown global state {g!r}")
            agents, caps = raw["agents"], raw["capabilities"]
            if not isinstance(agents, dict) or not isinstance(caps, dict):
                return _frozen("agents/capabilities not objects")
            return PanicState(global_state=g, frozen_agents=agents, frozen_capabilities=caps,
                              revision=int(raw["revision"]))
        except Exception as exc:  # noqa: BLE001
            return _frozen(f"malformed: {type(exc).__name__}: {exc}")

    def read_raw(self) -> dict | None:
        try:
            return json.loads(self.path.read_text("utf-8"))
        except Exception:  # noqa: BLE001
            return None

    # ---- write: atomic -----------------------------------------------------
    def _write(self, body: dict) -> None:
        sealed = _seal(body)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".panic.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(sealed, indent=2, sort_keys=True))
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
            dfd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def _base(self) -> dict:
        """Current body for a mutation. An unreadable state is rebuilt as FROZEN —
        a mutation can never 'repair' an unreadable file into RUNNING."""
        st = self.read()
        if not st.readable:
            return {"schema": SCHEMA, "revision": 0, "agents": {}, "capabilities": {},
                    "global": {"state": FROZEN, "changed_at": fmt_ts(utcnow()), "changed_by": "system",
                               "reason": f"rebuilt from unreadable state: {st.error}"}}
        raw = self.read_raw()
        assert raw is not None
        return raw

    def write_state(self, body: dict) -> dict:
        body = {**body, "schema": SCHEMA}
        self._write(body)
        return body

    def init(self, actor: str, reason: str, state: str = FROZEN) -> dict:
        """Create the state file. Defaults to FROZEN; releasing is a separate, receipted act."""
        if self.path.exists():
            raise FileExistsError(f"{self.path} exists; refusing to overwrite")
        return self.write_state({"revision": 1, "agents": {}, "capabilities": {},
                                 "global": {"state": state, "changed_at": fmt_ts(utcnow()),
                                            "changed_by": actor, "reason": reason}})

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(str(self.path) + ".lock", "a") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)

    def mutate(self, level: str, target: str | None, engage: bool, actor: str, reason: str) -> tuple[dict, dict]:
        """Return (before, after) bodies after applying one change atomically."""
        with self._locked():
            return self._mutate(level, target, engage, actor, reason)

    def _mutate(self, level: str, target: str | None, engage: bool, actor: str, reason: str) -> tuple[dict, dict]:
        before = self._base()
        after = json.loads(json.dumps(before))
        after.pop("checksum", None)
        stamp = {"changed_at": fmt_ts(utcnow()), "changed_by": actor, "reason": reason}
        if level == "L3":
            after["global"] = {"state": FROZEN if engage else RUNNING, **stamp}
        elif level in ("L1", "L2"):
            if not target:
                raise ValueError(f"{level} needs a target")
            key = "agents" if level == "L1" else "capabilities"
            if engage:
                after[key][target] = stamp
            else:
                after[key].pop(target, None)
        else:
            raise ValueError(f"unknown PANIC level {level!r}")
        after["revision"] = int(before.get("revision", 0)) + 1
        self.write_state(after)
        return before, after
