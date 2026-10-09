"""Shared pytest setup.

The API intentionally requires a service key at runtime. Unit tests default to
its explicitly supported local-only bypass; authentication tests opt back in
per test by setting AI2_AUTH_DISABLED=false and a test key.
"""

import os

os.environ.setdefault("AI2_AUTH_DISABLED", "true")
