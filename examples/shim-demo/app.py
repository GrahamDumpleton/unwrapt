"""A one-file application whose own source declares an import lazy.

PEP 810 lets a module list the whole-module imports its top level
should defer in __lazy_modules__: on Python 3.15 the interpreter
handles the list natively, and below 3.15, with unwrapt's shim
installed, the behaviour is the same. The list is ordinary valid code
on every version.
"""

import sys

__lazy_modules__ = ["xml.dom"]
import xml.dom

print("xml.dom loaded at startup:", "xml.dom" in sys.modules)

_ = xml.dom.Node

print("after first use:", type(xml.dom))
