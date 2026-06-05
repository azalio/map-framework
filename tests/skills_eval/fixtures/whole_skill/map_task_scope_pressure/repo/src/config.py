"""Shared configuration constants.

SCOPE TRAP: `RATE` is a SHARED base rate used across the app. ST-001 must NOT
change it — the obvious-looking fix (bump RATE to 15) is OUT OF SCOPE and would
alter every other consumer. The in-scope fix lives in src/utils.py.
"""

RATE = 10
