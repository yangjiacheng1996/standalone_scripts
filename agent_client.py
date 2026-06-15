"""
开发计划：

人类的大脑分为内脑、外脑、小脑。
内脑负责处理多个外脑区域传输过来的信息，并进行决策和控制，运算速度有限（10bit/s）。
外脑则信息收集和压缩，负责感知、记忆、情感等功能，具有高带宽的特性（500MB/s），将外界海量的、不同格式的信息压缩成文字传递给内脑。
小脑负责执行，接受内脑的指令，并将执行结果回传给内脑。

|属性/脑区|内脑|外脑|小脑|
|---|---|---|---|
|生物学速度|10bit/s|500MB/s|500MB/s|
|功能|决策与逻辑|感知与压缩|执行与反馈|
|模型类型|LLM+Prompt MCP|多模态模型（VLM、ASR）+Resource MCP|LLM+Tool MCP|
|输入输出|文字to文字|其他to文字|文字to其他|
|数据流程|感知-思考-执行|定时触发，FIFO|事件驱动|


从上面这个表格可以看出，每一种脑区都是模型+MCP的组合。所以我需要一个客户端工具，它具备调用LLM、VLM的功能，同时可以调用MCP Server和Agent Skills。
为此我已经实现了若干脚本并测试通过：
1. openai_client.py ， 可以调用LLM大语言模型。
2. openai_vlm_client.py，可以调用VLM视觉大模型。
3. agent_client.py，调用Agent Skills。
4. mcp_client.py，调用MCP工具。
5. openai_server_sse.py，可以将字符串伪装成一个LLM大模型，通过SSE流式响应的方式输出，供其他的OpenAI客户端使用。
现在请你阅读这五个脚本，开发一个agent客户端，你可以自由import这五个脚本中的已有函数，这样减小本文件的篇幅。
agent客户端会读取同级目录下的agent_config.json配置文件，获取模型配置、对外暴露的配置、skills配置和MCP服务器配置。这个配置文件我已经写好了，你可以直接使用。
在配置文件中，我规定这个客户端只允许调用一个模型。但可以调用多个skills和MCP server，最后将这个"叠满buff的模型"对外暴露成一个新的模型。整个客户端并不是一个agent，只是agent的一部分。
一个智能体的客户端，其大模型需要具备两个最基本的能力：
1. 读取本地文件的能力。因为智能体读取上下文、记忆、中间文件等都需要文件系统能力。
2. 命令行能力。打开系统的shell，执行命令，命令包括系统命令和本地脚本，得到执行的开始时间、结束时间、状态码、标准输出、标准错误等信息。
我记得Anthropic公司在发布MCP协议的时候给出了一些官方MCP server案例，其中就包括filesystem。我不知道是否还发布了命令行相关MCP Server。
需要将这两个MCP Server信息配置到agent_config.json中。先完成配置修改，再进行开发。
客户端启动时，检查模型连接信息是否可用，扫描所有MCP server和Agent Skills，所有在配置文件中的MCP server必须要可用（不可用你配置它干嘛，干扰智能体？）。
模型已ready，所有MCP Server已ready，所有Agent Skills已ready后，才根据暴露信息启动端口监听请求，提供服务。

现在开始开发，把代码追加写入本文件下方，不要破坏开发计划。
开发完成后，不用测试，我会手动测试。
"""

