"""ark-agentic Agents — bundled agent implementations.

Agents are *products*, not infrastructure. They live alongside ``core/``
and ``plugins/`` (built-in features). Discovery is filesystem-driven by
``core.runtime.discovery.discover_and_register_agents`` against the
path returned by ``core.utils.env.get_agents_root`` (or ``AGENTS_ROOT``
when set explicitly), so this package is just a container of
sub-packages — no registry shim lives here.

Each agent package may expose a top-level ``register(registry, **opts)``
function. Common ``opts`` include ``enable_memory`` and ``enable_dream``;
individual agents pick what they need and ignore the rest via ``**_``.
"""
