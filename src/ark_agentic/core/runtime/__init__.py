"""Core runtime Lifecycle components — always-on building blocks.

These are NOT plugins (they're not user-selectable). They live in core
because they implement core capabilities (agent registration, tracing)
and just happen to share the Lifecycle contract so Bootstrap can drive
them uniformly alongside plugins.
"""
