"""An application whose import is deferred by configuration alone.

Nothing in this file mentions laziness: the external configuration
names the import, and the bootstrap installs the hook.
"""

import sys

import decimal

print("decimal loaded at startup:", "decimal" in sys.modules)

_ = decimal.Decimal(1)

print("after first use:", type(decimal))
