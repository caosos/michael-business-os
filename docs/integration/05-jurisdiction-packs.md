# Jurisdiction packs and `eligibility(job, packs)` (E-19)

- **Owner:** Agent 05
- **Sources:** ADR-0013 §8 and `DEAL_SNIFFER_START_HERE.md` §12.
- **Status:** format and evaluator only. The pilot data is a **synthetic fixture** (`sample: true`). No real jurisdiction, regulator or legal fact is asserted.
- **Files:**
  - Data and schema: `policy/jurisdiction/{jurisdiction_rules.v1.json, pack.schema.json, packs/sample-pilot.v1.json}`
  - Code: `src/mbos_governance/jurisdiction.py`
  - Tests: `tests/test_e19_jurisdiction.py`
  - CLI: `mbos-gov jurisdiction check` and `mbos-gov jurisdiction eligibility --job FILE`

## Pack
`{pack_id, jurisdiction, job_class, rule, source, date_verified, credential_required, permit_notes, confidence, unresolved[], threshold?, verified_by?, sample}`
- `jurisdiction` is a slash path (`STATE/COUNTY/CITY`). The job supplies its own chain, broadest to most specific. **Nothing is geocoded or inferred.**
- `credential_required` holds specific E-18 credential ids.
  - `[]` means the pack affirmatively finds no credential required.
  - `null` means it could not determine the requirement.
- `threshold` (for example `value_usd < 1000`) limits when the rule applies.
- **A real pack** (`sample: false`) must cite a URL or `citation:` and name a `verified_by`. A sample pack must use `SYNTHETIC-FIXTURE` and a `SAMPLE-*` jurisdiction.

## `eligibility(job, packs)`
`job = {job_class, jurisdiction_chain, scope?: {value_usd}, provider_claims?: [E-18 claims]}` → `{status, authoritative, sample, credential_required, missing_credentials, confidence, cited{pack_id, jurisdiction, rule, source, date_verified, permit_notes}, unresolved, reasons[]}`.

| Situation | Result |
|---|---|
| No pack for the job class or place on the chain | **UNKNOWN** (`NO_PACK`). Never "no licence needed". |
| Job lacks a jurisdiction chain, or the chain is not nested | **UNKNOWN** (`NO_JURISDICTION`). |
| A threshold pack and the job lacks the field | **UNKNOWN** (`MISSING_JOB_FIELD`). |
| Packs at the same level disagree | **UNKNOWN** (`CONFLICT`). |
| The most specific applicable pack requires a credential | **needs_credential**, with the cited rule. It becomes **eligible** only if the provider holds *every* required credential with a valid E-18 claim: verified, unexpired, and checked in a jurisdiction on this chain. |
| The pack finds no credential required | **eligible**, but only if it is fresh and confident (>= 0.7 after the age factor) with no open questions. Otherwise **UNKNOWN** (`UNCERTAIN`). |
| `credential_required: null` | **UNKNOWN** (`UNRESOLVED`). |
| Pack older than the staleness limits | confidence x 0.7 (> 180 days) or x 0.4 (> 365 days). Beyond 730 days: **UNKNOWN** (`EXPIRED_PACK`). |

- **The evaluator knows no local law.** It has no city or county constants. A test scans its source for such assumptions.
- **Uncertainty only keeps a requirement.** Low confidence never removes a requirement, but it also cannot clear one.
- **`gate(result)`:**
  - an authoritative eligible result → `allow`
  - `needs_credential` → `block_until_credential`
  - UNKNOWN or a sample pack → `ask_michael`
  - A sample fixture can never unblock a job.

## Not done (and why)
- **No real pack.** Researching and citing real local rules (and dating them) is a separate piece of work that needs sources and, for what Michael holds, his answers (`licenses_held`). It is the earlier E-17 proposal (the authoritative license-gated list), which is now better framed as "author real packs with this format".
- **No wiring into the PDP** (a license-gated job Michael lacks a licence for → deny outbound offers). That belongs with the campaign and card work, once real packs exist.
