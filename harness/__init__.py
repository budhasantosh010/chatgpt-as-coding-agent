"""chatgpt-code-harness: a local MCP coding server driven by ChatGPT.

ChatGPT is the reasoning loop; this package is the hands. It exposes
Claude-Code-style tools (read/write/edit/list/glob/grep/shell + workspace
orientation) over Streamable-HTTP MCP, confined to approved workspace roots,
reachable from ChatGPT through a Tailscale Funnel + secret route.

No model-provider API is ever called from here.
"""

__version__ = "0.1.0"