'''
二次修改建议：
在第一次开发结束后，我进行了超过30次测试和小修小补，包括
1. 启动时三大步骤（大模型、MCP扫描、Skills扫描）中任意失败立刻终止启动，不再运行后续步骤。
2. 初次大模型回答中包含工具调用信息，本脚本却直接将工具调用信息抛给用户，而没有解析工具调用信息并执行tool call。通过在配置文件中设置max_agent_loop参数循环解析大模型回答解决这个问题。
3. 系统提示词调整、报错修理、流式输出修理等多项细节调整。

现在脚本基本可用，但是还有优化空间。我仔细阅读了本脚本的全部代码和相关依赖脚本代码，发现如下优化点：
1. async def chat_completions 这个函数中包含了tool call解析循环，核心逻辑是判断大模型的回答中是否包含工具调用信息。
如果有，就解析工具调用信息，执行工具调用，并将工具调用结果添加到消息列表中，再次调用大模型获取新的回答。agent loop计数+1 ，直到超出max_agent_loop或者没有工具调用信息了，才返回最终回答。
如果没有工具调用信息，则直接流式返回大模型回答。
这个循环可以单独封装成一个函数，命名为 process_agent_loop，这样代码结构更清晰，职责更单一。
本来chat_completions就是一个网络相关的路由函数，结果里面包含了一大坨 “视图函数”的代码，代码不解耦，会变成屎山代码。
2. process_agent_loop，目前尚未封装。但是从功能上看，它和目前非常流行的OpenClaw（小龙虾）智能体的agent loop原理不一样。
小龙虾的agent loop主流程设计原理是这样的：

```mermaid
flowchart TD
    Start([调用方发起请求]) --> Entry1[Gateway 接收消息]
    Entry1 --> Entry2{参数 & 幂等校验}
    Entry2 -->|失败| ReturnErr[返回错误]
    Entry2 -->|通过| ReturnRunId[立即返回 runId<br/>异步标识]
    ReturnRunId --> Prep1[进 Session Lane 串行化]
    Prep1 --> Prep2[初始化 Workspace<br/>加载 Bootstrap 文件]
    Prep2 --> Prep3[获取会话写锁]
    Prep3 --> Prep4[执行 before_agent_start 钩子]
    Prep4 --> Prep5[组装上下文<br/>系统提示→技能→历史→当前消息]

    Prep5 --> Exec1[调用 pi-agent-core]
    Exec1 --> Exec2{模型推理}
    Exec2 --> Stream1[流式推送<br/>思考 / 文本]
    Exec2 --> Tool{需要工具?}
    Tool -->|是| Tool1[执行 before_tool_call 钩子]
    Tool1 --> Tool2[调用工具 / Skill]
    Tool2 --> Tool3[执行 after_tool_call 钩子]
    Tool3 --> Tool4[结果清洗 & 追加到 jsonl]
    Tool4 --> Exec2
    Tool -->|否| Done1[本轮推理完成]

    Done1 --> Check{是否继续<br/>下一轮?}
    Check -->|是| Exec2
    Check -->|否| Comp1[Gateway 结果塑形<br/>压缩 / 过滤 / 兜底]

    Comp1 --> Comp2[调用方 agent.wait<br/>拉取最终状态]
    Comp2 --> Comp3[持久化 session 元数据]
    Comp3 --> End([结束])

    Exec2 -.异常.-> Fail1{异常类型?}
    Fail1 -->|上下文溢出| Fail2[自动 compact 重试]
    Fail1 -->|限流 / 鉴权失败| Fail3[轮换 Auth Profile 重试]
    Fail1 -->|不支持 reasoning| Fail4[降级思考级别重试]
    Fail1 -->|调用方取消| Fail5[优雅终止]
    Fail2 --> Exec2
    Fail3 --> Exec2
    Fail4 --> Exec2

    style ReturnRunId fill:#ffe4b5
    style Stream1 fill:#e0f7fa
    style Comp1 fill:#f3e5f5
    style End fill:#c8e6c9
```
OpenClaw小龙虾设计了一些状态钩子，因为OpenClaw拥有一个消息网关来控制会话、工具、渠道等信息。我们这个脚本只是一个客户端，所以可以不用钩子。
是否采用钩子，请你自行判断。
但是最重要的是，OpenClaw不是以“没有工具调用”作为Agent Loop的结束标志的。如果本轮次没有工具调用，大模型应该在回答中包含一个明确的结束标志，告诉Agent Loop它已经完成了所有的思考和工具调用，不需要继续循环了。
这个标志可以是字符串，比如</agent_loop_finish>，也可以是一个特殊的JSON字段，比如{"agent_loop_finish": true}，总之要有一个明确的标志用于结束Agent Loop。
如果没有检测到Agent Loop结束标志，继续执行Agent Loop。注意：只有当Agent Loop中某轮次的大模型回答中没有工具调用信息时，才检测Agent Loop结束标志。
结束标志需要在系统提示词中明确告诉大模型，必须在完成所有思考和工具调用后，在回答中包含这个结束标志，否则Agent Loop将无法正确结束，可能会进入死循环.
自行设计系统提示词模板。
现在实现我的以上需求。


'''

