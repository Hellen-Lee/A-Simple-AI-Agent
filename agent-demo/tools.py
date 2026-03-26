"""Tool system with built-in tools and MCP server integration."""

import asyncio
import inspect
import json
import os
import subprocess
from contextlib import AsyncExitStack
from typing import Any, Callable, Optional

# MCP SDK (optional dependency)
try:
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client, StdioServerParameters
    from mcp.client.sse import sse_client

    HAS_MCP = True
except ImportError:
    HAS_MCP = False


# ─────────────────────────────────────────────────────────────
#  Built-in Tool System
# ─────────────────────────────────────────────────────────────


class Tool:
    """A single callable tool with OpenAI-compatible schema."""

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict,
        func: Callable,
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.func = func

    def to_openai_tool(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Registry for built-in Python tools."""

    def __init__(self):
        self.tools: dict[str, Tool] = {}

    def register(
        self,
        name: Optional[str] = None,
        description: str = "",
        parameters: Optional[dict] = None,
    ):
        """Decorator to register a function as a tool."""

        def decorator(func: Callable):
            tool_name = name or func.__name__
            tool_desc = description or (func.__doc__ or "").strip()
            tool_params = parameters or self._infer_parameters(func)
            self.tools[tool_name] = Tool(tool_name, tool_desc, tool_params, func)
            return func

        return decorator

    def _infer_parameters(self, func: Callable) -> dict:
        sig = inspect.signature(func)
        props, required = {}, []
        type_map = {str: "string", int: "integer", float: "number", bool: "boolean"}
        for pname, param in sig.parameters.items():
            annotation = param.annotation
            props[pname] = {"type": type_map.get(annotation, "string")}
            if param.default is inspect.Parameter.empty:
                required.append(pname)
        return {"type": "object", "properties": props, "required": required}

    async def call(self, name: str, arguments: dict) -> str:
        tool = self.tools.get(name)
        if not tool:
            return json.dumps({"error": f"Tool '{name}' not found"})
        try:
            result = tool.func(**arguments)
            if asyncio.iscoroutine(result):
                result = await result
            return str(result)
        except Exception as e:
            return json.dumps({"error": f"{type(e).__name__}: {e}"})

    def get_openai_tools(self) -> list[dict]:
        return [t.to_openai_tool() for t in self.tools.values()]


# ─────────────────────────────────────────────────────────────
#  MCP Client
# ─────────────────────────────────────────────────────────────


class MCPClient:
    """Manages connections to one or more MCP servers (stdio / SSE)."""

    def __init__(self):
        self._stack = AsyncExitStack()
        self.sessions: dict[str, ClientSession] = {}
        self.tool_map: dict[str, str] = {}  # tool_name → server_name

    async def connect_from_config(self, servers: dict) -> None:
        for name, cfg in servers.items():
            transport = cfg.get("transport", "stdio")
            try:
                if transport == "stdio":
                    await self._connect_stdio(name, cfg)
                elif transport == "sse":
                    await self._connect_sse(name, cfg)
                else:
                    print(f"  ✗ Unknown transport '{transport}' for '{name}'")
                    continue
                tools = await self.sessions[name].list_tools()
                for t in tools.tools:
                    self.tool_map[t.name] = name
                print(f"  ✓ [{name}] connected ({transport}, {len(tools.tools)} tools)")
            except Exception as e:
                print(f"  ✗ [{name}] failed: {e}")

    async def _connect_stdio(self, name: str, cfg: dict) -> None:
        if not HAS_MCP:
            raise ImportError("pip install mcp")
        merged_env = {**os.environ, **(cfg.get("env") or {})}
        params = StdioServerParameters(
            command=cfg["command"],
            args=cfg.get("args", []),
            env=merged_env,
        )
        read, write = await self._stack.enter_async_context(stdio_client(params))
        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self.sessions[name] = session

    async def _connect_sse(self, name: str, cfg: dict) -> None:
        if not HAS_MCP:
            raise ImportError("pip install mcp")
        read, write = await self._stack.enter_async_context(
            sse_client(cfg["url"], headers=cfg.get("headers"))
        )
        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self.sessions[name] = session

    async def list_tools(self) -> list[dict]:
        tools = []
        for session in self.sessions.values():
            result = await session.list_tools()
            for t in result.tools:
                schema = t.inputSchema or {"type": "object", "properties": {}}
                tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": t.name,
                            "description": t.description or "",
                            "parameters": schema,
                        },
                    }
                )
        return tools

    async def call_tool(self, name: str, arguments: dict) -> str:
        server = self.tool_map.get(name)
        if not server:
            return json.dumps({"error": f"MCP tool '{name}' not found"})
        try:
            result = await self.sessions[server].call_tool(name, arguments=arguments)
            parts = []
            for item in result.content:
                parts.append(item.text if hasattr(item, "text") else str(item))
            return "\n".join(parts) or "(empty)"
        except Exception as e:
            return json.dumps({"error": f"{type(e).__name__}: {e}"})

    def has_tool(self, name: str) -> bool:
        return name in self.tool_map

    async def close(self) -> None:
        await self._stack.aclose()


# ─────────────────────────────────────────────────────────────
#  Built-in Tool Definitions
# ─────────────────────────────────────────────────────────────

registry = ToolRegistry()


@registry.register(
    name="execute_command",
    description="Execute a shell command and return stdout/stderr.",
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to run",
            },
        },
        "required": ["command"],
    },
)
def execute_command(command: str) -> str:
    try:
        r = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=60
        )
        out = r.stdout.strip()
        if r.stderr.strip():
            out += f"\n[stderr] {r.stderr.strip()}"
        if r.returncode != 0:
            out += f"\n[exit {r.returncode}]"
        return out or "(no output)"
    except subprocess.TimeoutExpired:
        return "[error] Command timed out (60s)"
    except Exception as e:
        return f"[error] {e}"


@registry.register(
    name="read_file",
    description="Read the text content of a file.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to read"},
        },
        "required": ["path"],
    },
)
def read_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"[error] {e}"


@registry.register(
    name="write_file",
    description="Write content to a file, creating parent directories as needed.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to write"},
            "content": {"type": "string", "description": "Content to write"},
        },
        "required": ["path", "content"],
    },
)
def write_file(path: str, content: str) -> str:
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Wrote {len(content)} chars → {path}"
    except Exception as e:
        return f"[error] {e}"


@registry.register(
    name="list_directory",
    description="List files and subdirectories in a path.",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path (default: current directory)",
            },
        },
        "required": [],
    },
)
def list_directory(path: str = ".") -> str:
    try:
        entries = sorted(os.listdir(path))
        lines = []
        for e in entries:
            full = os.path.join(path, e)
            prefix = "📁 " if os.path.isdir(full) else "   "
            lines.append(f"{prefix}{e}")
        return "\n".join(lines) or "(empty)"
    except Exception as e:
        return f"[error] {e}"
