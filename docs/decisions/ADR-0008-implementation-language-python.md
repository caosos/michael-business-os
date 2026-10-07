# Decision

ADR-0008 — Primary implementation language: Python

Status: PROPOSED. **PENDING MICHAEL** (decision packet P1). It does not block anything until the round-two build starts.

## Context
The language has to be chosen before any MVP code is written. Agent 04 lists "Python/FastAPI vs TS" as an UNKNOWN.

## Options
- **Python:**
  - DBOS Transact (Python SDK), LangGraph, Pydantic AI and the LiteLLM SDK/proxy are all Python-first.
  - 02's collectors (nodriver, pycraigslist, pysam, feedparser, Scrapy) are Python.
  - 06's owned-voice path (Pipecat) is Python.
  - 03's formulas map naturally onto Python with Pydantic models generated from the JSON Schemas.
- **TypeScript:**
  - DBOS, LangGraph.js and the MCP TS SDK are strong.
  - Twenty is TypeScript.
  - Weaker fit for 02's scraping libraries and 06's Pipecat path.

## Recommendation
**Python 3.12+**, using Pydantic v2 models generated from `docs/research/contracts/*.schema.json`. TypeScript is allowed only for UI or Twenty-side glue.

Evidence: FACT, from the language support listed for each tool in 01 §6, 02 §3 and 06 §2.B. INFERENCE: it is the lowest-friction single language across 5 of the 6 specialist stacks.

Reversibility: Low once code exists. That is why Michael should confirm it before round two.
