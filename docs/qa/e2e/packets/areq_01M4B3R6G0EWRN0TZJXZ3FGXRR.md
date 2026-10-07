# MANUAL-ASSIST PACKET — DRY-RUN

> **Nothing was sent, posted, or paid by the system.** This packet is the exact text Michael
> approved. Acting on it is a manual choice outside the system.

- Packet format: `manual-assist-packet/1`
- Action request: `areq_01M4B3R6G0EWRN0TZJXZ3FGXRR` (item `itm_01M4B3R6G0H4QX4FR84G98PBSK`)
- Capability / category: `comms.email.send` / `email` · tier 0 · irreversible
- Channel: email (platform relay)
- Target ref: `relay:QA-FLIP-0001`
- Approved by: michael via `cli` at 2026-10-07T12:00:00Z (`appr_01M4B3R6G0YS30M2BWJXNZ8V39`) — **SIMULATED fixture decision, not Michael**
- Approved payload hash: `sha256:3b163622fa25aebf2b26925e13495dcc46fcc30b4ae8ae16538ac467cdfbe8f0`
- Draft content hash: `sha256:cd893e98831a73f392825639e75b6e37398021821a8fd32af44f9bb71ab9b08d` · template `seller_inquiry_v1@1` · model `none:deterministic-template`
- AI-generated content: no (deterministic template)

## Content

**Subject:** Question about your 6x12 enclosed utility trailer

**Body:**

```text
Hi,

I saw your listing for the 6x12 enclosed utility trailer in Conway. Is it still available?
- Are the axles and tires sound?
- Is the title clear and in your name?
If everything checks out I could pay $850 cash and pick it up myself.
This is a question, not a binding offer.

Thanks,
Michael
```

## Manual steps (only if you choose to act)

1. Use the platform relay address on file (target ref above); the system never stores raw contact values here.
2. Send the Subject and Body exactly as shown, or do not send at all.
3. If the counterparty replies, log the reply so the item can move forward.

## Compliance checklist

- [ ] One-to-one reply to a public listing / inbound request — not bulk marketing.
- [ ] No pressure tactics; no binding offer language (tier-0 external commitment rule).

## Provenance

- `prov_01M4B3R6G0EG1YRSN7GYAYEREH`

Verify: `sha256(canonical(payload)) == sha256:3b163622fa25aebf2b26925e13495dcc46fcc30b4ae8ae16538ac467cdfbe8f0`
