"""
开发计划：

MCP协议是由Anthropic在2024年11月提出的。分为mcp client客户端和mcp server服务端两部分。
用户将提示词发送给客户端，客户端会扫描所有server中的工具（一个server可以有多个工具），
将工具列表+用户提示词发送给大模型，并监听大模型回答，客户端一旦检测到特定的触发条件（感兴趣自己去看MCP源码），就会执行相应的工具操作。
工具执行完毕后，客户端会将已有上下文和工具执行结果进行拼接，发送给大模型继续生成回答。
mcp server有三种对外暴露方式：stdio命令行、sse网络协议、streamable网络协议。stdio最快最方便，streamable最安全，sse狗都不用。
mcp server中每个函数都是一个工具，工具分为三类：资源类、工具类、提示词类。对应三种装饰器：
@mcp.resource()
@mcp.tool()
@mcp.prompt()

官方项目给出了一个示例：
FastMCP quickstart example.

cd to the `examples/snippets/clients` directory and run:
    uv run server fastmcp_quickstart stdio

# Create an MCP server
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("Demo")

# Add an addition tool
@mcp.tool()
def add(a: int, b: int) -> int:
    '''Add two numbers'''
    return a + b

# Add a dynamic greeting resource
@mcp.resource("greeting://{name}")
def get_greeting(name: str) -> str:
    '''Get a personalized greeting'''
    return f"Hello, {name}!"

# Add a prompt
@mcp.prompt()
def greet_user(name: str, style: str = "friendly") -> str:
    '''Generate a greeting prompt'''
    styles = {
        "friendly": "Please write a warm, friendly greeting",
        "formal": "Please write a formal, professional greeting",
        "casual": "Please write a casual, relaxed greeting",
    }

    return f"{styles.get(style, styles['friendly'])} for someone named {name}."
    
if __name__ == "__main__":
    mcp.run(transport="stdio")
    # mcp.run(transport="sse")
    # mcp.run(transport="streamable-http")


注意，MCP工具的输入来自大模型，输出交给大模型，所以函数传参和return都要是字符串。
哲学：AI是一个梭子服务，两头小中间大，输入输出都是字符串或图片，不占用太多网速，中间处理需要海量算力。所以这种梭子服务天生适合在云端机房中运行。
2026年NVIDIA总裁黄仁勋鼓吹AI PC，相继推出DGX spark和RTX spark，想把本应轻量化的PC做成重资产，这违背了梭子服务的特点，我估计此类产品销量将远不如服务器。

本脚本用于实现一个mcp server，功能是生成一个32位的uuid字符串，对外暴露成streamable-http。
请开始你的命令行开发，将代码追加写入本文件下方，不要破坏开发计划。
"""

'''
# 依赖包
mcp[cli]
'''

import uuid
from mcp.server.fastmcp import FastMCP

# Create an MCP server
mcp = FastMCP("UUID32-Generator")


@mcp.tool()
def generate_uuid32() -> str:
    """
    生成一个32位的UUID字符串（不带横杠）
    
    Returns:
        str: 32位UUID字符串，例如 "a1b2c3d4e5f67890abcd1234567890ab"
    """
    return uuid.uuid4().hex


if __name__ == "__main__":
    # mcp.run(transport="stdio")
    mcp.run(transport="streamable-http")
    # mcp.run(transport="sse")
"""
使用方法：
python mcp_server_uuid32.py ，这样就启动了，占用8000端口。

打开Chatbox或者Cherry Studio，图形化页面配置MCP，点击新增，类型选择streamable-http，地址填写 http://127.0.0.1:8000/mcp
点击保存，这样就配置完毕了。
打开uuid32这个工具的开关，在对话框中勾选uuid32，然后向大模型发送提示词“请生成一个32位的UUID。”你就会看到大模型调用了这个工具。

在一些编程环境比如OpenCode或者Cline，可通过JSON配置文件进行配置。
{
    "mcpServers": {
        "uuid32":{
            "name": "uuid32",
            "description": "",
            "baseUrl": "http://127.0.0.1:8000/mcp",
            "command": "",
            "args": [],
            "env": {},
            "isActive": false,
            "type": "streamableHttp",
            "provider": "",
            "providerUrl": "",
            "logoUrl": "",
            "tags": []
        }
    }
}

在AI编程环境中，常用的JSON配置MCP方法如下：
{
	"mcpServers": {
		"sequentialthinking": {
			"command": "npx",
			"args": [
				"-y",
				"@modelcontextprotocol/server-sequential-thinking"
			]
	    },
		"time": {
			"command": "uvx",
			"args": [
				"mcp-server-time"
			],
			"alwaysAllow": [
				"get_current_time"
			],
			"disabled": false
		}
    }
}
"""