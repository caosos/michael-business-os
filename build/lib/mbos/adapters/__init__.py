"""Adapters that put REAL specialist-lane implementations behind the spine's interfaces
(src/mbos/interfaces.py). Each imports its lane's package lazily; the lane package is installed
from that lane's branch, never vendored or merged here."""
