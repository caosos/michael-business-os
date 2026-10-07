"""MOCK — lane A (Core workflow, Agent 01) + lane F approval semantics. Conforms to contracts v1.0.0.

Drives one Item through DISCOVER → NORMALIZE → RESEARCH → SCORE → RECOMMEND → APPROVE → DRY-RUN ACT,
writing every transition and its receipt in one transaction, and implements Approval semantics:
  YES    → request approved; the frozen payload (and only it) may execute.
  NO     → request rejected with a reason; item archived when nothing else is live.
  MODIFY → NEVER mutates: a new ActionRequest (derived_from) is created; the old one is closed.
  HOLD   → parked durably; wakes on time/condition, re-notifies, escalates — NEVER auto-executes.
REPLACE WITH: Agent 01's DBOS Item workflow + Operator UI approval queue behind the same calls.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from .. import drafts
from ..core import iso, parse_duration, parse_iso, sha256_ref
from . import discovery, economics

IMPLEMENTATION = "MOCK item workflow + approval service — stands in for Agent 01 (DBOS) / lane F"
TOOL_NAME, TOOL_VERSION = "mbos_qa.mocks.workflow", "0.1.0"
WF = {"type": "agent", "id": "agent-01-workflow"}
MICHAEL = {"type": "human", "id": "michael"}
LIVE = ("pending_approval", "held", "approved", "executing")


class ApprovalRejected(Exception):
    pass


@dataclass
class Trace:
    """Human-readable notes collected per stage for the end-to-end report."""
    stages: dict[str, list[str]] = field(default_factory=dict)

    def add(self, stage: str, note: str) -> None:
        self.stages.setdefault(stage, []).append(note)


class Workflow:
    def __init__(self, h):
        self.h = h
        self.store, self.ids, self.clock = h.store, h.ids, h.clock
        self.traces: dict[str, Trace] = {}
        self.prov_id = self._tool_provenance(TOOL_NAME, TOOL_VERSION)

    # ------------------------------------------------------------------ helpers
    def now(self) -> str:
        return iso(self.clock.now())

    def _tool_provenance(self, name: str, version: str) -> str:
        pid = self.ids.new("prov")
        with self.store.tx() as t:
            t.put_provenance({"provenance_id": pid, "created_at": self.now(), "actor_type": "system",
                              "basis": "FACT", "tool_name": name, "tool_version": version})
        return pid

    def trace(self, item_id: str) -> Trace:
        return self.traces.setdefault(item_id, Trace())

    def _sync_item_after_decision(self, t, item_id: str) -> None:
        item = self.store._load(t.cur, "items", "item_id", item_id)
        reqs = [a for a in self.store.action_requests(item_id=item_id)]
        statuses = {a["status"] for a in reqs}
        state = item["state"]
        if state in ("ACTING", "ACTED", "OUTCOME_RECORDED", "LEARNED", "ARCHIVED", "FAILED"):
            return
        if "pending_approval" in statuses:
            target = "AWAITING_APPROVAL"
        elif "approved" in statuses:
            target = "APPROVED"
        elif "held" in statuses:
            target = "HELD"
        elif statuses and statuses <= {"rejected", "expired", "cancelled_by_freeze"}:
            target = "REJECTED"
        else:
            return
        if target != state:
            if state == "HELD" and target != "AWAITING_APPROVAL":
                t.transition_item(item_id, "AWAITING_APPROVAL", actor=WF, intent="held request re-presented",
                                  provenance_ids=[self.prov_id])
                state = "AWAITING_APPROVAL"
            if target != state:
                t.transition_item(item_id, target, actor=WF, intent=f"all requests decided → {target}",
                                  provenance_ids=[self.prov_id])
        if target == "REJECTED":
            t.transition_item(item_id, "ARCHIVED", actor=WF, intent="Michael said NO to every action — archived with reason",
                              provenance_ids=[self.prov_id])

    # ------------------------------------------------------------------ DISCOVER + NORMALIZE
    def ingest(self, raw_path) -> str:
        raw, raw_ref = discovery.fetch(raw_path, self.h.artifacts)
        seen = self.store.receipt_by_key(f"discover:{raw['source']}:{raw.get('source_listing_id', raw['url'])}")
        if seen:  # same source listing already ingested → dedup, no new item, no new receipt
            return seen["item_id"]
        item_id = self.ids.new("itm")
        src_pid, norm_pid = self.ids.new("prov"), self.ids.new("prov")
        item, notes = discovery.normalize(raw, raw_ref, item_id=item_id, created_at=self.now(), src_pid=src_pid)
        tr = self.trace(item_id)
        tr.add("source", f"{raw['source']} · {raw['url']} · fetched {raw['fetched_at']} · ingestion {raw['ingestion_method']}")
        tr.add("source", f"raw payload stored content-addressed: {raw_ref}")
        tr.add("source", raw.get("_fixture", ""))
        for n in notes:
            tr.add("normalization", n)
        with self.store.tx() as t:
            t.put_provenance(discovery.source_provenance(src_pid, self.now(), raw, raw_ref))
            t.put_provenance(discovery.normalizer_provenance(norm_pid, self.now(), src_pid))
            item["provenance_ids"] = [src_pid, norm_pid]
            t.put_item(item)
            r = t.receipt(type="ITEM_STATE_CHANGED", actor={"type": "agent", "id": "agent-02-discovery"},
                          intent=f"discovered {item['type']}/{item['category']} from {raw['source']}",
                          provenance_ids=[src_pid], idempotency_key=f"discover:{raw['source']}:{raw.get('source_listing_id', raw['url'])}",
                          item_id=item_id, entity_type="item", entity_id=item_id, effect="create",
                          before_state=None, after_state={"state": "DISCOVERED"}, artifact_hashes=[raw_ref])
            item["receipt_ids"] = [r["receipt_id"]]
            t.replace_item(item)
            if "injection_suspected" in item["normalized"].get("flags", []):
                t.receipt(type="INJECTION_SUSPECTED", actor={"type": "agent", "id": "agent-02-discovery"},
                          intent="prompt-injection pattern in untrusted listing text; quarantined from drafts",
                          provenance_ids=[src_pid, norm_pid], idempotency_key=f"inject:{item_id}",
                          item_id=item_id, effect="none", artifact_hashes=[raw_ref])
            t.transition_item(item_id, "NORMALIZED", actor={"type": "agent", "id": "agent-02-discovery"},
                              intent="raw → Item v1 normalized", provenance_ids=[norm_pid])
        return item_id

    # ------------------------------------------------------------------ RESEARCH
    def research(self, item_id: str, findings: list[dict]) -> None:
        with self.store.tx() as t:
            entries, pids = [], []
            for f in findings:
                pid = self.ids.new("prov")
                t.put_provenance({"provenance_id": pid, "created_at": self.now(), "actor_type": "agent",
                                  "agent_name": "agent-02-discovery", "basis": f["basis"], "source_uri": f["source_uri"],
                                  "fetched_at": f["fetched_at"]})
                entries.append({"finding": f["finding"], "field": f["field"], "basis": f["basis"],
                                "source_uri": f["source_uri"], "fetched_at": f["fetched_at"], "provenance_id": pid})
                pids.append(pid)
                self.trace(item_id).add("research", f"[{f['basis']}] {f['finding']} ({f['source_uri']})")
            item = self.store._load(t.cur, "items", "item_id", item_id)
            t.transition_item(item_id, "RESEARCHING", actor=WF, intent=f"{len(entries)} research findings recorded",
                              provenance_ids=pids or [self.prov_id],
                              patch={"research": entries, "provenance_ids": item["provenance_ids"] + pids})

    # ------------------------------------------------------------------ SCORE
    def score(self, item_id: str, econ: dict, *, skills_on_file: set[str], scarcity: float) -> dict:
        item = self.store.get("item", item_id)
        research_pids = [r["provenance_id"] for r in item.get("research", [])]
        n_comps = sum(1 for r in item.get("research", []) if r["field"].startswith("resale.") or "comp" in r["finding"].lower())
        ihash = economics.inputs_hash(econ, research_pids)
        card = economics.score(item["type"], econ, n_comps=n_comps, skills_on_file=skills_on_file,
                               scarcity=scarcity, computed_at=self.now())
        scr_id, pid = self.ids.new("scr"), self.ids.new("prov")
        with self.store.tx() as t:
            t.put_provenance(economics.scorer_provenance(pid, self.now(), research_pids or [self.prov_id], ihash))
            t.transition_item(item_id, "SCORED", actor={"type": "agent", "id": "agent-03-economics"},
                              intent=f"scored {card['decision']} composite {card['composite']}", provenance_ids=[pid],
                              patch={"economics": econ,
                                     "scores": {"scorecard_id": scr_id, "inputs_hash": ihash, "scorecard": card},
                                     "provenance_ids": item["provenance_ids"] + [pid]})
            t.receipt(type="SCORE_RECORDED", actor={"type": "agent", "id": "agent-03-economics"},
                      intent=f"scorecard {scr_id} ({card['decision']})", provenance_ids=[pid],
                      idempotency_key=f"score:{item_id}:{ihash}", item_id=item_id, entity_type="scorecard",
                      entity_id=scr_id, inputs_hash=ihash, effect="create")
        tr = self.trace(item_id)
        d = card["derived"]
        tr.add("economics", f"inputs_hash {ihash} (scoring_config {card['scoring_config_version']})")
        tr.add("economics", f"EV net ${d['ev_net_profit']:,.2f} · EV $/hr {d['ev_profit_per_hour']:,.2f} · max loss "
                            f"${d['max_loss']:,.2f} · cash tied up ${d['cash_tied_up']:,.2f} · confidence {d['confidence']}")
        tr.add("economics", "gates: " + ", ".join(f"{k}={'✔' if v else '✘'}" for k, v in card["gates"].items()))
        for r in card["reasons"]:
            tr.add("economics", r)
        return card

    # ------------------------------------------------------------------ RECOMMEND (+ propose)
    def recommend(self, item_id: str, proposed_actions: list[dict], expires_hours: int = 48) -> str:
        item = self.store.get("item", item_id)
        card = item["scores"]["scorecard"]
        pid, rec_id = self.ids.new("prov"), self.ids.new("rec")
        rec = {"recommendation_id": rec_id, "verdict": card["decision"], "rationale": card["reasons"][1:] or card["reasons"],
               "confidence": card["derived"]["confidence"], "provenance_id": pid,
               "expires_at": iso(self.clock.now() + parse_duration(f"PT{expires_hours}H"))}
        if card["decision"] == "YES":
            rec["proposed_actions"] = [{k: a[k] for k in ("capability", "summary", "reversibility", "estimated_cost")}
                                       for a in proposed_actions]
        if card.get("cheapest_decisive_evidence"):
            rec["cheapest_decisive_evidence"] = card["cheapest_decisive_evidence"]
        with self.store.tx() as t:
            t.put_provenance({"provenance_id": pid, "created_at": self.now(), "actor_type": "agent",
                              "agent_name": "agent-03-economics", "basis": "RECOMMENDATION",
                              "tool_name": economics.TOOL_NAME, "tool_version": economics.TOOL_VERSION,
                              "config_version": economics.CONFIG_VERSION,
                              "derived_from": [item["provenance_ids"][-1]]})
            t.transition_item(item_id, "RECOMMENDED", actor={"type": "agent", "id": "agent-03-economics"},
                              intent=f"machine verdict {rec['verdict']} (NOT Michael's decision)", provenance_ids=[pid],
                              patch={"recommendation": rec, "provenance_ids": item["provenance_ids"] + [pid]})
            t.receipt(type="RECOMMENDATION_RECORDED", actor={"type": "agent", "id": "agent-03-economics"},
                      intent=f"verdict {rec['verdict']}", provenance_ids=[pid], idempotency_key=f"rec:{rec_id}",
                      item_id=item_id, entity_type="recommendation", entity_id=rec_id, effect="create")
            if rec["verdict"] == "PASS":
                t.transition_item(item_id, "ARCHIVED", actor=WF, intent="PASS → archived, no ping", provenance_ids=[pid])
            elif rec["verdict"] == "MAYBE":
                t.transition_item(item_id, "RESEARCHING", actor=WF, provenance_ids=[pid],
                                  intent="MAYBE → back to RESEARCH for cheapest decisive evidence (no approval ping)")
        tr = self.trace(item_id)
        tr.add("recommendation", f"verdict {rec['verdict']} (machine; YES/MAYBE/PASS) · confidence {rec['confidence']} · expires {rec['expires_at']}")
        for a in rec.get("proposed_actions", []):
            tr.add("recommendation", f"proposed: {a['capability']} — {a['summary']} ({a['reversibility']})")
        if rec["verdict"] == "YES":
            for a in proposed_actions:
                self.propose(item_id, a, rec_id=rec_id)
        return rec["verdict"]

    def propose(self, item_id: str, a: dict, *, rec_id: str | None = None, derived_from: str | None = None,
                via: object | None = None) -> dict:
        """Create an ActionRequest (frozen payload) → PDP → APPROVAL_REQUESTED. `via` is the open Tx when nested."""
        item = self.store.get("item", item_id) if via is None else self.store._load(via.cur, "items", "item_id", item_id)
        payload = a["payload"]
        areq_id, draft_pid = self.ids.new("areq"), self.ids.new("prov")
        untrusted = bool(a.get("untrusted_inputs_present")) or "injection_suspected" in item["normalized"].get("flags", [])
        areq = {
            "action_request_id": areq_id, "item_id": item_id, "created_at": self.now(), "proposed_by": a["proposed_by"],
            "on_behalf_of": "michael", "capability": a["capability"], "category": a["category"], "payload": payload,
            "payload_hash": sha256_ref(payload), "idempotency_key": f"{areq_id}:{a['capability']}",
            "estimated_cost": a["estimated_cost"], "reversibility": a["reversibility"],
            "untrusted_inputs_present": untrusted, "tier": 0, "status": "pending_approval",
            "expires_at": iso(self.clock.now() + parse_duration("P2D")),
            "provenance_ids": [draft_pid], "target": a["target"],
        }
        if rec_id:
            areq["recommendation_id"] = rec_id
        if derived_from:
            areq["derived_from"] = derived_from
        if item.get("scores"):
            areq["score_ref"] = item["scores"]["scorecard_id"]
        decision = self.h.pdp.decide(areq)
        areq["policy_decision_ref"] = decision["policy_decision_ref"]

        def write(t):
            t.put_provenance(drafts.draft_provenance(draft_pid, self.now(), template_id=payload["template_id"],
                                                     item=item, content_hash=payload["content_hash"]))
            if decision["decision"] == "deny":
                areq["status"] = "rejected"
            t.put_action_request(areq)
            common = dict(item_id=item_id, action_request_id=areq_id, capability=areq["capability"],
                          payload_hash=areq["payload_hash"], effect="none")
            t.receipt(type="ACTION_PROPOSED", actor={"type": "agent", "id": a["proposed_by"]},
                      intent=a["summary"], provenance_ids=[draft_pid], idempotency_key=f"{areq_id}:proposed",
                      after_state={"status": "drafted"}, details={"kind": "marketing" if a["proposed_by"].startswith("agent-07") else "generic"},
                      **common)
            t.receipt(type="POLICY_DECIDED", actor={"type": "system", "id": "pdp"},
                      intent=f"PDP: {decision['decision']} at tier {decision['tier']}", provenance_ids=[self.h.gateway.prov_id],
                      idempotency_key=f"{areq_id}:policy", policy_decision_ref=decision["policy_decision_ref"],
                      after_state={"decision": decision["decision"], "tier": decision["tier"]}, **common)
            if decision["decision"] != "deny":
                t.receipt(type="APPROVAL_REQUESTED", actor=WF, intent="presented to Michael: YES / NO / MODIFY / HOLD",
                          provenance_ids=[draft_pid], idempotency_key=f"{areq_id}:approval-requested",
                          before_state={"status": "classified"}, after_state={"status": "pending_approval"}, **common)
            cur_item = self.store._load(t.cur, "items", "item_id", item_id)
            cur_item.setdefault("action_request_ids", []).append(areq_id)
            cur_item["provenance_ids"] = cur_item.get("provenance_ids", []) + [draft_pid]
            t.replace_item(cur_item)
            if cur_item["state"] == "RECOMMENDED":
                t.transition_item(item_id, "AWAITING_APPROVAL", actor=WF, intent="action(s) awaiting Michael",
                                  provenance_ids=[self.prov_id])

        if via is None:
            with self.store.tx() as t:
                write(t)
        else:
            write(via)
        self.trace(item_id).add("action", f"{areq_id} {a['capability']} [{a['category']}, tier 0, "
                                          f"{a['reversibility']}, untrusted={untrusted}] payload {areq['payload_hash'][:23]}…")
        return areq

    # ------------------------------------------------------------------ APPROVE
    def decide(self, areq_id: str, decision: str, *, payload_hash_seen: str | None = None, reason: str | None = None,
               new_payload: dict | None = None, hold: dict | None = None, channel: str = "cli",
               step_up: bool = True, scope: str = "once", simulated: bool = True) -> dict:
        areq = self.store.get("action-request", areq_id)
        if areq["status"] not in ("pending_approval", "held"):
            raise ApprovalRejected(f"{areq_id} is {areq['status']}; only pending/held requests can be decided")
        seen = payload_hash_seen or areq["payload_hash"]
        if seen != areq["payload_hash"]:
            raise ApprovalRejected("payload_hash_seen does not match the frozen payload — approval void")
        if decision == "NO" and not reason:
            raise ApprovalRejected("NO requires a reason")
        if decision == "HOLD" and not (hold and hold.get("hold_until") and hold.get("wake_on")):
            raise ApprovalRejected("HOLD requires hold_until and wake_on")
        if decision == "MODIFY" and not new_payload:
            raise ApprovalRejected("MODIFY requires a new payload")
        appr_id, pid = self.ids.new("appr"), self.ids.new("prov")
        appr = {"approval_id": appr_id, "action_request_id": areq_id, "decision": decision, "decider": "michael",
                "decided_at": self.now(), "channel": channel, "payload_hash_seen": seen, "scope": scope,
                "auth_context": {"method": "fixture_simulation" if simulated else "cli_local", "step_up": step_up}}
        if reason:
            appr["reason"] = reason
        if hold:
            appr["hold"] = {"renotify_after": "PT24H", "escalate_after": "PT48H", **hold}
        before = areq["status"]
        with self.store.tx() as t:
            new_areq = None
            if decision == "MODIFY":
                proposal = {"proposed_by": areq["proposed_by"], "capability": areq["capability"], "category": areq["category"],
                            "payload": new_payload, "reversibility": areq["reversibility"],
                            "estimated_cost": areq["estimated_cost"], "target": areq["target"],
                            "untrusted_inputs_present": areq.get("untrusted_inputs_present", False),
                            "summary": f"MODIFY of {areq_id}"}
                areq["status"] = "rejected"  # closed; contract has no 'superseded' status (finding F-3)
                t.replace_action_request(areq)
                new_areq = self.propose(areq["item_id"], proposal, rec_id=areq.get("recommendation_id"),
                                        derived_from=areq_id, via=t)
                appr["modifications"] = {"diff": _diff(areq["payload"], new_payload),
                                         "new_action_request_id": new_areq["action_request_id"],
                                         "new_payload_hash": new_areq["payload_hash"]}
            else:
                areq["status"] = {"YES": "approved", "NO": "rejected", "HOLD": "held"}[decision]
                t.replace_action_request(areq)
            t.put_approval(appr)
            t.put_provenance({"provenance_id": pid, "created_at": self.now(), "actor_type": "human",
                              "human_actor": "michael (SIMULATED by QA fixture)" if simulated else "michael",
                              "basis": "FACT", "approval_id": appr_id})
            after = {"status": areq["status"]}
            if new_areq:
                after["superseded_by"] = new_areq["action_request_id"]
            t.receipt(type="APPROVAL_DECIDED", actor=MICHAEL, intent=("[SIMULATED by QA fixture] " if simulated else "") + f"Michael: {decision}" + (f" — {reason}" if reason else ""),
                      provenance_ids=[pid], idempotency_key=f"{appr_id}:decided", item_id=areq["item_id"],
                      action_request_id=areq_id, approval_id=appr_id, capability=areq["capability"],
                      payload_hash=areq["payload_hash"], effect="none", before_state={"status": before}, after_state=after)
            item = self.store._load(t.cur, "items", "item_id", areq["item_id"])
            item.setdefault("approval_ids", []).append(appr_id)
            item["provenance_ids"] = item.get("provenance_ids", []) + [pid]
            t.replace_item(item)
            self._sync_item_after_decision(t, areq["item_id"])
        self.trace(areq["item_id"]).add("approval", f"{decision} on {areq_id} via {channel} ({appr_id})"
                                        + (f" → new request {new_areq['action_request_id']}" if new_areq else "")
                                        + (f" · reason: {reason}" if reason else "")
                                        + (" · SIMULATED owner decision (fixture), not Michael" if simulated else ""))
        return appr

    # ------------------------------------------------------------------ HOLD timers
    def tick(self) -> list[str]:
        """Process HOLD wake / re-notify / escalate. Never executes anything."""
        events = []
        now = self.clock.now()
        for areq in self.store.action_requests(status="held"):
            hold_appr = self.store.approvals_for(areq["action_request_id"])[-1]
            h = hold_appr["hold"]
            decided = parse_iso(hold_appr["decided_at"])
            if "time" in h["wake_on"] and now >= parse_iso(h["hold_until"]):
                events.append(self._re_present(areq, hold_appr, "woke: hold_until reached"))
                continue
            if now >= decided + parse_duration(h.get("escalate_after", "PT48H")):
                events.append(self._re_present(areq, hold_appr, "escalated: escalate_after elapsed"))
                continue
            n = int((now - decided) / parse_duration(h.get("renotify_after", "PT24H")))
            if n >= 1:
                key = f"{hold_appr['approval_id']}:renotify:{n}"
                if not self.store.receipt_by_key(key):
                    with self.store.tx() as t:
                        t.receipt(type="APPROVAL_REQUESTED", actor=WF, intent=f"HOLD re-notify #{n} (still held, not executed)",
                                  provenance_ids=[self.prov_id], idempotency_key=key, item_id=areq["item_id"],
                                  action_request_id=areq["action_request_id"], capability=areq["capability"],
                                  payload_hash=areq["payload_hash"], effect="none",
                                  before_state={"status": "held"}, after_state={"status": "held"})
                    events.append(f"renotify:{areq['action_request_id']}:{n}")
        return events

    def wake(self, areq_id: str, condition: str) -> str | None:
        areq = self.store.get("action-request", areq_id)
        if areq["status"] != "held":
            return None
        hold_appr = self.store.approvals_for(areq_id)[-1]
        if condition not in hold_appr["hold"]["wake_on"]:
            return None
        return self._re_present(areq, hold_appr, f"woke on {condition}")

    def _re_present(self, areq: dict, hold_appr: dict, why: str) -> str:
        with self.store.tx() as t:
            areq["status"] = "pending_approval"
            t.replace_action_request(areq)
            t.receipt(type="APPROVAL_REQUESTED", actor=WF, intent=f"HOLD {why} → re-presented to Michael (NOT executed)",
                      provenance_ids=[self.prov_id], idempotency_key=f"{hold_appr['approval_id']}:{why}",
                      item_id=areq["item_id"], action_request_id=areq["action_request_id"], capability=areq["capability"],
                      payload_hash=areq["payload_hash"], effect="none",
                      before_state={"status": "held"}, after_state={"status": "pending_approval"})
            self._sync_item_after_decision(t, areq["item_id"])
        return f"{why}:{areq['action_request_id']}"

    # ------------------------------------------------------------------ ACT
    def act(self, item_id: str) -> list:
        results = []
        for res in self.h.gateway.recover():
            results.append(res)
        for areq in self.store.action_requests(item_id=item_id, status="approved"):
            appr = self.store.approvals_for(areq["action_request_id"])[-1]
            res = self.h.gateway.execute(areq["action_request_id"], appr["approval_id"])
            results.append(res)
            if res.receipt is None or res.receipt["type"] != "ACTION_EXECUTED":
                continue
            er = res.receipt["effector_response"]
            self.trace(item_id).add("dry-run action", f"{areq['action_request_id']} → {er['provider']} status={er['status']} "
                                                      f"dry_run={er['dry_run']} packet {res.receipt['artifact_hashes'][0][:23]}…")
        return results

    # ------------------------------------------------------------------ OUTCOME (attribution)
    def record_attribution(self, item_id: str, attribution: dict) -> dict:
        outc_id, pid = self.ids.new("outc"), self.ids.new("prov")
        item = self.store.get("item", item_id)
        outc = {"outcome_id": outc_id, "item_id": item_id, "observed_at": self.now(), "kind": "lead_attributed",
                "attribution": attribution, "provenance_ids": [pid]}
        with self.store.tx() as t:
            t.put_provenance({"provenance_id": pid, "created_at": self.now(), "actor_type": "agent",
                              "agent_name": "agent-07-marketing", "basis": "FACT",
                              "source_uri": item["sources"][0]["url"], "fetched_at": item["sources"][0]["first_seen_at"]})
            t.put_outcome(outc)
            t.receipt(type="OUTCOME_RECORDED", actor={"type": "agent", "id": "agent-07-marketing"},
                      intent="lead attribution captured at intake", provenance_ids=[pid],
                      idempotency_key=f"attr:{item_id}", item_id=item_id, outcome_id=outc_id, entity_type="outcome",
                      entity_id=outc_id, effect="create")
            cur = self.store._load(t.cur, "items", "item_id", item_id)
            cur.setdefault("outcome_ids", []).append(outc_id)
            t.replace_item(cur)
        self.trace(item_id).add("source", f"attribution: {attribution}")
        return outc


def _diff(old: dict, new: dict) -> dict:
    out = {}
    for k in sorted(set(old) | set(new)):
        if old.get(k) != new.get(k):
            out[k] = {"from": copy.deepcopy(old.get(k)), "to": copy.deepcopy(new.get(k))}
    return out
