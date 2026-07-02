"""seedwright data engine — the Python MCP server (ADR-0004).

Exposes the proven Python engine (authoring loop, deterministic generation, validation, file
export, Postgres load/teardown) as MCP tools consumed by the central Spring server over stdio.
Tool logic lives in plain, unit-tested functions; the MCP layer is a thin registration shim.
"""

__version__ = "0.0.1"
