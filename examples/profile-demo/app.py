"""A small application shaped for profiling: a few eager imports of
varying weight, a nest, and a from-import."""

import decimal
import sqlite3
import xml.dom

import helpers.rendering
import helpers.xmlbits
