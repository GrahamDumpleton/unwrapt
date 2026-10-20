"""Two deferrals on Python 3.15, one each way.

The `lazy import` statement is native: the interpreter defers it, and
unwrapt is not involved. The import the configuration names is
unwrapt's: its shim defers that one, and reifies it at first use.
"""

import sys

lazy import colorsys

import decimal

print("native deferred colorsys:", "colorsys" not in sys.modules)
print("unwrapt deferred decimal:", "decimal" not in sys.modules)

_ = colorsys.rgb_to_hls(1, 0, 0)
_ = decimal.Decimal(1)
