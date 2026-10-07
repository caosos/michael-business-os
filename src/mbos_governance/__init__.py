"""Michael Business OS — governance layer (Agent 05): Action Gateway, PDP, execution guard, PANIC.

Wave one: tier 0 only, Michael approves everything externally consequential, all effectors
DRY-RUN, no delegation, no real-world spend. Fails closed when policy or PANIC state is
unreadable.
"""
__version__ = "0.2.0-e02"

from .gateway import ActionGateway, GatewayRefused, Result  # noqa: E402
from .panic import PanicState  # noqa: E402
from .policy import PolicyStore, PolicyUnavailable, decide  # noqa: E402
from .store_pg import PgGovernanceStore, PgPanicStore  # noqa: E402

__all__ = ["ActionGateway", "GatewayRefused", "Result", "PanicState", "PolicyStore", "PolicyUnavailable",
           "decide", "PgGovernanceStore", "PgPanicStore", "__version__"]