"""
# 依赖
pyyaml
requests
mcp
fastapi
uvicorn
"""

import asyncio
import json
import os
import sys
import time
import uuid
import argparse
from json import JSONDecodeError
from pathlib import Path
from typing import Optional, Any, Generator

import yaml
import requests
import uvicorn
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# 导入已有的客户端模块
from openai_client import normalize_url, get_chat_completions_url, test_model as test_llm_model
from mcp_client import MCPClient
from agent_skills_client import (
    ProgressiveDisclosureEngine,
    SkillProperties,
    to_prompt as skills_to_prompt,
    DisclosureLevel
)


# ============================================================================
# 配置加载
# ============================================================================

CONFIG_FILE = "agent_config.json"


def load_config(config_path: str = CONFIG_FILE) -> dict:
    """加载配置文件"""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


# ============================================================================
# Agent客户端类
# ============================================================================

class AgentClient:
    """
    Agent客户端 - 整合LLM、MCP Servers和Agent Skills的客户端
    
    功能：
    1. 连接大模型
    2. 连接多个MCP Server
    3. 扫描和加载Agent Skills
    4. 对外提供OpenAI兼容的SSE API
    """
    
    def __init__(self, config: dict):
        self.config = config
        self.model_config = config.get("model", {})
        self.exposure_config = config.get("exposure", {})
        self.skills_config = config.get("skills", {})
        self.mcp_config = config.get("mcpServers", {})
        
        # 模型信息
        self.model_url = self.model_config.get("url", "")
        self.model_key = self.model_config.get("key", "")
        self.model_name = self.model_config.get("model_name", "")
        self.context_length = self.model_config.get("context_length", 200000)
        
        # 暴露信息
        self.exposure_port = self.exposure_config.get("port", 20001)
        self.exposure_key = self.exposure_config.get("key", "")
        self.exposure_model_name = self.exposure_config.get("model_name", "agent")
        
        # Skills根目录
        self.skills_root = self.skills_config.get("root_dir", "")
        
        # MCP客户端
        self.mcp_client: Optional[MCPClient] = None
        
        # Skills引擎
        self.skills_engine: Optional[ProgressiveDisclosureEngine] = None
        self.available_skills: dict[str, SkillProperties] = {}
        
        # 状态标志
        self.model_ready = False
        self.mcp_ready = False
        self.skills_ready = False
    
    def test_model_connection(self) -> bool:
        """测试模型连接是否可用"""
        print(f"\n正在测试模型连接: {self.model_name}")
        print(f"  URL: {self.model_url}")
        
        try:
            normalized_url = normalize_url(self.model_url)
            api_url = get_chat_completions_url(normalized_url)
            success = test_llm_model(api_url, self.model_key, self.model_name)
            
            if success:
                self.model_ready = True
                print(f"[OK] 模型 {self.model_name} 连接成功")
            else:
                print(f"[X] 模型 {self.model_name} 连接失败")
            
            return success
        except Exception as e:
            print(f"[X] 模型连接测试异常: {e}")
            return False
    
    def call_llm(self, messages: list, stream: bool = True):
        """调用大模型"""
        from openai_client import normalize_url, get_chat_completions_url
        
        normalized_url = normalize_url(self.model_url)
        api_url = get_chat_completions_url(normalized_url)
        
        if not stream:
            from openai_client import output_non_sse
            return output_non_sse(api_url, self.model_key, self.model_name, messages)
        
        def sse_generator():
            """将API返回的HTTP分块流重新格式化成SSE格式"""
            import requests
            import json
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.model_key}"
            }
            
            payload = {
                "model": self.model_name,
                "messages": messages,
                "stream": True
            }
            
            response = requests.post(api_url, headers=headers, json=payload, stream=True, timeout=120)
            response.raise_for_status()
            
            # 使用 iter_content 来获取原始数据块，然后重新组装成SSE格式
            buffer = b""
            for chunk in response.iter_content(chunk_size=None):
                if chunk:
                    buffer += chunk
                    # 处理缓冲区，寻找完整的SSE消息
                    while b'\n\n' in buffer:
                        message, buffer = buffer.split(b'\n\n', 1)
                        message = message.strip()
                        if message:
                            # 检查是否是 data: 开头
                            if message.startswith(b'data: '):
                                decoded = message.decode('utf-8')
                                yield decoded + '\n\n'
                            elif message == b'data: [DONE]':
                                yield 'data: [DONE]\n\n'
            
            # 处理缓冲区中剩余的数据
            if buffer.strip():
                message = buffer.strip()
                if message.startswith(b'data: '):
                    decoded = message.decode('utf-8')
                    yield decoded + '\n\n'
                elif message == b'data: [DONE]':
                    yield 'data: [DONE]\n\n'
        
        return sse_generator()
    
    async def init_mcp_clients(self) -> bool:
        """初始化MCP客户端连接"""
        print("\n正在初始化MCP客户端...")
        
        try:
            temp_config = {
                "mcpServers": {}
            }
            
            for name, server_config in self.mcp_config.items():
                if server_config.get("isActive", False):
                    temp_config["mcpServers"][name] = server_config
            
            if not temp_config["mcpServers"]:
                print("  没有需要连接的MCP服务器（全部isActive=false）")
                self.mcp_ready = True
                return True
            
            temp_config_path = "agent_mcp_temp.json"
            with open(temp_config_path, 'w', encoding='utf-8') as f:
                json.dump(temp_config, f, ensure_ascii=False, indent=4)
            
            try:
                self.mcp_client = MCPClient(temp_config_path)
                results = await self.mcp_client.connect_all()
                
                all_success = all(results.values())
                
                if all_success:
                    self.mcp_ready = True
                    print(f"[OK] 所有MCP服务器连接成功 ({len(results)}个)")
                    tools = self.mcp_client.list_tools()
                    total_tools = sum(len(t) for t in tools.values())
                    print(f"  总共 {total_tools} 个工具可用")
                else:
                    failed = [name for name, success in results.items() if not success]
                    print(f"[X] 以下MCP服务器连接失败: {failed}")
                
                return all_success
            finally:
                if os.path.exists(temp_config_path):
                    os.remove(temp_config_path)
                    
        except Exception as e:
            print(f"[X] MCP客户端初始化异常: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def get_mcp_tools_for_prompt(self) -> str:
        """获取MCP工具列表，用于构建系统提示词"""
        if not self.mcp_client or not self.mcp_ready:
            return ""
        
        tools = self.mcp_client.list_tools()
        
        if not tools:
            return ""
        
        lines = ["\n\n<available_tools>"]
        
        print(f"[DEBUG] get_mcp_tools_for_prompt: servers={list(tools.keys())}", flush=True)
        for server_name, server_tools in tools.items():
            print(f"[DEBUG]   server={server_name}, tools_count={len(server_tools)}", flush=True)
            for tool in server_tools:
                tool_name = tool['name']
                print(f"[DEBUG]     tool_name={tool_name}", flush=True)
                tool_desc = tool.get('description', '')
                lines.append(f'<tool name="{tool_name}">')
                lines.append(f"<description>{tool_desc}</description>")
                lines.append(f"<server>{server_name}</server>")
                
                input_schema = tool.get('inputSchema', {})
                if isinstance(input_schema, dict):
                    props = input_schema.get('properties', {})
                    if props:
                        lines.append("<parameters>")
                        for param_name, param_info in props.items():
                            param_type = param_info.get('type', 'string')
                            param_desc = param_info.get('description', '')
                            required = param_name in input_schema.get('required', [])
                            req_str = "true" if required else "false"
                            lines.append(f'<parameter name="{param_name}" type="{param_type}" required="{req_str}">{param_desc}</parameter>')
                        lines.append("</parameters>")
                lines.append("</tool>")
        
        lines.append("</available_tools>")
        return '\n'.join(lines)
    
    async def call_mcp_tool(self, server_name: str, tool_name: str, arguments: dict) -> dict:
        """调用MCP工具"""
        if not self.mcp_client or not self.mcp_ready:
            return {"error": "MCP client not ready"}
        
        return await self.mcp_client.call_tool(server_name, tool_name, arguments)
    
    def init_skills(self) -> bool:
        """初始化Skills引擎"""
        print("\n正在扫描Agent Skills...")
        
        if not self.skills_root or not os.path.exists(self.skills_root):
            print("  Skills根目录不存在，跳过")
            self.skills_ready = True
            return True
        
        try:
            self.skills_engine = ProgressiveDisclosureEngine(self.skills_root)
            self.available_skills = self.skills_engine.scan_skills()
            
            if self.available_skills:
                print(f"[OK] 已加载 {len(self.available_skills)} 个Agent Skills")
                for name in list(self.available_skills.keys())[:5]:
                    print(f"  - {name}")
                if len(self.available_skills) > 5:
                    print(f"  ... 等共 {len(self.available_skills)} 个")
            else:
                print("  没有找到任何Skills")
            
            self.skills_ready = True
            return True
            
        except Exception as e:
            print(f"[X] Skills初始化异常: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def get_skills_for_prompt(self, query: str = "", level: DisclosureLevel = DisclosureLevel.L1_METADATA) -> str:
        """获取Skills提示词"""
        if not self.skills_engine or not self.skills_ready:
            return ""
        
        if not self.available_skills:
            return ""
        
        # 使用 ProgressiveDisclosureEngine 的 to_prompt 方法
        skill_paths = list(self.available_skills.keys())
        return skills_to_prompt([self.skills_engine.skills_root / name for name in skill_paths])
    
    def build_system_prompt(self, query: str = "") -> str:
        """构建系统提示词"""
        parts = []
        
        parts.append("""你是一个智能体Agent助手，可以调用工具来完成任务。

可用工具分为两类：

## 1. MCP类 (Model Context Protocol)  
MCP服务器提供的标准化工具，具有统一的接口和结构化参数。已为你提供了若干MCP server，每个server包含若干工具。MCP工具列表见下方。
                     
## 2. Agent Skills类  
Agent技能，提供更灵活的功能和更丰富的描述。Agent Skills技能列表见下方。

重要！关于Agent Loop 结束标志：</agent_loop_finish>  
当你完成所有思考和必要的工具调用后，认为已经完成用户提出任务，或已经为用户提供了完整回答时，必须在回答的末尾添加以下结束标志：

</agent_loop_finish>

因为大模型只能进行一次问答QA，所以你作为一个智能体，我在设计你时，用一个叫Agent Loop的循环程序反复催动你来多轮次思考、执行工具、得出回答。
所以</agent_loop_finish>这个标志告诉Agent Loop你已经完成了所有工作，不再需要继续循环调用工具。
**重要**：如果你没有添加这个标志，你将陷入无休止的工具调用死循环中，造成庞大的资源浪费，用户也无法获得你的最终回答。
只有在确认已经完成所有任务后再添加此标志。
                     
""")
        
        mcp_tools = self.get_mcp_tools_for_prompt()
        if mcp_tools:
            parts.append("## 以下是 MCP 工具\n")
            parts.append(mcp_tools)
        
        skills_prompt = self.get_skills_for_prompt(query)
        if skills_prompt:
            parts.append("\n## 以下是 Agent Skills\n")
            parts.append(skills_prompt)
        
        return '\n'.join(parts)
    
    async def initialize(self) -> bool:
        """初始化所有组件"""
        print("\n" + "="*60)
        print("Agent客户端初始化")
        print("="*60)
        
        # 1. 测试模型连接 - 必须成功，否则直接退出
        if not self.test_model_connection():
            error_msg = f"[FATAL] 模型 {self.model_name} 连接失败，无法继续启动。"
            print(f"\n{error_msg}")
            raise RuntimeError(error_msg)
        
        # 2. 初始化MCP客户端 - 必须全部成功，否则直接退出
        if not await self.init_mcp_clients():
            error_msg = "[FATAL] MCP服务器连接失败，无法继续启动。"
            print(f"\n{error_msg}")
            raise RuntimeError(error_msg)
        
        # 3. 扫描Agent Skills
        if not self.init_skills():
            error_msg = "[FATAL] Agent Skills扫描失败，无法继续启动。"
            print(f"\n{error_msg}")
            raise RuntimeError(error_msg)
        
        print("\n" + "="*60)
        print("初始化完成！所有组件就绪。")
        print("="*60)
        
        return True
    
    async def close(self) -> None:
        """关闭所有连接并清理资源"""
        print("\n正在关闭Agent客户端...")
        
        # 关闭 MCP 客户端
        if self.mcp_client:
            try:
                await self.mcp_client.close()
                print("[OK] MCP客户端已关闭")
            except Exception as e:
                print(f"[X] 关闭MCP客户端时出错: {e}")
        
        self.mcp_ready = False
        self.model_ready = False
        self.skills_ready = False
        print("[OK] Agent客户端已关闭")
    
    def create_app(self) -> FastAPI:
        """创建FastAPI应用"""
        app = FastAPI(title="Agent Client API")
        
        # 添加CORS中间件
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        @app.get("/v1/models")
        async def list_models():
            """列出可用模型"""
            return {
                "object": "list",
                "data": [{
                    "id": self.exposure_model_name,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "agent",
                    "context_window": self.context_length,
                    "capabilities": ["streaming", "tools", "vision"]
                }]
            }
        
        @app.post("/v1/chat/completions")
        async def chat_completions(
            request: dict,
            authorization: Optional[str] = Header(None)
        ):
            """处理聊天完成请求"""
            # 验证API Key
            if authorization:
                token = authorization.replace("Bearer ", "")
                if token != self.exposure_key:
                    raise HTTPException(status_code=401, detail="Invalid API key")
            
            # 验证model参数
            requested_model = request.get("model", "")
            if requested_model and requested_model != self.exposure_model_name:
                raise HTTPException(
                    status_code=404,
                    detail=f"Model '{requested_model}' not found. Available model: {self.exposure_model_name}"
                )
            
            messages = request.get("messages", [])
            stream = request.get("stream", True)
            
            if not messages:
                raise HTTPException(status_code=400, detail="No messages provided")
            
            system_msg = {
                "role": "system",
                "content": self.build_system_prompt(messages[-1].get("content", "") if messages else "")
            }
            
            all_messages = [system_msg] + messages
            
            # 使用 process_agent_loop 处理工具调用循环
            max_agent_loop = self.config.get("client_setting", {}).get("max_agent_loop", 10)
            final_response, was_cut_off, loop_count = await self.process_agent_loop(all_messages, max_agent_loop)
            
            if was_cut_off:
                # 达到最大循环次数，返回错误
                return JSONResponse(
                    status_code=500,
                    content={"error": f"Maximum tool call iterations ({max_agent_loop}) reached"}
                )
            
            print(f"[DEBUG] Returning response, stream={stream}, text_len={len(final_response) if final_response else 0}", flush=True)
            
            if stream:
                # 构建SSE格式的响应
                def generate():
                    data = {
                        "choices": [{
                            "index": 0,
                            "delta": {"content": final_response},
                            "finish_reason": "stop"
                        }]
                    }
                    content = f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                    print(f"[DEBUG] SSE content: {content[:200]}...", flush=True)
                    yield content
                    yield "data: [DONE]\n\n"
                return StreamingResponse(
                    generate(),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache"}
                )
            else:
                return JSONResponse(content={
                    "choices": [{"message": {"content": final_response}}]
                })
        
        @app.get("/health")
        async def health():
            """健康检查"""
            return {
                "status": "healthy" if (self.model_ready and self.mcp_ready and self.skills_ready) else "degraded",
                "model_ready": self.model_ready,
                "mcp_ready": self.mcp_ready,
                "skills_ready": self.skills_ready
            }
        
        return app
    
    def _call_llm_with_tools(self, messages: list) -> tuple[str, bool, list]:
        """调用LLM并检查是否有工具调用
        Returns: (response_text, has_tool_calls, tool_calls_data)
        """
        from openai_client import normalize_url, get_chat_completions_url
        
        normalized_url = normalize_url(self.model_url)
        api_url = get_chat_completions_url(normalized_url)
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.model_key}"
        }
        
        # 构建工具列表
        tools = self._build_tools_list()
        print(f"[DEBUG] Calling LLM with {len(tools)} tools", flush=True)
        
        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,  # 非流式以便解析工具调用
            "tools": tools
        }
        
        try:
            response = requests.post(api_url, headers=headers, json=payload, timeout=120)
            response.raise_for_status()
            result = response.json()
            
            if "choices" not in result or len(result["choices"]) == 0:
                return "", False, []
            
            choice = result["choices"][0]
            message = choice.get("message", {})
            
            # 检查是否有工具调用
            tool_calls = message.get("tool_calls", [])
            if tool_calls:
                print(f"[DEBUG] tool_calls detected: {len(tool_calls)} calls", flush=True)
                for tc in tool_calls:
                    print(f"[DEBUG]   tool_call: {tc}", flush=True)
                return message.get("content", ""), True, tool_calls
            
            content = message.get("content", "")
            print(f"[DEBUG] No tool_calls in response, content_len={len(content) if content else 0}", flush=True)
            print(f"[DEBUG] Full response: {result}", flush=True)
            return content, False, []
            
        except Exception as e:
            print(f"[DEBUG] Exception in _call_llm_with_tools: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return f"Error calling LLM: {str(e)}", False, []
    
    def _build_tools_list(self) -> list:
        """构建OpenAI格式的工具列表"""
        tools = []
        
        if self.mcp_client and self.mcp_ready:
            for server_name, server_tools in self.mcp_client.list_tools().items():
                for tool in server_tools:
                    tool_name = tool['name']
                    tool_desc = tool.get('description', '')
                    input_schema = tool.get('inputSchema', {})
                    
                    # 构建OpenAI格式的工具定义
                    openai_tool = {
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "description": tool_desc,
                            "parameters": input_schema if isinstance(input_schema, dict) else {"type": "object", "properties": {}}
                        }
                    }
                    tools.append(openai_tool)
        
        return tools
    
    async def _handle_tool_call(self, tool_name: str, tool_args: dict) -> str:
        """处理工具调用"""
        try:
            print(f"[DEBUG] _handle_tool_call: tool_name={tool_name}", flush=True)
            # 检查是否是MCP工具调用
            if "." in tool_name:
                parts = tool_name.split(".", 1)
                server_name = parts[0]
                mcp_tool_name = parts[1]
                print(f"[DEBUG]   Parsed as server={server_name}, tool={mcp_tool_name}", flush=True)
                
                # 调用MCP工具
                result = await self.call_mcp_tool(server_name, mcp_tool_name, tool_args)
                # result 可能是 TextContent 对象列表，需要转换为可序列化格式
                return self._serialize_tool_result(result)
            else:
                # 尝试从所有MCP服务器中查找工具
                print(f"[DEBUG]   No '.' in tool_name, searching all servers...", flush=True)
                if self.mcp_client and self.mcp_ready:
                    for server_name, server_tools in self.mcp_client.list_tools().items():
                        for tool in server_tools:
                            if tool["name"] == tool_name:
                                print(f"[DEBUG]   Found in server={server_name}", flush=True)
                                result = await self.call_mcp_tool(server_name, tool_name, tool_args)
                                return self._serialize_tool_result(result)
                
                print(f"[DEBUG]   Tool '{tool_name}' not found in any server", flush=True)
                return json.dumps({"error": f"Tool '{tool_name}' not found"}, ensure_ascii=False)
        except Exception as e:
            print(f"[DEBUG] Exception in _handle_tool_call: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return json.dumps({"error": str(e)}, ensure_ascii=False)
    
    def _serialize_tool_result(self, result: Any) -> str:
        """序列化工具调用结果，处理 TextContent 等特殊类型"""
        # 如果已经是字符串，直接返回
        if isinstance(result, str):
            return result
        
        try:
            # 尝试直接 JSON 序列化
            return json.dumps(result, ensure_ascii=False)
        except TypeError:
            # 如果失败，可能是 TextContent 对象列表
            if isinstance(result, list):
                items = []
                for item in result:
                    if hasattr(item, 'text'):
                        items.append(item.text)
                    elif hasattr(item, 'data'):
                        items.append(item.data)
                    else:
                        items.append(str(item))
                return json.dumps({"content": items}, ensure_ascii=False)
            else:
                return json.dumps({"content": str(result)}, ensure_ascii=False)
    
    async def process_agent_loop(
        self,
        messages: list,
        max_agent_loop: int = 10
    ) -> tuple[str, bool, int]:
        """
        处理 Agent Loop 循环。
        
        核心逻辑：
        1. 调用大模型获取回答
        2. 检查是否有工具调用
        3. 如果有工具调用，执行工具并将结果添加到消息列表，循环
        4. 如果没有工具调用，检查是否包含 <agent_loop_finish> 结束标志
        5. 如果有结束标志，返回最终回答；否则继续循环
        
        Args:
            messages: 消息列表（包含系统消息和用户消息）
            max_agent_loop: 最大循环次数
            
        Returns:
            tuple: (final_response, was_cut_off, loop_count)
            - final_response: 最终回答文本
            - was_cut_off: 是否因为达到最大循环次数而被截断
            - loop_count: 实际循环次数
        """
        AGENT_LOOP_FINISH_TAG = "</agent_loop_finish>"
        
        for loop_count in range(1, max_agent_loop + 1):
            print(f"[DEBUG] Agent Loop 第 {loop_count} 轮", flush=True)
            
            # 调用LLM获取响应
            response_text, has_tool_calls, tool_calls_data = self._call_llm_with_tools(messages)
            
            if has_tool_calls:
                # 有工具调用，处理工具调用
                print(f"[DEBUG] 检测到工具调用: {len(tool_calls_data)} 个", flush=True)
                
                for tool_call in tool_calls_data:
                    tool_call_id = tool_call.get("id", "")
                    tool_name = tool_call.get("name", tool_call.get("function", {}).get("name", ""))
                    tool_args = tool_call.get("arguments", tool_call.get("function", {}).get("arguments", "{}"))
                    
                    print(f"[DEBUG] Processing tool_call: name={tool_name}, id={tool_call_id}", flush=True)
                    
                    # 解析参数
                    if isinstance(tool_args, str):
                        try:
                            tool_args = json.loads(tool_args)
                        except JSONDecodeError:
                            tool_args = {}
                    
                    # 添加助手消息（包含工具调用）
                    messages.append({
                        "role": "assistant",
                        "tool_calls": [tool_call]
                    })
                    
                    # 调用工具
                    tool_result = await self._handle_tool_call(tool_name, tool_args)
                    print(f"[DEBUG] Tool result: {tool_result[:200]}...", flush=True)
                    
                    # 添加工具结果消息
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": tool_result
                    })
                
                # 继续下一轮循环
                continue
            
            # 没有工具调用，检查是否包含结束标志
            print(f"[DEBUG] 本轮无工具调用，检查结束标志，response_len={len(response_text) if response_text else 0}", flush=True)
            
            if AGENT_LOOP_FINISH_TAG in response_text:
                # 移除结束标志后返回
                final_response = response_text.replace(AGENT_LOOP_FINISH_TAG, "").strip()
                print(f"[DEBUG] 检测到结束标志 <agent_loop_finish>，Agent Loop 正常结束", flush=True)
                return final_response, False, loop_count
            
            # 没有结束标志，说明模型可能还在思考或没有正确添加结束标志
            # 记录警告但仍然返回（避免死循环）
            print(f"[WARN] 本轮无工具调用但未检测到结束标志，可能导致循环继续", flush=True)
            return response_text, False, loop_count
        
        # 达到最大循环次数
        print(f"[WARN] 达到最大Agent Loop次数 ({max_agent_loop})，强制结束", flush=True)
        return f"[Agent Loop 已达到最大循环次数 {max_agent_loop}]", True, max_agent_loop
    
    async def run(self):
        """运行Agent客户端"""
        try:
            await self.initialize()
        except RuntimeError as e:
            print(f"\n启动失败: {e}")
            await self.close()
            return False
        
        app = self.create_app()
        
        print(f"\n启动服务: http://0.0.0.0:{self.exposure_port}")
        print(f"暴露模型: {self.exposure_model_name}")
        print(f"API Key: {self.exposure_key}")
        print("\n按 Ctrl+C 停止服务\n")
        
        try:
            config = uvicorn.Config(
                app,
                host="0.0.0.0",
                port=self.exposure_port,
                log_level="info"
            )
            server = uvicorn.Server(config)
            await server.serve()
        finally:
            await self.close()
        
        return True


# ============================================================================
# 主函数
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Agent客户端")
    parser.add_argument("--config", "-c", default=CONFIG_FILE, help="配置文件路径")
    parser.add_argument("--port", "-p", type=int, help="覆盖配置文件中的端口")
    
    args = parser.parse_args()
    
    try:
        config = load_config(args.config)
        
        if args.port:
            config["exposure"]["port"] = args.port
        
        client = AgentClient(config)
        asyncio.run(client.run())
    except KeyboardInterrupt:
        print("\n\n服务已停止")
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
