The negarena family cannot be registered against the real plugin registry.

A maintainer ruling (PR #73) added this family's exact identity to `TRUSTED_BUILTIN_PLUGIN_KEYS`, so it should be registered the way the other in-tree families are, through the trusted in-tree path. `register_plugin` in `aeread_families/negarena/environment.py` still goes through the contribution admission gate, which no longer applies to it, and registering the plugin against a real `PluginRegistry` fails.
