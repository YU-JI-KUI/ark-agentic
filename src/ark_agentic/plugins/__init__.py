"""Built-in plugins — optional features that opt into the host app.

Each sub-package exposes a Plugin class (per ``core.plugin.Plugin``).
The host registers them in a static list (``app.PLUGINS``) and drives
their lifecycle uniformly. Future third-party plugins can be discovered
via ``importlib.metadata`` entry_points without changes here.
"""
