"""
Agent Demo — LLM Agent with Tool Calling & MCP Support
=======================================================
A portable terminal agent that works with any OpenAI-compatible API
(OpenAI, Doubao/Volcengine, DeepSeek, Moonshot, Qwen, Zhipu, etc.)

Usage:
    python agent.py                 # default config.json
    python agent.py my_config.json  # custom config
"""

import asyncio
import json
import os
import sys

from openai import AsyncOpenAI

from memory import Memory
from tools import MCPClient, registry

# ── Optional pretty output via rich ──────────────────────────
try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel

    console = Console()

    def print_md(text: str) -> None:
        console.print(Markdown(text))

    def print_info(text: str) -> None:
        console.print(f"[dim]{text}[/dim]")

    def print_tool(text: str) -> None:
        console.print(f"  [cyan]↳ {text}[/cyan]")

    def print_banner(body: str) -> None:
        console.print(Panel(body, title="Agent Demo", border_style="blue"))

except ImportError:
    # Fallback: works without rich
    def print_md(text: str) -> None:
        print(text)

    def print_info(text: str) -> None:
        print(text)

    def print_tool(text: str) -> None:
        print(f"  → {text}")

    def print_banner(body: str) -> None:
        print(f"{'='*50}\n{body}\n{'='*50}")


# ─────────────────────────────────────────────────────────────
#  Agent
# ─────────────────────────────────────────────────────────────


class Agent:
    def __init__(self, config_path: str = "config.json"):
        self._load_env()
        self.cfg = self._read_json(config_path)

        self.client = AsyncOpenAI(
            api_key=os.getenv("API_KEY", self.cfg.get("api_key", "sk-placeholder")),
            base_url=self.cfg.get("base_url", "https://api.openai.com/v1"),
        )
        self.model = self.cfg.get("model", "gpt-4o")
        self.system_prompt = self.cfg.get(
            "system_prompt",
            "You are a helpful assistant. Answer in the user's language. "
            "Use tools when needed to accomplish tasks.",
        )
        self.max_iterations = self.cfg.get("max_tool_rounds", 15)

        self.builtin = registry
        self.mcp = MCPClient()
        self.memory = Memory(max_messages=self.cfg.get("max_messages", 100))
        self.memory.add("system", self.system_prompt)

    # ── Setup ────────────────────────────────────────────────

    @staticmethod
    def _load_env() -> None:
        """Load .env file if present (no hard dependency on python-dotenv)."""
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if not os.path.exists(env_path):
            return
        try:
            from dotenv import load_dotenv

            load_dotenv(env_path)
        except ImportError:
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip())

    @staticmethod
    def _read_json(path: str) -> dict:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    async def setup(self) -> None:
        mcp_servers = self.cfg.get("mcp_servers", {})
        if mcp_servers:
            print_info("Connecting to MCP servers …")
            await self.mcp.connect_from_config(mcp_servers)

    # ── Tool helpers ─────────────────────────────────────────

    async def _all_tools(self) -> list[dict]:
        tools = self.builtin.get_openai_tools()
        if self.mcp.sessions:
            tools += await self.mcp.list_tools()
        return tools

    async def _call_tool(self, name: str, arguments: dict) -> str:
        if self.mcp.has_tool(name):
            return await self.mcp.call_tool(name, arguments)
        return await self.builtin.call(name, arguments)

    # ── Core chat loop ───────────────────────────────────────

    async def chat(self, user_input: str) -> str:
        self.memory.add("user", user_input)
        tools = await self._all_tools()

        for _ in range(self.max_iterations):
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=self.memory.get_messages(),
                tools=tools or None,
            )
            msg = resp.choices[0].message

            # No tool calls → final answer
            if not msg.tool_calls:
                answer = msg.content or ""
                self.memory.add("assistant", answer)
                return answer

            # Record assistant message with tool_calls
            self.memory.add(
                "assistant",
                content=msg.content,
                tool_calls=[
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            )

            # Execute each tool call
            for tc in msg.tool_calls:
                fname = tc.function.name
                try:
                    fargs = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    fargs = {}

                args_preview = json.dumps(fargs, ensure_ascii=False)
                if len(args_preview) > 120:
                    args_preview = args_preview[:117] + "..."
                source = "MCP" if self.mcp.has_tool(fname) else "builtin"
                print_tool(f"[{source}] {fname}({args_preview})")

                result = await self._call_tool(fname, fargs)
                self.memory.add("tool", content=result, tool_call_id=tc.id)

        return "(Reached max tool iterations – stopping.)"

    # ── Interactive terminal ─────────────────────────────────

    async def run(self) -> None:
        await self.setup()

        builtin_count = len(self.builtin.tools)
        mcp_count = len(self.mcp.tool_map)
        print_banner(
            f"Model   : {self.model}\n"
            f"Base URL: {self.client.base_url}\n"
            f"Tools   : {builtin_count} built-in, {mcp_count} MCP\n\n"
            "Commands: /tools  /clear  /save  /load  /quit"
        )

        try:
            while True:
                try:
                    user_input = await asyncio.to_thread(
                        input, "\n👧 You: "
                    )
                    user_input = user_input.strip()
                except (EOFError, KeyboardInterrupt):
                    break

                if not user_input:
                    continue

                if user_input.startswith("/"):
                    await self._command(user_input)
                    continue

                print()
                response = await self.chat(user_input)
                print()
                print_md(response)

        finally:
            await self.mcp.close()
            print_info("\nBye!")

    async def _command(self, cmd: str) -> None:
        parts = cmd.split(maxsplit=1)
        c = parts[0].lower()

        if c in ("/quit", "/exit", "/q"):
            raise KeyboardInterrupt

        elif c == "/clear":
            self.memory.clear()
            print_info("Memory cleared.")

        elif c == "/save":
            path = parts[1] if len(parts) > 1 else "chat_history.json"
            self.memory.save(path)
            print_info(f"Saved → {path}")

        elif c == "/load":
            path = parts[1] if len(parts) > 1 else "chat_history.json"
            if self.memory.load(path):
                print_info(f"Loaded ← {path}")
            else:
                print_info(f"Not found: {path}")

        elif c == "/tools":
            all_t = await self._all_tools()
            print_info(f"\nAvailable tools ({len(all_t)}):")
            for t in all_t:
                fn = t["function"]
                src = "MCP" if self.mcp.has_tool(fn["name"]) else "   "
                desc = (fn.get("description") or "")[:60]
                print_info(f"  [{src}] {fn['name']} — {desc}")

        else:
            print_info(f"Unknown command: {c}")


# ─────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────


async def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.json"
    agent = Agent(config_path)
    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
