"""Michael Business OS — DISCOVER + NORMALIZE lane (Agent 02).

Read-only SourceAdapters fetch opportunity data, retain every raw payload by content
hash (`raw_ref`), normalize it into canonical Item v1 (frozen contracts v1.0.0), and
deduplicate across repeated runs and across sources. Nothing in this package contacts
sellers, bids, buys, posts or sends; the HTTP layer refuses anything but allow-listed reads.
"""

__version__ = "0.1.0"

AGENT_ID = "agent-02-opportunity"        # agent id = branch name (ruling R7; 05 policy.v1.json)
CONTRACT_VERSION = "1.0.0"
NORMALIZER_VERSION = "2026.10.0"
