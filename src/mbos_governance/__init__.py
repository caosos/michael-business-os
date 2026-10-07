"""Michael Business OS — governance layer (Agent 05): Action Gateway, PDP, execution guard, PANIC.

Wave one: tier 0 only, Michael approves everything externally consequential, all effectors
DRY-RUN, no delegation, no real-world spend. Fails closed when policy or PANIC state is
unreadable.
"""
__version__ = "0.1.0-wave1"

from .gateway import ActionGateway, GatewayRefused, Result  # noqa: E402
from .panic import PanicStore  # noqa: E402
from .policy import PolicyStore, PolicyUnavailable, decide  # noqa: E402
from .store import GovernanceStore  # noqa: E402

__all__ = ["ActionGateway", "GatewayRefused", "Result", "PanicStore", "PolicyStore", "PolicyUnavailable",
           "decide", "GovernanceStore", "__version__"]
