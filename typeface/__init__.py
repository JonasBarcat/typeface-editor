"""Editor tipográfico de borradores de Base Tucumán."""

import logging

__version__ = "0.1.0"

_log = logging.getLogger("typeface")
_log.addHandler(logging.NullHandler())
_log.propagate = False
