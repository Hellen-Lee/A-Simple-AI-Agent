# Agent Demo

一个轻量级终端 AI Agent，支持 **多模型 API 调用**、**Tool Calling**、**MCP 工具** 和 **对话记忆**。

基于 OpenAI 兼容接口，可无缝切换豆包/火山引擎、OpenAI、DeepSeek、Moonshot、通义千问、智谱等模型服务。

## 项目结构

```
agent-demo/
  agent.py          # 主 Agent 实现（入口）
  tools.py          # 内置工具 + MCP 客户端
  memory.py         # 对话记忆管理
  config.json       # 配置文件
  .env.example      # 环境变量模板
  requirements.txt  # Python 依赖
```

## 快速开始

### 1. 安装依赖

```bash
cd agent-demo
pip install -r requirements.txt
```

### 2. 配置 API Key

```bash
cp .env.example .env
```

编辑 `.env`，填入你的 API Key：

```
API_KEY=your-api-key-here
```

### 3. 配置模型（可选）

编辑 `config.json`，修改模型和 API 地址。预置为豆包，也可以切换为其他服务：

| 服务商 | `base_url` | `model` 示例 |
|--------|-----------|--------------|
| 豆包/火山引擎 | `https://ark.cn-beijing.volces.com/api/v3` | `doubao-1.5-pro-256k-250115` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` |
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` |
| Moonshot | `https://api.moonshot.cn/v1` | `moonshot-v1-128k` |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| 智谱 AI | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-plus` |

### 4. 启动

```bash
python agent.py
```

## 终端命令

| 命令 | 说明 |
|------|------|
| `/tools` | 列出所有可用工具 |
| `/clear` | 清空对话记忆 |
| `/save [path]` | 保存对话历史 |
| `/load [path]` | 加载对话历史 |
| `/quit` | 退出 |

## 内置工具

| 工具名 | 功能 |
|--------|------|
| `execute_command` | 执行 Shell 命令 |
| `read_file` | 读取文件内容 |
| `write_file` | 写入文件 |
| `list_directory` | 列出目录内容 |

## MCP 工具集成

在 `config.json` 中配置 MCP 服务器即可自动加载其工具：

```json
{
  "mcp_servers": {
    "filesystem": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
    },
    "web-search": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-brave-search"],
      "env": {
        "BRAVE_API_KEY": "your-brave-key"
      }
    },
    "remote-server": {
      "transport": "sse",
      "url": "http://localhost:3000/sse"
    }
  }
}
```

支持两种传输方式：
- **stdio** — 本地子进程（适用于大多数 MCP server）
- **sse** — HTTP Server-Sent Events（适用于远程服务）

## 扩展自定义工具

在 `tools.py` 中用装饰器注册即可：

```python
@registry.register(
    name="my_tool",
    description="Do something useful",
    parameters={
        "type": "object",
        "properties": {
            "input": {"type": "string", "description": "The input"},
        },
        "required": ["input"],
    },
)
def my_tool(input: str) -> str:
    return f"Result: {input}"
```

支持同步和异步函数，Agent 会自动识别。

## 工作原理

```
User Input
    │
    ▼
┌──────────┐     ┌──────────────┐
│  Agent   │────▶│ LLM API      │
│  Loop    │◀────│ (tool_calls) │
└──────────┘     └──────────────┘
    │  ▲
    │  │ results
    ▼  │
┌──────────┐     ┌──────────────┐
│  Tool    │────▶│ Built-in     │
│  Router  │     │ MCP Servers  │
└──────────┘     └──────────────┘
```

Agent 采用 ReAct 循环：LLM 决定是否调用工具 → 执行工具 → 将结果反馈给 LLM → 重复直到给出最终回答。

## 环境要求

- Python >= 3.10
- 网络能访问所配置的模型 API

## License

MIT
