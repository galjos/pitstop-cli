"""Exercise the installed CLI and optional stdio MCP server without network access."""

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


async def check_mcp(env):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=["-m", "pitstop.mcp_server"], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            assert {t.name for t in tools} == {
                "find_stations", "find_cheapest", "find_chargers", "find_places", "list_fuels", "get_stats"
            }
            assert all(t.annotations and t.annotations.readOnlyHint and
                       t.annotations.destructiveHint is False for t in tools)
            result = await session.call_tool("find_places", {"query": "Livo"})
            assert not result.isError and result.structuredContent["matched_count"] == 2
            assert {p["provincia"] for p in result.structuredContent["places"]} == {"CO", "TN"}
            result = await session.call_tool("find_chargers", {"near": "nan,11"})
            assert result.isError
    print("Installed MCP: six read-only tools, structured discovery, invalid-input error passed")


def main():
    from pitstop.version import __version__

    with tempfile.TemporaryDirectory(prefix="pitstop-install-smoke-") as directory:
        cache = Path(directory) / "pitstop"
        cache.mkdir()
        (cache / "comuni_main.csv").write_text(
            "comune,pro_com_t,lat,long,sigla\n"
            "Livo,013130,46.17,9.30,CO\nLivo,022106,46.40,11.02,TN\n"
        )
        env = dict(os.environ, XDG_CACHE_HOME=directory)
        cli = [str(Path(sys.executable).parent / "pitstop")]
        version = subprocess.run([*cli, "--version"], env=env, capture_output=True, text=True, check=True, timeout=15)
        assert __version__ in version.stdout
        places = subprocess.run([*cli, "places", "Livo", "--json"], env=env,
                                capture_output=True, text=True, check=True, timeout=15)
        assert json.loads(places.stdout)["matched_count"] == 2
        invalid = subprocess.run([*cli, "stations", "--near", "nan,11", "--json"],
                                 env=env, capture_output=True, text=True, timeout=15)
        assert invalid.returncode == 2 and invalid.stdout == ""
        print("Installed CLI: version, municipality discovery, invalid-input error passed")
        if importlib.util.find_spec("mcp"):
            asyncio.run(asyncio.wait_for(check_mcp(env), timeout=30))
        else:
            print("MCP extra absent; base installation passed")


if __name__ == "__main__":
    main()
