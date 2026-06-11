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
# 依赖
pyyaml
requests
mcp
fastapi
uvicorn
'''

import asyncio
import json
import os
import sys
import time
import uuid
import argparse
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
        self.exposure_port = self.exposure_config.get("port", 23333)
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
        
        for server_name, server_tools in tools.items():
            for tool in server_tools:
                tool_name = tool['name']
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
        
        parts.append(f"""你是一个智能Agent助手，拥有以下能力：
1. 可以读写本地文件系统
2. 可以执行命令行命令
3. 可以调用各种工具来完成任务

请根据用户的需求，选择合适的工具来完成任务。""")
        
        mcp_tools = self.get_mcp_tools_for_prompt()
        if mcp_tools:
            parts.append(mcp_tools)
        
        skills_prompt = self.get_skills_for_prompt(query)
        if skills_prompt:
            parts.append(skills_prompt)
        
        return '\n'.join(parts)
    
    async def initialize(self) -> bool:
        """初始化所有组件"""
        print("\n" + "="*60)
        print("Agent客户端初始化")
        print("="*60)
        
        success = True
        
        if not self.test_model_connection():
            success = False
        
        if not await self.init_mcp_clients():
            success = False
        
        if not self.init_skills():
            success = False
        
        print("\n" + "="*60)
        if success:
            print("初始化完成！所有组件就绪。")
        else:
            print("初始化完成，但存在错误。")
        print("="*60)
        
        return success
    
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
            
            if stream:
                return StreamingResponse(
                    self.call_llm(all_messages, stream=True),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache"}
                )
            else:
                return JSONResponse(
                    content={"choices": [{"message": {"content": "non-stream not implemented"}}]}
                )
        
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
    
    async def run(self):
        """运行Agent客户端"""
        if not await self.initialize():
            print("\n初始化失败，退出。")
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
