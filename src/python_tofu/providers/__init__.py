"""Provider implementations.

Importing a provider package (for example :mod:`python_tofu.providers.gcp`)
registers it with :mod:`python_tofu.core.provider`. The registry itself is
defined in core so providers depend on core, never the other way around.
"""

from python_tofu.core.provider import Provider, available_providers, get_provider, register_provider

__all__ = ["Provider", "available_providers", "get_provider", "register_provider"]
