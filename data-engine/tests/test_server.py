"""The MCP server shim: exposes the engine functions as MCP tools over stdio.

Verified through the SDK's in-memory client session — the same protocol path the central Spring
server will use, without a subprocess.
"""

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from seedwright_data_engine.server import create_server

EXPECTED_TOOLS = {
    "author_generator",
    "generate_dataset",
    "validate_dataset",
    "export_dataset",
    "load_postgres",
    "teardown_postgres",
}


@pytest.mark.anyio
async def test_server_exposes_expected_tools() -> None:
    server = create_server()
    async with create_connected_server_and_client_session(
        server._mcp_server  # noqa: SLF001 - documented FastMCP escape hatch for in-memory tests
    ) as client:
        listed = await client.list_tools()
        names = {tool.name for tool in listed.tools}
        assert EXPECTED_TOOLS <= names


@pytest.mark.anyio
async def test_author_tool_roundtrip() -> None:
    server = create_server()
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        result = await client.call_tool(
            "author_generator",
            {
                "schema": {
                    "customers": {
                        "columns": [
                            {"name": "id", "sql_type": "bigint"},
                            {"name": "email", "sql_type": "varchar(255)"},
                        ],
                        "primary_key": ["id"],
                    }
                },
                "rules": [],
                "volumes": {"customers": 10},
                "seed": 5,
            },
        )
        assert result.isError is False
        assert result.structuredContent is not None
        assert result.structuredContent["version"].startswith("ga_")
