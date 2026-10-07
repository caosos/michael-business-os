"""Human-readable end-to-end result: source → normalization → economics → recommendation → approval →
dry-run action → receipt → provenance, for each fixture item."""
from __future__ import annotations


def provenance_resolution(p: dict) -> str:
    kinds = []
    if p.get("source_uri") and p.get("fetched_at"):
        kinds.append(f"source `{p['source_uri']}` @ {p['fetched_at']}")
    if p.get("model_id") and p.get("model_version") and p.get("prompt_hash"):
        kinds.append(f"model `{p['model_id']}` v`{p['model_version']}` prompt `{p['prompt_hash'][:19]}…`")
    if p.get("approval_id"):
        kinds.append(f"human decision `{p['approval_id']}`")
    if p.get("tool_name") and p.get("tool_version"):
        kinds.append(f"tool `{p['tool_name']}@{p['tool_version']}`" + (f" config {p['config_version']}" if p.get("config_version") else ""))
    return "; ".join(kinds) if kinds else "**UNRESOLVED**"


def item_section(h, item_id: str, fixture: str) -> str:
    st, wf = h.store, h.workflow
    item = st.get("item", item_id)
    tr = wf.trace(item_id).stages
    out = [f"## {fixture} — `{item_id}`", "",
           f"**Type / category:** {item['type']} / {item['category']} ({item.get('subcategory', '')}) · "
           f"**final state:** `{item['state']}`", ""]

    def stage(title, key):
        out.extend([f"### {title}", ""])
        notes = [n for n in tr.get(key, []) if n]
        out.extend([f"- {n}" for n in notes] or ["- (none)"])
        out.append("")

    stage("1. Source", "source")
    stage("2. Normalization", "normalization")
    if tr.get("research"):
        stage("2b. Research findings", "research")
    stage("3. Economics", "economics")
    stage("4. Recommendation", "recommendation")
    stage("4b. Action requests (frozen payloads, PDP tier)", "action")
    stage("5. Approval (Michael: YES / NO / MODIFY / HOLD)", "approval")
    stage("6. Dry-run action", "dry-run action")

    receipts = st.receipts(item_id=item_id)
    out += ["### 7. Receipts (hash-chained ledger rows for this item)", "",
            "| seq | type | actor | intent | dry_run | row_hash |", "|---:|---|---|---|---|---|"]
    for r in receipts:
        dr = r.get("effector_response", {}).get("dry_run", "")
        intent = r["intent"].replace("|", "/")
        out.append(f"| {r['seq']} | `{r['type']}` | {r['actor']['type']}:{r['actor']['id']} | {intent} | {dr} | `{r['row_hash'][7:19]}…` |")
    chain = st.verify_chain()
    out += ["", f"Ledger `verify_chain`: **{'PASS' if chain.ok else 'FAIL'}** ({chain.checked} receipts in the whole ledger)", ""]

    pids = []
    for r in receipts:
        for p in r["provenance_ids"]:
            if p not in pids:
                pids.append(p)
    out += ["### 8. Provenance (every id cited by the receipts above, resolved)", "",
            "| provenance_id | actor | basis | resolves to |", "|---|---|---|---|"]
    for pid in pids:
        p = st.find_provenance(pid)
        if p is None:
            out.append(f"| `{pid}` | — | — | **MISSING** |")
            continue
        actor = p.get("agent_name") or p.get("human_actor") or p["actor_type"]
        out.append(f"| `{pid}` | {actor} | {p['basis']} | {provenance_resolution(p)} |")
    out.append("")
    return "\n".join(out)
