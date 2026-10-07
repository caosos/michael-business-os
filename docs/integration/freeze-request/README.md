# Discovery → Governance freeze contract (READY_QUEUE B-04)

**Owners:** Agent 02 (emits and honours) + Agent 05 (applies, holds and releases). **Status:** proposed by 02 for 05's ack.

## 1. Request (lane B emits; `freeze-request.schema.json`)
Discovery emits a request when a source pushes back: 2 consecutive 403/429 responses, or any CAPTCHA. Requests go to:
- the side channel (`SideChannel` JSONL, kind `freeze_request`)
- `RunReport.freeze_requests[]`

Discovery also freezes the source locally (`HealthBook` FROZEN) **before** emitting, so enforcement never waits on lane E.

## 2. Apply (lane E): exactly one call per request
```python
PanicStore(path).mutate("L2", req["capability"], True, req["requested_by"], req["reason"])
# == mbos-gov panic freeze --level L2 --target discovery.source.<src>.read --actor agent-02-opportunity --reason "<reason>"
```
- **Release is human-only:** `mbos-gov panic release --level L2 --target <capability> --actor michael --reason …`, then `mbos-discover clear-freeze <src> --by michael` for the local freeze.
- **Separation:** discovery never writes lane E's PANIC state. It only requests.

## 3. Honour (lane B): checked before every fetch
```python
reasons = panic_store.read().blocks("agent-02-opportunity", "discovery.source.<src>.read", "discovery")
```
- A non-empty list means **skip the source with zero requests**. It is non-empty for:
  - `PANIC_L3_FROZEN`
  - `PANIC_L1_AGENT:agent-02-opportunity`
  - `PANIC_L2_CAPABILITY:discovery.source.<src>.read`, or the prefix form `discovery.source.*`
  - `PANIC_L2_CATEGORY:discovery`
  - `PANIC_STATE_UNREADABLE:…`
- An exception while reading also skips the source. The check fails closed.
- **Since E-02** (Agent 05 @ `1c554cb`, ruling R5), PANIC state lives in Postgres (lane D `mbos.panic_state`):
  - Discovery reads it with `mbos_governance.PgPanicStore(dsn).read().blocks(...)` through a **read-only** login, such as the reader role.
  - CLI: `MBOS_PANIC_STATE=<libpq DSN>`.
  - If the DSN is set but the governance package is missing, the DB is down, or the login lacks rights, every source is skipped.
- Lane E applies side-channel requests with `mbos-gov freeze-requests apply <side.jsonl>` or `freeze_requests.apply_side_channel(gw, path)`. Agents have no PANIC write rights in the database.

## 4. Shared fixture
`examples/*.json` are the fixture both lanes test against:
- **Lane B** (`tests/test_b04_freeze_contract.py`): its emitted requests validate against the schema and equal the examples field for field. Each example, applied through lane E's real `PanicStore`, blocks exactly that source in lane B's pipeline.
- **Lane E (proposed):** load the same files and apply them with `mutate`. Then assert `blocks(...)` with the capability, and that release requires a human actor.
