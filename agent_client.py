from __future__ import annotations

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
本来chat_completions就是一个网络相关的路由函数，结果里面包含了一大坨 "视图函数"的代码，代码不解耦，会变成屎山代码。
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
但是最重要的是，OpenClaw不是以"没有工具调用"作为Agent Loop的结束标志的。如果本轮次没有工具调用，大模型应该在回答中包含一个明确的结束标志，告诉Agent Loop它已经完成了所有的思考和工具调用，不需要继续循环了。
这个标志可以是字符串，比如</agent_loop_finish>，也可以是一个特殊的JSON字段，比如{"agent_loop_finish": true}，总之要有一个明确的标志用于结束Agent Loop。
如果没有检测到Agent Loop结束标志，继续执行Agent Loop。注意：只有当Agent Loop中某轮次的大模型回答中没有工具调用信息时，才检测Agent Loop结束标志。
结束标志需要在系统提示词中明确告诉大模型，必须在完成所有思考和工具调用后，在回答中包含这个结束标志，否则Agent Loop将无法正确结束，可能会进入死循环.
自行设计系统提示词模板。
现在实现我的以上需求。


'''

"""
第三次修改建议：
上一次（第二次）修改建议是让这个脚本变成一个类似OpenClaw小龙虾一样的智能体，具备完整的Agent Loop能力。
1. 我发现你把大模型回答中的tool_call字段解析成工具调用schema，然后加载到openai的请求里。实际上这是OpenAI的function calling能力。
我并不是反对这样做，事实上很多智能体客户端都是这么干的。
但是这样做需要模型厂商原生支持function calling协议(vllm启动模型时开启function calling功能)。
如果我在家里用Nvidia DGX spark搭建私有大模型，则可能不适用。
我已用MiniMax Agent联网调研了多种客户端的"大模型与MCP Client交互方式"，做成了报告，放到了agent_client_format_research.md中。
请你阅读这篇报告的全文，就知道目前这个脚本采用流派B。我想你将这个脚本改成像Cline这样的流派A。
因为流派B并不会节约Token和上下文空间，是一种垃圾做法，流派A更通用。
2. 我发现这个客户端只能读取Agent Skills的L1级别信息，并且误以为L1信息就是这个技能的全部指令。
因为Agent Skills是渐进式披露的，需要让大模型具备查看L2和L3信息的能力。
所以请你阅读agent_skills_client.py，让本脚本中的大模型具备查看某个技能L2和L3信息的能力。
大模型进一步披露Skill技能的信息，这个行为本质上也是调用工具。
所以需要你开发一个披露工具，你需要在系统提示词中添加一段话，让大模型发送特别的xml格式的指令，
然后根据指令中的agent_skill_name和信息登记，将大模型想要的信息披露出来，而不是使用MCP的filesystem。
很多agent client不具备MCP功能，只有调用Agent skills的功能，用filesystem来读取skills，是一个非常愚蠢的做法。

"""

"""
# 依赖
pyyaml
requests
mcp
fastapi
uvicorn
"""



import asyncio
import argparse
import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from collections import deque
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Generator, Optional

import requests
import uvicorn
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from requests import RequestException
from requests.exceptions import Timeout as RequestsTimeout

# 导入已有的客户端模块
from openai_client import (
    get_chat_completions_url,
    normalize_url,
    test_model as test_llm_model,
)
from mcp_client import MCPClient
from agent_skills_client import (
    DisclosureLevel,
    ProgressiveDisclosureEngine,
    SkillProperties,
    to_prompt as skills_to_prompt,
)


# ============================================================================
# 通用工具函数
# ============================================================================

# 调试日志配置
DEBUG_LOG_FILE = "agent_client_debug.log"

# 业务模块 logger（统一格式，避免与 print 混用）
logger = logging.getLogger("agent_client")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    _stream_handler = logging.StreamHandler(stream=sys.stdout)
    _stream_handler.setFormatter(
        logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", "%H:%M:%S")
    )
    logger.addHandler(_stream_handler)
    # 防止日志被 uvicorn 重复打印
    logger.propagate = False


# 进程级锁，避免并发请求把日志写串行
_DEBUG_LOG_LOCK = threading.Lock()


def log_to_file(title: str, content: str, file_path: str = DEBUG_LOG_FILE) -> None:
    """
    将调试内容写入本地日志文件。

    并发安全：使用进程级 threading.Lock 串行化写入，避免多请求下日志交错。
    异常吞咽：日志写入失败绝不应阻塞主流程，仅记录一条 warning。

    Args:
        title: 日志条目的标题，用于区分不同的日志类型
        content: 日志内容
        file_path: 日志文件路径
    """
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    try:
        with _DEBUG_LOG_LOCK:
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(f"\n{'#'*80}\n")
                f.write(f"# [{timestamp}] {title}\n")
                f.write(f"{'#'*80}\n\n")
                f.write(content if isinstance(content, str) else str(content))
                f.write("\n")
    except OSError as e:
        # 写调试日志失败不应让请求整体 500
        logger.warning("log_to_file 写入失败 (%s): %s", file_path, e)


def clear_debug_log(file_path: str = DEBUG_LOG_FILE) -> None:
    """清空调试日志文件。文件被占用或不存在时静默失败。"""
    try:
        with _DEBUG_LOG_LOCK:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("")
    except OSError as e:
        logger.warning("clear_debug_log 失败 (%s): %s", file_path, e)


# ============================================================================
# Agent Loop 防护与跟踪器（P0 阶段新增）
# ============================================================================

class MistakeTracker:
    """
    连续失败计数器 (P0 - F类问题防护)

    设计目的：
    - 当模型连续多轮调用工具都失败时，强制结束循环，避免无限空转浪费资源
    - 只要出现一次成功调用就重置计数器，避免误伤正常的探索过程

    触发逻辑：
    - failed_count > 0 且 success_count == 0  -> 连续失败 +1
    - success_count > 0                       -> 连续失败清零
    """

    def __init__(self, max_consecutive: int = 6) -> None:
        self.consecutive_failures = 0
        self.max_consecutive = max_consecutive

    def record_turn(self, failed_count: int, success_count: int) -> None:
        if failed_count > 0 and success_count == 0:
            self.consecutive_failures += 1
        elif success_count > 0:
            self.consecutive_failures = 0  # 成功轮自动 reset

    def is_limit_reached(self) -> bool:
        return self.consecutive_failures >= self.max_consecutive


class LoopDetectionTracker:
    """
    重复调用检测器 (P0 - F类问题防护)

    设计目的：
    - 检测模型是否陷入"反复调用同一个工具、传同样参数"的死循环
    - 采用软硬双阈值：
        * soft: 软提醒，注入一条 system 消息告诉模型"你在重复同样的调用"
        * hard: 硬停止，直接 finishRun 避免资源耗尽

    实现细节：
    - 使用 deque(maxlen=20) 维护最近的调用签名
    - 签名 = (tool_name, JSON序列化后的参数)，按 key 排序保证稳定
    - 统计最近连续相同签名的次数 (从尾部向前扫描)
    """

    def __init__(self, soft: int = 3, hard: int = 5) -> None:
        self.recent_signatures: deque = deque(maxlen=20)
        self.soft_threshold = soft
        self.hard_threshold = hard

    def check(self, tool_name: str, tool_args: Optional[dict]) -> tuple:
        """
        返回 (状态, 连续相同次数)
        状态: 'ok' | 'soft' | 'hard'
        """
        sig = (
            tool_name,
            json.dumps(tool_args or {}, sort_keys=True, ensure_ascii=False),
        )
        self.recent_signatures.append(sig)
        # 数最近连续相同签名次数
        count = 0
        for s in reversed(self.recent_signatures):
            if s == sig:
                count += 1
            else:
                break
        if count >= self.hard_threshold:
            return "hard", count
        if count >= self.soft_threshold:
            return "soft", count
        return "ok", count


# ============================================================================
# XML工具调用解析（流派A：Cline风格）
# ============================================================================

# 安全截断长度，避免把模型原始输出全部打印到日志/屏幕
_LOG_PREVIEW_CHARS = 200


def _try_parse_arguments(arguments_str: str, server_name: str, tool_name: str) -> dict:
    """
    宽容地解析工具参数字符串 (修复 4: 空 arguments 容错)

    解析策略（依次尝试，失败则降级）：
    1. 空字符串直接返回 {}
    2. 严格 json.loads
    3. 修复尾部逗号后 json.loads
    4. 替换单引号为双引号后 json.loads
    5. 仍失败则返回 __parse_error__ 标记字典，让上层把错误反馈给 LLM
    """
    # 空 arguments 视为 {}，不再抛错
    if not arguments_str or not arguments_str.strip():
        logger.debug(
            "_try_parse_arguments: 空 arguments 视为 {} (server=%s, tool=%s)",
            server_name, tool_name,
        )
        return {}

    # 1. 严格 JSON 解析
    try:
        return json.loads(arguments_str)
    except json.JSONDecodeError:
        pass

    # 2. 修复常见错误：尾部逗号 (,]/,} -> ]/})
    fixed = re.sub(r",(\s*[}\]])", r"\1", arguments_str)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # 3. 替换单引号为双引号（仅在不含双引号时尝试，避免误伤字符串内容）
    if "'" in arguments_str and '"' not in arguments_str:
        single_quoted = arguments_str.replace("'", '"')
        single_quoted = re.sub(r",(\s*[}\]])", r"\1", single_quoted)
        try:
            return json.loads(single_quoted)
        except json.JSONDecodeError:
            pass

    # 4. 仍失败：返回带特殊标记的字典，让 _handle_tool_call 反馈给 LLM
    #    截断原始输入，避免敏感内容全量打到日志里
    preview = arguments_str[:_LOG_PREVIEW_CHARS]
    logger.warning(
        "_try_parse_arguments: JSON解析失败 for %s.%s: arguments_str='%s%s'",
        server_name, tool_name, preview,
        "..." if len(arguments_str) > _LOG_PREVIEW_CHARS else "",
    )
    return {"__parse_error__": arguments_str, "__error__": "无法解析为有效JSON"}


def parse_xml_tool_calls(text: str) -> list:
    """
    解析文本中的XML工具调用标签。

    支持两种格式：
    1. <use_mcp_tool> - MCP工具调用
    2. <skill_disclosure> - Skill披露请求

    Returns:
        list of dict, each dict contains:
        - tool_type: "mcp" or "skill_disclosure"
        - server_name: for MCP tools
        - tool_name: for MCP tools or skill_name for skill disclosure
        - arguments: dict of arguments
        - level: for skill disclosure (L2 or L3)
    """
    if not isinstance(text, str):
        return []

    results = []

    # Parse <use_mcp_tool> blocks
    # 使用更严格的正则表达式，只匹配正确格式的工具调用
    use_mcp_pattern = re.compile(
        r'<use_mcp_tool>\s*'
        r'<server_name>(.*?)</server_name>\s*'
        r'<tool_name>(.*?)</tool_name>\s*'
        r'<arguments>(.*?)</arguments>\s*'
        r'</use_mcp_tool>',
        re.DOTALL,
    )

    for match in use_mcp_pattern.finditer(text):
        server_name = match.group(1).strip()
        tool_name = match.group(2).strip()
        arguments_str = match.group(3).strip()

        # server_name / tool_name 缺失时跳过，避免下游 NPE
        if not server_name or not tool_name:
            logger.warning(
                "parse_xml_tool_calls: 跳过缺少 server_name/tool_name 的 use_mcp_tool 块",
            )
            continue

        # Parse JSON arguments —— 使用宽容解析（修复 4）
        arguments = _try_parse_arguments(arguments_str, server_name, tool_name)

        results.append({
            "tool_type": "mcp",
            "server_name": server_name,
            "tool_name": tool_name,
            "arguments": arguments,
        })

    # Parse <skill_disclosure> blocks
    skill_pattern = re.compile(
        r'<skill_disclosure>\s*'
        r'<skill_name>(.*?)</skill_name>\s*'
        r'<level>(.*?)</level>\s*'
        r'</skill_disclosure>',
        re.DOTALL,
    )

    for match in skill_pattern.finditer(text):
        skill_name = match.group(1).strip()
        level = match.group(2).strip() or "L2"  # 缺省视为 L2

        # skill_name 缺失时跳过
        if not skill_name:
            logger.warning(
                "parse_xml_tool_calls: 跳过缺少 skill_name 的 skill_disclosure 块",
            )
            continue

        results.append({
            "tool_type": "skill_disclosure",
            "skill_name": skill_name,
            "level": level,
        })

    return results


def remove_xml_tool_calls(text: str, tool_calls: list) -> str:
    """
    从文本中移除已解析的XML工具调用标签。

    这个函数比直接在 parse_xml_tool_calls 中移除更可靠，
    因为它只移除成功解析的工具调用，不会误移除格式错误的标签。

    Args:
        text: 原始文本
        tool_calls: parse_xml_tool_calls 返回的工具调用列表

    Returns:
        移除XML标签后的文本
    """
    if not isinstance(text, str):
        return text

    result = text

    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        if tc.get("tool_type") == "mcp":
            # 匹配完整的工具调用块
            xml_pattern = re.compile(
                r'<use_mcp_tool>\s*'
                r'<server_name>\s*' + re.escape(tc.get("server_name", "")) + r'\s*</server_name>\s*'
                r'<tool_name>\s*' + re.escape(tc.get("tool_name", "")) + r'\s*</tool_name>\s*'
                r'<arguments>\s*(.*?)\s*</arguments>\s*'
                r'</use_mcp_tool>',
                re.DOTALL,
            )
            result = xml_pattern.sub("", result)
        elif tc.get("tool_type") == "skill_disclosure":
            xml_pattern = re.compile(
                r'<skill_disclosure>\s*'
                r'<skill_name>\s*' + re.escape(tc.get("skill_name", "")) + r'\s*</skill_name>\s*'
                r'<level>\s*' + re.escape(tc.get("level", "")) + r'\s*</level>\s*'
                r'</skill_disclosure>',
                re.DOTALL,
            )
            result = xml_pattern.sub("", result)

    # 清理残留的孤立闭合标签
    result = re.sub(r'</use_mcp_tool>\s*', "", result)
    result = re.sub(r'</skill_disclosure>\s*', "", result)

    return result


def normalize_language_code(lang: str) -> str:
    """
    智能标准化语言代码，将各种格式的语言代码转换为标准格式。

    支持的输入格式：
    - BCP 47 风格：zh-Hans, zh-Hant, en-US
    - IETF 风格：zh-cmn-Hans, zh-yue-WUU
    - 简短格式：zh, en, de
    - 带区域代码：zh-CN, zh-TW, en-US

    返回标准格式的语言代码。
    """
    if not lang or not isinstance(lang, str):
        return lang

    lang_lower = lang.lower().strip()

    # 已经是可以直接使用的标准格式（带区域代码的简短格式），直接返回
    if len(lang_lower) == 2:
        return lang_lower

    # 处理带 "-" 的 BCP 47 / IETF 格式
    if "-" in lang or "_" in lang:
        parts = lang.replace("_", "-").split("-")
        primary_lang = parts[0].lower()

        # 特殊中文脚本转换：Hans -> CN, Hant -> TW
        if primary_lang == "zh":
            for part in parts[1:]:
                part_lower = part.lower()
                if part_lower in ("hans", "cmn"):
                    return "zh-CN"
                if part_lower in ("hant", "yue", "wuu", "mín-nán", "min-nan"):
                    return "zh-TW"

            # 如果没有脚本信息但有区域代码，使用区域代码
            for part in parts[1:]:
                part_lower = part.lower()
                if part_lower in ("cn", "sg"):
                    return "zh-CN"
                if part_lower in ("tw", "hk", "mo"):
                    return "zh-TW"

            # 默认返回 zh-CN
            return "zh-CN"

        # 其他语言，尝试返回标准格式
        if len(parts) >= 2:
            # 保留语言代码和区域代码的组合，如 en-US, de-DE
            return f"{primary_lang}-{parts[1].upper()}"

        return primary_lang

    # 如果已经是简短格式但长度不是2，可能是无效的，直接返回
    return lang


# ============================================================================
# 配置加载
# ============================================================================

CONFIG_FILE = "agent_config.json"


def load_config(config_path: str = CONFIG_FILE) -> dict:
    """
    加载配置文件。

    Raises:
        FileNotFoundError: 配置文件不存在
        ValueError: 配置文件顶层不是 JSON object
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(
            f"配置文件 {config_path} 顶层必须是 JSON object，实际为 {type(data).__name__}"
        )
    return data


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

    def __init__(self, config: dict) -> None:
        self.config = config
        self.model_config = config.get("model", {}) or {}
        self.exposure_config = config.get("exposure", {}) or {}
        self.skills_config = config.get("skills", {}) or {}
        self.mcp_config = config.get("mcpServers", {}) or {}

        # 模型信息
        self.model_url: str = self.model_config.get("url", "")
        self.model_key: str = self.model_config.get("key", "")
        self.model_name: str = self.model_config.get("model_name", "")
        self.context_length: int = int(self.model_config.get("context_length", 200000))

        # 暴露信息
        self.exposure_port: int = int(self.exposure_config.get("port", 20001))
        self.exposure_key: str = self.exposure_config.get("key", "")
        self.exposure_model_name: str = self.exposure_config.get("model_name", "agent")

        # Skills根目录
        self.skills_root: str = self.skills_config.get("root_dir", "")

        # MCP客户端
        self.mcp_client: Optional[MCPClient] = None

        # Skills引擎
        self.skills_engine: Optional[ProgressiveDisclosureEngine] = None
        self.available_skills: dict = {}

        # 状态标志
        self.model_ready: bool = False
        self.mcp_ready: bool = False
        self.skills_ready: bool = False

        # P0 - 任务跟踪器（解决"必须完成某类任务才允许结束"）
        # 当用户的原始查询中包含「保存/写入/文件/汇总」等关键词时，
        # terminal_tool_required 会被设为对应的工具名（如 "filesystem.write_file"），
        # process_agent_loop 会检查这个工具是否被实际调用过，未调用则不允许 finish。
        self.task_tracker: dict = {
            "original_query": "",
            "sub_goals": [],
            "achieved_goals": set(),
            "terminal_tool_required": None,
        }
        # P0 - 读取 client_setting 里的上下文管理配置（提前读好，避免后文反复 get）
        client_setting = self.config.get("client_setting", {}) or {}
        self.input_context_limit: int = int(client_setting.get("input_context_limit", 0))  # 0 表示不限制
        self.output_context_reserve: int = int(client_setting.get("output_context_reserve", 4096))
        self.max_consecutive_failures: int = int(client_setting.get("max_consecutive_failures", 6))
        self.loop_soft_threshold: int = int(client_setting.get("loop_soft_threshold", 3))
        self.loop_hard_threshold: int = int(client_setting.get("loop_hard_threshold", 5))
        # 工具结果最大字符数（对应 Cline message-builder.ts:28-29 的 50000）
        self.tool_result_max_chars: int = int(client_setting.get("tool_result_max_chars", 50000))
        # 大模型 HTTP 调用超时（秒），可在 client_setting 里覆盖
        self.llm_request_timeout: int = int(client_setting.get("llm_request_timeout", 120))
        # 修复 3: "必须调用 terminal_tool"提醒的注入计数（仅注入 1 次）
        self._terminal_tool_remind_injected: bool = False
        # 修复 3 补充: LoopDetectionTracker 软提醒也只注入 1 次
        self._loop_remind_injected: bool = False
        # 修复 2: 终止条件 A 的状态——本轮无工具调用且 terminal_tool_required 已调过
        self._terminal_tool_already_called: bool = False
        # 修复 2: 硬停止时跳过的原因（"max_iter" | "no_tool" | "mistake" | "loop"）
        self._hard_stop_reason: Optional[str] = None
        # 修复 2: 硬停止时 LLM 最后一轮文本（用于构造兜底响应）
        self._last_assistant_text: str = ""
        # 修复 2: 硬停止时 LLM 最后一条完整响应（包含 XML 标签前后的内容）
        self._last_raw_response: str = ""
        # 修复 5: 是否已经检测到本轮有 tool_calls（用于 _compact_messages 保留切点）
        self._last_had_tool_calls: bool = False

        # 关闭重入防护：避免外部异常路径下 close 被调用多次
        self._closed: bool = False

        # ----- 启动期基础校验（不阻断，但给出明确 warning） -----
        if not (0 < self.exposure_port < 65536):
            raise ValueError(
                f"exposure.port 非法: {self.exposure_port}，必须在 1-65535 之间"
            )
        if not self.model_url:
            raise ValueError("model.url 不能为空")
        if not self.model_name:
            raise ValueError("model.model_name 不能为空")
        if not self.model_key:
            logger.warning("model.key 为空，调用大模型将可能鉴权失败")
        if not self.exposure_key:
            logger.info("exposure.key 为空，将跳过对外 API Key 校验（仅供本地调试）")

    def test_model_connection(self) -> bool:
        """测试模型连接是否可用。"""
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
            logger.error("模型连接测试异常: %s", e, exc_info=True)
            return False

    def call_llm(self, messages: list, stream: bool = True):
        """
        调用大模型（流式或非流式）。

        - 非流式：直接复用 openai_client.output_non_sse
        - 流式：内联实现 SSE 适配，确保 response 在 with 块内使用并正确关闭
        """
        normalized_url = normalize_url(self.model_url)
        api_url = get_chat_completions_url(normalized_url)

        if not stream:
            from openai_client import output_non_sse  # 延迟 import 兼容旧路径
            return output_non_sse(api_url, self.model_key, self.model_name, messages)

        return self._sse_generator(api_url, messages)

    def _sse_generator(self, api_url: str, messages: list) -> Generator[str, None, None]:
        """
        将 API 返回的 HTTP 分块流重新格式化成 SSE 格式。

        使用 `with` 上下文管理 `requests.Response`，确保在生成器提前
        中断（客户端断开、异常、return）时底层 socket 连接也能被关闭。
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.model_key}",
        }

        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": True,
        }

        # 使用 context manager 确保连接关闭，避免长跑下 socket 句柄耗尽
        try:
            response = requests.post(
                api_url,
                headers=headers,
                json=payload,
                stream=True,
                timeout=self.llm_request_timeout,
            )
        except RequestsTimeout as e:
            logger.error("SSE 调用超时: %s", e)
            yield self._format_sse_error(f"Error calling LLM: timeout ({e})")
            return
        except RequestException as e:
            logger.error("SSE 调用网络异常: %s", e, exc_info=True)
            yield self._format_sse_error(f"Error calling LLM: {e}")
            return

        try:
            response.raise_for_status()
        except RequestException as e:
            logger.error("SSE 调用 HTTP 状态异常: %s", e)
            yield self._format_sse_error(f"Error calling LLM: HTTP {e}")
            return

        try:
            with response:
                buffer = b""
                # 使用 iter_content 获取原始数据块，然后重新组装成 SSE 格式
                for chunk in response.iter_content(chunk_size=None):
                    if not chunk:
                        continue
                    buffer += chunk
                    # 处理缓冲区，寻找完整的 SSE 消息
                    while b"\n\n" in buffer:
                        message, buffer = buffer.split(b"\n\n", 1)
                        message = message.strip()
                        if not message:
                            continue
                        # 检查是否是 data: 开头
                        if message.startswith(b"data: "):
                            decoded = message.decode("utf-8", errors="replace")
                            yield decoded + "\n\n"
                        elif message == b"data: [DONE]":
                            yield "data: [DONE]\n\n"

                # 处理缓冲区中剩余的数据
                if buffer.strip():
                    message = buffer.strip()
                    if message.startswith(b"data: "):
                        decoded = message.decode("utf-8", errors="replace")
                        yield decoded + "\n\n"
                    elif message == b"data: [DONE]":
                        yield "data: [DONE]\n\n"
        except Exception as e:
            # 生成器在迭代中可能因客户端断开/网络中断抛异常，
            # 这里兜底但不影响 SSE 流的正常收尾
            logger.error("SSE 流式迭代异常: %s", e, exc_info=True)

    @staticmethod
    def _format_sse_error(message: str) -> str:
        """把错误信息包装成 SSE chunk，方便客户端统一处理。"""
        payload = {
            "error": {
                "message": message,
                "type": "server_error",
            }
        }
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def init_mcp_clients(self) -> bool:
        """初始化MCP客户端连接。"""
        print("\n正在初始化MCP客户端...")

        try:
            temp_config: dict = {"mcpServers": {}}

            for name, server_config in self.mcp_config.items():
                if not isinstance(server_config, dict):
                    logger.warning(
                        "init_mcp_clients: 跳过非法 MCP server 配置项 %s (类型=%s)",
                        name, type(server_config).__name__,
                    )
                    continue
                if server_config.get("isActive", False):
                    temp_config["mcpServers"][name] = server_config

            if not temp_config["mcpServers"]:
                print("  没有需要连接的MCP服务器（全部isActive=false）")
                self.mcp_ready = True
                return True

            temp_config_path = "agent_mcp_temp.json"
            with open(temp_config_path, "w", encoding="utf-8") as f:
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
                # 即便中途抛异常也必须清理临时文件
                if os.path.exists(temp_config_path):
                    try:
                        os.remove(temp_config_path)
                    except OSError as e:
                        logger.warning("清理临时 MCP 配置文件失败: %s", e)

        except Exception as e:
            logger.error("MCP客户端初始化异常: %s", e, exc_info=True)
            return False

    def get_mcp_tools_for_prompt(self) -> str:
        """
        获取MCP工具列表，用于构建系统提示词（流派A：Cline风格XML格式）

        将MCP工具转换为Cline风格的XML工具描述，
        模型通过<use_mcp_tool>标签回传工具调用。
        """
        if not self.mcp_client or not self.mcp_ready:
            return ""

        tools = self.mcp_client.list_tools()

        if not tools:
            return ""

        lines = []

        for server_name, server_tools in tools.items():
            if not isinstance(server_tools, list):
                continue
            for tool in server_tools:
                if not isinstance(tool, dict):
                    continue
                tool_name = tool.get("name", "")
                if not tool_name:
                    continue
                tool_desc = tool.get("description", "") or ""
                input_schema = tool.get("inputSchema", {}) or {}

                # Cline风格的工具描述格式
                lines.append(f"""# Tool: {server_name}.{tool_name}
Description: {tool_desc}

Parameters:""")

                # 添加参数描述
                if isinstance(input_schema, dict):
                    props = input_schema.get("properties", {}) or {}
                    required_params = input_schema.get("required", []) or []
                    if not isinstance(props, dict):
                        props = {}
                    if not isinstance(required_params, list):
                        required_params = []
                    for param_name, param_info in props.items():
                        if not isinstance(param_info, dict):
                            param_info = {}
                        param_type = param_info.get("type", "string")
                        param_desc = param_info.get("description", "")
                        is_required = param_name in required_params
                        req_str = "(required)" if is_required else "(optional)"
                        lines.append(f"- {param_name}: {req_str} {param_desc} [{param_type}]")

                # 添加使用示例（教模型怎么回传）
                lines.append(f"""
Usage:
<use_mcp_tool>
<server_name>{server_name}</server_name>
<tool_name>{tool_name}</tool_name>
<arguments>{{ "param1": "value1", "param2": "value2" }}</arguments>
</use_mcp_tool>

""")

        return "\n".join(lines)

    async def call_mcp_tool(self, server_name: str, tool_name: str, arguments: Optional[dict]) -> dict:
        """调用MCP工具。"""
        if not self.mcp_client or not self.mcp_ready:
            return {"error": "MCP client not ready"}

        # 验证参数不能为空 - 但注意某些工具（如list_allowed_directories）确实不需要参数
        # 如果arguments是空字典但工具实际需要参数，MCP server会返回错误，这里不需要提前检查
        # 如果arguments是None或missing，才认为参数缺失
        if arguments is None:
            return {
                "error": (
                    f"工具 {server_name}.{tool_name} 的参数缺失！请检查XML格式，"
                    f"确保arguments标签内有有效的JSON参数（即使是空对象也要写{{}}）。"
                )
            }

        # 通用参数标准化：处理语言代码等参数
        arguments = self._normalize_tool_arguments(arguments)

        return await self.mcp_client.call_tool(server_name, tool_name, arguments)

    def _normalize_tool_arguments(self, arguments: dict) -> dict:
        """
        标准化工具参数，将不兼容的值转换为兼容的格式。
        这是一个通用处理，不针对特定的 MCP server。
        """
        if not arguments:
            return arguments

        args = arguments.copy()

        # 标准化语言代码
        if "language" in args:
            lang = args["language"]
            if isinstance(lang, str):
                normalized = normalize_language_code(lang)
                if normalized != lang:
                    args["language"] = normalized

        return args

    def init_skills(self) -> bool:
        """初始化Skills引擎。"""
        print("\n正在扫描Agent Skills...")

        if not self.skills_root or not os.path.exists(self.skills_root):
            print("  Skills根目录不存在，跳过")
            self.skills_ready = True
            return True

        try:
            self.skills_engine = ProgressiveDisclosureEngine(self.skills_root)
            self.available_skills = self.skills_engine.scan_skills() or {}

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
            logger.error("Skills初始化异常: %s", e, exc_info=True)
            return False

    def get_skills_for_prompt(self, query: str = "", level: DisclosureLevel = DisclosureLevel.L1_METADATA) -> str:
        """获取Skills提示词。"""
        if not self.skills_engine or not self.skills_ready:
            return ""

        if not self.available_skills:
            return ""

        # 使用 ProgressiveDisclosureEngine 的 to_prompt 方法
        skill_paths = list(self.available_skills.keys())
        return skills_to_prompt([self.skills_engine.skills_root / name for name in skill_paths])

    def get_activated_skill_instruction(self, skill_name: str) -> str:
        """
        获取指定 Skill 的 L2 指令层全文（按需披露）。

        这是渐进式披露的核心方法：初始只加载 L1 元数据，
        当大模型调用 skill_activate 工具时才加载 L2 完整指令。

        Args:
            skill_name: 技能名称

        Returns:
            Skill 的 L2 指令内容，如果技能不存在则返回错误信息
        """
        if not self.skills_engine or not self.skills_ready:
            return json.dumps({"error": "Skills engine not ready"}, ensure_ascii=False)

        if skill_name not in self.available_skills:
            return json.dumps(
                {"error": f"Skill '{skill_name}' not found. Available skills: {list(self.available_skills.keys())}"},
                ensure_ascii=False,
            )

        try:
            l2_prompt = self.skills_engine.get_skill_prompt(skill_name, DisclosureLevel.L2_INSTRUCTION)
            return l2_prompt
        except Exception as e:
            return json.dumps({"error": f"Failed to load skill '{skill_name}': {str(e)}"}, ensure_ascii=False)

    def build_system_prompt(self, query: str = "") -> str:
        """构建系统提示词。"""
        parts = []

        parts.append("""你是一个智能体Agent助手，可以调用工具来完成任务。

可用工具分为两类：

## 1. MCP类 (Model Context Protocol)  
MCP服务器提供的标准化工具，具有统一的接口和结构化参数。已为你提供了若干MCP server，每个server包含若干工具，每个工具是一个函数。MCP工具列表见下方。
                     
## 2. Agent Skills类（渐进式披露机制）
Agent技能，提供更灵活的功能和更丰富的领域知识。

**重要**：Agent Skills 采用渐进式披露机制：
- **初始状态**：系统提示词中只包含每个 Skill 的名称和简要描述（用于路由决策）
- **按需获取**：当你判断需要使用某个 Skill 时，必须发送 `<skill_disclosure>` XML标签来获取该 Skill 的完整指令（L2）或资源（L3）
- **执行任务**：获取完整指令后，按照指令中的步骤执行任务

如果你不调用 `<skill_disclosure>` 获取完整指令，你将无法正确使用任何 Agent Skill。

### Skill 披露请求格式：

当你需要获取某个 Skill 的详细信息时，请发送以下格式的 XML 标签：

<skill_disclosure>
<skill_name>技能名称</skill_name>
<level>L2</level>
</skill_disclosure>

- `skill_name`: 技能的名称（必须与上方列表中的名称完全匹配）
- `level`: 披露级别
  - `L2`: 获取该技能的完整指令文档（包含执行步骤、注意事项等）
  - `L3`: 获取该技能的附加资源（参考链接、模板文件等）

### 使用示例：

获取名为 "code_review" 技能的完整指令：
<skill_disclosure>
<skill_name>code_review</skill_name>
<level>L2</level>
</skill_disclosure>

获取名为 "api_design" 技能的资源文件：
<skill_disclosure>
<skill_name>api_design</skill_name>
<level>L3</level>
</skill_disclosure>

## 任务执行原则

当你面对复杂任务时，必须遵循以下原则：

1. **分解任务为具体步骤**：将大任务分解成多个可执行的小步骤
2. **每个步骤都要调用工具**：不能只是说"让我继续"，必须实际调用工具执行
3. **按顺序执行**：先完成前置步骤，再执行后续步骤
4. **立即行动**：不要在回复中说"首先"、"然后"而不调用工具，要直接调用工具

**常见错误**：如果你只是回复"让我搜索更多信息"或"让我继续"，但没有实际调用任何工具，这是不允许的！

## Agent Loop 结束标志

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
            parts.append("\n## 以下是 Agent Skills（按需获取完整指令）\n")
            parts.append(skills_prompt)

        return "\n".join(parts)

    async def initialize(self) -> bool:
        """初始化所有组件。"""
        print("\n" + "=" * 60)
        print("Agent客户端初始化")
        print("=" * 60)

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

        print("\n" + "=" * 60)
        print("初始化完成！所有组件就绪。")
        print("=" * 60)

        return True

    async def close(self) -> None:
        """关闭所有连接并清理资源。具备重入保护，多次调用安全。"""
        if self._closed:
            return
        self._closed = True

        print("\n正在关闭Agent客户端...")

        # 关闭 MCP 客户端；先取引用再置空，确保重复调用安全
        mcp_client = self.mcp_client
        self.mcp_client = None
        if mcp_client:
            try:
                await mcp_client.close()
                print("[OK] MCP客户端已关闭")
            except Exception as e:
                logger.error("关闭MCP客户端时出错: %s", e, exc_info=True)

        self.mcp_ready = False
        self.model_ready = False
        self.skills_ready = False
        print("[OK] Agent客户端已关闭")

    def create_app(self) -> FastAPI:
        """创建FastAPI应用。"""
        app = FastAPI(title="Agent Client API")

        # 添加CORS中间件
        # 注意：allow_origins=["*"] + allow_credentials=True 在新版 Starlette 中会抛
        # "Cannot use allow_credentials=True with allow_origins=['*']"。这里保留历史行为
        # （Cherry Studio 等本地客户端依赖此宽松配置），如需部署到公网请收紧配置。
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        @app.get("/v1/models")
        async def list_models():
            """列出可用模型。"""
            return {
                "object": "list",
                "data": [{
                    "id": self.exposure_model_name,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "agent",
                    "context_window": self.context_length,
                    "capabilities": ["streaming", "tools", "vision"],
                }],
            }

        @app.post("/v1/chat/completions")
        async def chat_completions(
            request: dict,
            authorization: Optional[str] = Header(None),
        ):
            """处理聊天完成请求。"""
            # 验证 API Key：仅当 exposure_key 非空时校验；空配置 = 不校验
            if self.exposure_key:
                if not authorization:
                    raise HTTPException(status_code=401, detail="Missing Authorization header")
                token = authorization.replace("Bearer ", "", 1)
                if token != self.exposure_key:
                    raise HTTPException(status_code=401, detail="Invalid API key")

            # 验证model参数
            requested_model = request.get("model", "")
            if requested_model and requested_model != self.exposure_model_name:
                raise HTTPException(
                    status_code=404,
                    detail=f"Model '{requested_model}' not found. Available model: {self.exposure_model_name}",
                )

            messages = request.get("messages", [])
            stream = request.get("stream", True)

            if not messages:
                raise HTTPException(status_code=400, detail="No messages provided")

            # 兜底：用户消息为非字符串时避免 .get("content","") 抛错
            last_user_content = ""
            if messages and isinstance(messages[-1], dict):
                raw_content = messages[-1].get("content", "")
                last_user_content = raw_content if isinstance(raw_content, str) else ""

            system_prompt = self.build_system_prompt(last_user_content)
            system_msg = {
                "role": "system",
                "content": system_prompt,
            }

            # 清空并重新开始调试日志（每次新请求独立记录）
            clear_debug_log()

            # 记录系统提示词到调试日志
            log_to_file("SYSTEM PROMPT (系统提示词)", system_prompt)

            all_messages = [system_msg] + messages

            # 使用 process_agent_loop 处理工具调用循环
            max_agent_loop = int(self.config.get("client_setting", {}).get("max_agent_loop", 10))
            final_response, was_cut_off, loop_count = await self.process_agent_loop(all_messages, max_agent_loop)
            # 优化 6: 收集诊断元信息（loop 计数 / 硬停止原因 / 任务闭环工具是否被调用）
            diag_metadata = {
                "agent_loop_count": loop_count,
                "agent_loop_hard_stop": was_cut_off,
                "agent_loop_hard_stop_reason": getattr(self, "_hard_stop_reason", None),
                "agent_loop_terminal_tool_required": self.task_tracker.get("terminal_tool_required"),
                "agent_loop_terminal_tool_called": getattr(self, "_terminal_tool_already_called", False),
            }

            # 修复 1+6: 不论是 was_cut_off 还是正常结束，都返回 200
            # —— final_response 已由 process_agent_loop 里的 _build_fallback_response 构造过
            # 不会再走到 500 分支。
            hard_stop_reason = getattr(self, "_hard_stop_reason", None)
            logger.debug(
                "/v1/chat/completions 收尾: was_cut_off=%s, loop_count=%s, "
                "hard_stop_reason=%s, stream=%s, text_len=%s",
                was_cut_off, loop_count, hard_stop_reason, stream,
                len(final_response) if final_response else 0,
            )

            # 修复 6: 统一构造 OpenAI 格式的 chat.completion 响应
            # - finish_reason 固定为 "stop"（OpenAI 客户端只认这个值表示正常结束）
            # - usage 填充占位值
            # - object: "chat.completion", created: 当前时间戳
            response_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
            created_ts = int(time.time())
            base_payload = {
                "id": response_id,
                "object": "chat.completion",
                "created": created_ts,
                "model": self.exposure_model_name,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": final_response or "",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            }
            if was_cut_off:
                logger.warning(
                    "修复 1 落地: 硬停止护栏触发（reason=%s），返回 200 兜底响应而非 500",
                    hard_stop_reason,
                )

            # 优化 6: 把诊断元信息附加到 base_payload.metadata
            # Cherry Studio / OpenAI 客户端通常忽略此字段但下游可埋点分析
            base_payload["metadata"] = diag_metadata

            if stream:
                # 修复 6: 流式分支——保证最后一个 chunk 以 finish_reason="stop" 收尾
                def generate() -> Generator[str, None, None]:
                    chunk_id = response_id
                    # 优化 6: 第一条 chunk 携带诊断元信息（OpenAI 兼容字段 metadata）
                    meta_chunk = {
                        "id": chunk_id,
                        "object": "chat.completion.chunk",
                        "created": created_ts,
                        "model": self.exposure_model_name,
                        "metadata": diag_metadata,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"role": "assistant"},
                                "finish_reason": None,
                            }
                        ],
                    }
                    yield f"data: {json.dumps(meta_chunk, ensure_ascii=False)}\n\n"

                    # 发送正文 chunk
                    content_chunk = {
                        "id": chunk_id,
                        "object": "chat.completion.chunk",
                        "created": created_ts,
                        "model": self.exposure_model_name,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": final_response or ""},
                                "finish_reason": None,
                            }
                        ],
                    }
                    yield f"data: {json.dumps(content_chunk, ensure_ascii=False)}\n\n"

                    # 修复 6: 最后一个 chunk 以 finish_reason="stop" 收尾
                    stop_chunk = {
                        "id": chunk_id,
                        "object": "chat.completion.chunk",
                        "created": created_ts,
                        "model": self.exposure_model_name,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {},
                                "finish_reason": "stop",
                            }
                        ],
                    }
                    yield f"data: {json.dumps(stop_chunk, ensure_ascii=False)}\n\n"
                    yield "data: [DONE]\n\n"

                return StreamingResponse(
                    generate(),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        # 优化 6: 把诊断元信息暴露到 HTTP header
                        # 便于 Cherry Studio 等客户端无需解析 SSE body 即可观测
                        "X-Agent-Loop-Count": str(loop_count),
                        "X-Agent-Loop-Hard-Stop": "1" if was_cut_off else "0",
                        "X-Agent-Loop-Hard-Stop-Reason": str(hard_stop_reason or ""),
                    },
                )
            else:
                return JSONResponse(content=base_payload)

        @app.get("/health")
        async def health():
            """健康检查。"""
            return {
                "status": "healthy" if (self.model_ready and self.mcp_ready and self.skills_ready) else "degraded",
                "model_ready": self.model_ready,
                "mcp_ready": self.mcp_ready,
                "skills_ready": self.skills_ready,
            }

        return app

    def _call_llm(self, messages: list) -> str:
        """
        调用大模型获取回答（流派A：不在请求中带tools参数）

        由于使用System Prompt中的XML格式来描述工具，
        所以这里不需要在API请求中传递tools参数。

        Returns:
            str: 大模型的原始回答文本
        """
        normalized_url = normalize_url(self.model_url)
        api_url = get_chat_completions_url(normalized_url)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.model_key}",
        }

        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
        }

        # 修复：使用 with 语句确保 response 句柄被显式释放，
        # 避免在多请求并发下出现 socket 句柄耗尽。
        try:
            logger.debug("Calling LLM (流派A: no tools in request)")
            with requests.post(
                api_url,
                headers=headers,
                json=payload,
                timeout=self.llm_request_timeout,
            ) as response:
                response.raise_for_status()
                result = response.json()

            if not isinstance(result, dict) or "choices" not in result or not result["choices"]:
                return ""

            choice = result["choices"][0]
            if not isinstance(choice, dict):
                return ""
            message = choice.get("message", {}) or {}
            content = message.get("content", "")
            content = content if isinstance(content, str) else ""

            logger.debug("LLM response content_len=%s", len(content) if content else 0)
            return content

        except RequestsTimeout as e:
            logger.error("LLM 调用超时: %s", e, exc_info=True)
            return f"Error calling LLM: timeout ({e})"
        except RequestException as e:
            logger.error("LLM 调用网络异常: %s", e, exc_info=True)
            return f"Error calling LLM: {e}"
        except (JSONDecodeError, ValueError) as e:
            logger.error("LLM 响应 JSON 解析失败: %s", e, exc_info=True)
            return f"Error calling LLM: invalid JSON response ({e})"
        except Exception as e:
            logger.error("LLM 调用未知异常: %s", e, exc_info=True)
            return f"Error calling LLM: {e}"

    # _build_tools_list 已移除 - 流派A不再使用OpenAI tools参数

    async def _handle_tool_call(self, parsed_tool: dict) -> str:
        """
        处理XML解析后的工具调用（流派A）

        parsed_tool: parse_xml_tool_calls 返回的字典，包含:
        - tool_type: "mcp" or "skill_disclosure"
        - server_name, tool_name, arguments (for mcp)
        - skill_name, level (for skill_disclosure)
        """
        if not isinstance(parsed_tool, dict):
            return json.dumps({"error": "工具调用参数不是合法字典"}, ensure_ascii=False)

        try:
            tool_type = parsed_tool.get("tool_type")
            logger.debug("_handle_tool_call: tool_type=%s", tool_type)

            if tool_type == "skill_disclosure":
                # 处理 skill_disclosure 请求
                skill_name = parsed_tool.get("skill_name", "")
                level = parsed_tool.get("level", "L2")
                logger.debug("  skill_disclosure: name=%s, level=%s", skill_name, level)

                if level == "L3":
                    return self._get_skill_l3_content(skill_name)
                return self.get_activated_skill_instruction(skill_name)

            if tool_type == "mcp":
                # 处理 MCP 工具调用
                server_name = parsed_tool.get("server_name", "")
                tool_name = parsed_tool.get("tool_name", "")
                arguments = parsed_tool.get("arguments", {})

                logger.debug("  MCP tool: server=%s, tool=%s", server_name, tool_name)

                # 检查是否有解析错误
                if isinstance(arguments, dict) and "__parse_error__" in arguments:
                    error_msg = (
                        f"参数JSON格式错误！您提供的arguments内容无法解析为有效JSON。"
                        f"请检查XML格式，确保<arguments>标签内是有效的JSON对象，例如："
                        f'<arguments>{{"query": "搜索内容"}}</arguments>'
                    )
                    logger.debug("  参数解析错误: %s", arguments.get("__error__"))
                    return json.dumps({"error": error_msg}, ensure_ascii=False)

                result = await self.call_mcp_tool(server_name, tool_name, arguments)
                return self._serialize_tool_result(result)

            return json.dumps({"error": f"Unknown tool type: {tool_type}"}, ensure_ascii=False)

        except Exception as e:
            # 工具异常不应让整个请求 500，返回结构化错误让模型有抓手重试
            logger.error("_handle_tool_call 异常: %s", e, exc_info=True)
            return json.dumps({"error": f"工具执行异常: {str(e)}"}, ensure_ascii=False)

    def _get_skill_l3_content(self, skill_name: str) -> str:
        """
        获取Skill的L3级别内容（包含references等资源）。
        """
        if not self.skills_engine or not self.skills_ready:
            return json.dumps({"error": "Skills engine not ready"}, ensure_ascii=False)

        if skill_name not in self.available_skills:
            return json.dumps({"error": f"Skill '{skill_name}' not found"}, ensure_ascii=False)

        try:
            l3_content = self.skills_engine.get_skill_prompt(skill_name, DisclosureLevel.L3_RESOURCE)
            return l3_content
        except Exception as e:
            return json.dumps({"error": f"Failed to load L3 content for '{skill_name}': {str(e)}"}, ensure_ascii=False)

    def _analyze_user_intent(self, messages: list) -> None:
        """
        分析用户原始查询意图，初始化 task_tracker。

        简单关键词检测 - 覆盖中文常见写作场景：
        - 包含「保存/写入/下载/导出」+「文件」 -> 目标工具 filesystem.write_file
        - 包含「汇总/总结」+「文件」           -> 目标工具 filesystem.write_file
        - 包含「调研/搜索」+「汇总」           -> 目标工具 filesystem.write_file
        """
        # 从 messages 中提取原始用户查询
        original_query = ""
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            if msg.get("role") == "user" and isinstance(msg.get("content"), str):
                original_query = msg["content"]
                break  # 取最早的用户消息

        self.task_tracker["original_query"] = original_query
        self.task_tracker["sub_goals"] = []
        self.task_tracker["achieved_goals"] = set()
        self.task_tracker["terminal_tool_required"] = None

        if not original_query:
            return

        q = original_query.lower()

        # 检测是否需要调用 filesystem.write_file 作为任务闭环
        write_keywords = ["保存", "写入", "下载到", "导出", "生成文件", "存为文件", "存到文件"]
        file_keywords = ["文件", "本地", "磁盘", "txt", "md", "markdown", "json", "csv"]
        summary_keywords = ["汇总", "总结", "归纳", "整理", "摘要"]

        has_write_intent = any(kw in q for kw in write_keywords)
        has_file_intent = any(kw in q for kw in file_keywords)
        has_summary_intent = any(kw in q for kw in summary_keywords)

        # 情况1：直接表达"写入/保存到文件"
        if has_write_intent and has_file_intent:
            self.task_tracker["terminal_tool_required"] = "filesystem.write_file"
            self.task_tracker["sub_goals"].append("将结果写入本地文件")
            return

        # 情况2："搜索/调研 + 汇总/总结" （隐含写文件需求）
        search_keywords = ["搜索", "查询", "调研", "查找", "搜集"]
        if any(kw in q for kw in search_keywords) and has_summary_intent:
            self.task_tracker["terminal_tool_required"] = "filesystem.write_file"
            self.task_tracker["sub_goals"].append("将搜索结果汇总到本地文件")
            return

        # 情况3：仅有汇总/总结意图，也默认要求写文件
        if has_summary_intent and has_file_intent:
            self.task_tracker["terminal_tool_required"] = "filesystem.write_file"
            self.task_tracker["sub_goals"].append("将汇总结果写入本地文件")
            return

    def _check_terminal_tool_called(self, messages: list) -> bool:
        """
        结构化检查：task_tracker 中声明的 terminal_tool_required 是否被实际调用过。

        修复：三重检查
        - 检查 1: 扫描 assistant 消息中真实存在的 <use_mcp_tool> XML 标签，
                  解析出 server_name.tool_name 后与 target 比对（最权威）
        - 检查 2: 检查所有 assistant 消息中的"已调用工具: ..."提示
        - 检查 3: 检查 assistant content 中是否有同义执行后描述

        这样即使上层压缩逻辑误砍了部分消息历史，<use_mcp_tool> 调用记录
        仍然能被正确识别为已调用。
        """
        target = self.task_tracker.get("terminal_tool_required")
        if not target:
            return True  # 没有目标工具，认为"已满足"

        # 解析 target 为 (server_name, tool_name) 二元组
        if "." in target:
            target_server, target_tool = target.rsplit(".", 1)
        else:
            target_server, target_tool = "", target

        for msg in messages:
            if not isinstance(msg, dict):
                continue
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content", "")
            if not isinstance(content, str):
                continue

            # 检查 1: 扫描真实存在的 <use_mcp_tool> XML 标签（最权威的证据）
            # 复用现有解析器，按 server_name + tool_name 精确比对
            try:
                for tc in parse_xml_tool_calls(content):
                    if tc.get("tool_type") != "mcp":
                        continue
                    if (
                        tc.get("server_name") == target_server
                        and tc.get("tool_name") == target_tool
                    ):
                        return True
            except Exception:
                # 解析失败不影响后续检查
                pass

            # 检查 2: "已调用工具: server.tool" 格式摘要
            if f"已调用工具: {target}" in content or f"已调用工具:{target}" in content:
                return True

            # 检查 3: 同义执行后描述
            if target in content and any(
                kw in content for kw in ["已调用", "已成功调用", "完成调用", "已执行"]
            ):
                return True

        return False

    def _truncate_tool_result(self, result: str, max_chars: int = 50000) -> str:
        """
        工具结果截断 - 解决 C 类问题（避免超长工具结果撑爆上下文）

        对应 Cline message-builder.ts:28-29
        超过 max_chars 字符的，保留前 max_chars 字符 + 截断提示。
        """
        if not isinstance(result, str):
            try:
                result = json.dumps(result, ensure_ascii=False)
            except (TypeError, ValueError):
                result = str(result)

        if len(result) <= max_chars:
            return result

        truncated = result[:max_chars]
        return (
            truncated
            + f"\n\n[...内容已截断，总长度 {len(result)} 字符，保留前 {max_chars} 字符...]"
        )

    def _estimate_tokens(self, messages: list) -> int:
        """
        粗略估算消息列表的 token 数。

        不引入新依赖，采用"3 字符 ≈ 1 token"的简单启发式 (对应 Cline 经验值)。
        该估算在中文 / JSON 负载下误差在 30% 以内，足以用来触发截断阈值。

        优化 2: 改为按字符累加，避免每轮 json.dumps 全部历史
        （旧实现在长上下文下每次调用都要重新序列化几十 KB，浪费严重）。
        """
        total_chars = 0
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            content = msg.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
            elif content is not None:
                # 非字符串内容（如 list[dict]）用 str() 兜底估算
                try:
                    total_chars += len(json.dumps(content, ensure_ascii=False))
                except (TypeError, ValueError):
                    total_chars += len(str(content))
            # 额外算上 role / 字段名占用的 token (粗略 +2 per message)
            total_chars += 2
        return total_chars // 3

    def _find_last_tool_call_index(self, messages: list) -> int:
        """
        修复 5: 找到消息列表中"最近一轮有 tool_calls"的起始索引。

        返回的索引 i 表示 messages[i] 是含 tool_calls 的 assistant 消息，
        从 i 开始到末尾的所有消息都应被保留（避免 compact 挤掉"工具已成功调用"的结果）。
        如果找不到 tool_calls 消息，返回 -1。
        """
        # 倒序扫描
        for i in range(len(messages) - 1, -1, -1):
            if not isinstance(messages[i], dict):
                continue
            msg = messages[i]
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content", "")
            if not isinstance(content, str):
                continue
            # 之前插入过 "（已调用工具: ...）" 摘要，或 "已调用工具: ..." 类文本
            if "已调用工具" in content or "<use_mcp_tool>" in content or "<skill_disclosure>" in content:
                return i
        return -1

    def _compact_messages(self, messages: list) -> None:
        """
        上下文压缩 - 解决 D 类问题（上下文无限增长）

        策略两层：
        1. 规则化截断：将早期 <tool_result> 内容只保留前 2000 字符 + 截断标记
        2. 如果还不够，删除最早的用户-助手对话对（保留 system 和最近 5 轮）

        切点必须 turn-start 对齐 - 不会切坏 assistant + user 配对。

        修复 5 补充：
        - 消息数 ≤ 12 不再 compact（已经接近稳定状态）
        - 保留最近一次 tool_calls 及其之后的所有消息（避免挤掉 write_file 成功后的
          "文件已写入"工具结果，导致 LLM 看不到任务闭环）
        """
        if not messages:
            return

        # ===== 修复 5: 消息数 ≤ 12 不再触发任何压缩 =====
        if len(messages) <= 12:
            logger.debug(
                "_compact_messages: 消息数 %d ≤ 12，跳过压缩",
                len(messages),
            )
            return

        # ===== 第一步：截断早期 tool_result =====
        # 修复 5: 只截断"最近一次 tool_calls 轮次"之前的 tool_result，
        # 避免压坏刚写入文件的 "文件已写入" 反馈。
        cut_idx = self._find_last_tool_call_index(messages)
        truncate_range_end = cut_idx if cut_idx > 0 else len(messages)

        truncated_count = 0
        for i, msg in enumerate(messages[:truncate_range_end]):
            if not isinstance(msg, dict):
                continue
            if msg.get("role") == "user" and isinstance(msg.get("content"), str):
                content = msg["content"]
                if "<tool_result>" in content and len(content) > 4000:
                    # 找到 <tool_result> ... </tool_result> 部分
                    start = content.find("<tool_result>")
                    end = content.rfind("</tool_result>")
                    if start != -1 and end != -1 and end > start:
                        inner = content[start + len("<tool_result>"):end]
                        if len(inner) > 2000:
                            truncated_inner = (
                                inner[:2000]
                                + f"\n\n[...工具结果已压缩，原长度 {len(inner)} 字符...]"
                            )
                            new_content = (
                                content[:start + len("<tool_result>")]
                                + truncated_inner
                                + content[end:]
                            )
                            msg["content"] = new_content
                            truncated_count += 1
        if truncated_count:
            logger.debug(
                "_compact_messages: 截断了 %d 条早期工具结果（cut_idx=%s，跳过最后 tool_calls 轮次）",
                truncated_count, cut_idx,
            )

        # ===== 第二步：如果仍超限，删除早期对话对 =====
        if self.input_context_limit <= 0:
            return

        threshold = self.input_context_limit - self.output_context_reserve
        if self._estimate_tokens(messages) <= threshold:
            return

        # 保留 system (第一条) + 最后 5 轮对话 (10 条消息)
        if not messages:
            return
        system_msg = None
        if messages[0].get("role") == "system":
            system_msg = messages[0]

        # 修复 5: 保留"最近 tool_calls 轮次"起到最后的所有消息
        if cut_idx > 0:
            tail = messages[cut_idx:]  # 含 tool_calls 及之后的 tool_result/assistant
        else:
            tail = messages[-10:]  # 退化：最后 5 轮 = 10 条

        # 优化 3: 构造新列表时把 system_msg 单独保留，避免与 tail[0] 重复
        new_messages = []
        if system_msg is not None:
            if not tail or tail[0] is not system_msg:
                new_messages.append(system_msg)
        new_messages.extend(tail)

        # 找到被删除的范围，插入一条 system 提示
        if len(new_messages) < len(messages):
            notice = {
                "role": "system",
                "content": (
                    "[系统通知] 上下文窗口接近上限，已自动压缩早期对话历史。"
                    "如需参考早期内容，请重新发起会话。"
                ),
            }
            insert_idx = 1 if system_msg is not None else 0
            new_messages.insert(insert_idx, notice)

        # 优化 3: 改用切片赋值（mutates in place 但避免 clear+extend 的瞬时空列表）
        messages[:] = new_messages
        logger.debug(
            "_compact_messages: 删除早期对话对，消息数 %d（cut_idx=%s）",
            len(new_messages), cut_idx,
        )

    def _inject_user_reminder(self, messages: list, content: str) -> None:
        """
        修复 3: 追加一条 user 角色的提醒消息。

        为什么改为 user role：
        - OpenAI 兼容 API 在 system 角色中频繁插入提醒，模型容易"注意力衰减"
        - user role 提醒在对话中更突出，模型更容易读到
        - 配合修复 3 的"最多注入 1 次"逻辑，避免每两轮就刷一条
        """
        messages.append({"role": "user", "content": content})
        logger.debug("注入 user 提醒: %s...", content[:80])

    def _inject_system_reminder(self, messages: list, content: str) -> None:
        """
        追加一条 system 角色的提醒消息 (P0 - 关键修复)

        修复 3 补充：
        - 业务级强制提醒（"必须调 terminal_tool"）仅用一次，之后切到不注入
        - 仍然保留 system 提醒的合法性，用于结构性上下文补齐
        """
        messages.append({"role": "system", "content": content})
        logger.debug("注入 system 提醒: %s...", content[:80])

    def _serialize_tool_result(self, result: Any) -> str:
        """序列化工具调用结果，处理 TextContent 等特殊类型。"""
        # 如果已经是字符串，直接返回
        if isinstance(result, str):
            return result

        # 尝试直接 JSON 序列化
        try:
            return json.dumps(result, ensure_ascii=False)
        except TypeError:
            # 如果失败，可能是 TextContent 对象列表 / 包含不可 JSON 序列化的对象
            if isinstance(result, list):
                items = []
                for item in result:
                    if hasattr(item, "text"):
                        items.append(item.text)
                    elif hasattr(item, "data"):
                        items.append(item.data)
                    else:
                        items.append(str(item))
                return json.dumps({"content": items}, ensure_ascii=False)
            if isinstance(result, dict):
                # 递归尝试把 dict 内每个 value 提取成可 JSON 序列化的形式
                safe_dict = {}
                for k, v in result.items():
                    if hasattr(v, "text"):
                        safe_dict[k] = v.text
                    elif hasattr(v, "data"):
                        safe_dict[k] = v.data
                    else:
                        try:
                            json.dumps(v)
                            safe_dict[k] = v
                        except TypeError:
                            safe_dict[k] = str(v)
                return json.dumps(safe_dict, ensure_ascii=False)
            return json.dumps({"content": str(result)}, ensure_ascii=False)

    def _build_fallback_response(
        self,
        reason: str,
        loop_count: int,
        last_text: str = "",
    ) -> str:
        """
        修复 1+6: 构造硬停止护栏触发后的兜底响应文本。

        这个文本会作为 OpenAI chat.completion 的 content 返回给客户端，
        finish_reason 固定为 "stop"（这是修复 6 要求的）。

        Args:
            reason: 硬停止原因（"max_iter" | "no_tool" | "mistake" | "loop"）
            loop_count: 已循环轮次
            last_text: LLM 上一轮的原始文本（XML 标签已被剥除）

        Returns:
            用于填充 content 字段的字符串
        """
        reason_msg_map = {
            "max_iter": f"已达到最大循环次数（{loop_count} 轮）",
            "no_tool": f"连续多轮未检测到有效工具调用或结束标志（{loop_count} 轮）",
            "mistake": "连续多轮工具调用均失败",
            "loop": "检测到重复调用同一工具的异常模式",
        }
        reason_msg = reason_msg_map.get(reason, "任务已主动结束")

        # 优化 4: 清理 last_text 里的 "Error calling LLM" 原始错误串,
        # 避免把内部异常信息暴露给终端用户.
        tail = (last_text or "").strip()
        if tail.startswith("Error calling LLM"):
            tail = ""

        if tail:
            # 剥除可能的 finish 标签残留
            tail = tail.replace("</agent_loop_finish>", "").strip()

        if tail:
            return (
                f"{tail}\n\n"
                f"[系统提示] Agent Loop 已主动结束（原因：{reason_msg}）。"
                f"以上为已收集到的最终回答。"
            )
        # 兜底默认文本，避免返回空 content
        return (
            f"任务已结束。{reason_msg}。\n"
            f"如需进一步处理，请重新发起请求或调整提示词。"
        )

    async def process_agent_loop(
        self,
        messages: list,
        max_agent_loop: int = 10,
    ) -> tuple:
        """
        处理 Agent Loop 循环（流派A：XML解析方式，P0 增强版 + 修复 1-6）。

        修复后的终止条件（修复 2）：
        - 条件 A（柔性结束）：本轮 LLM 响应无任何工具调用 AND
                                terminal_tool_required 已被实际调用过
                            -> 直接结束（用本轮文本作为最终回答）
        - 条件 B（显式结束）：检测到 `</agent_loop_finish>` 且
                                terminal_tool_required 已调过（如果声明了）-> 结束
        - 条件 C（硬停止）：max_agent_loop 达到上限 /
                          MistakeTracker 连续失败 / LoopDetectionTracker 硬阈值 /
                          错误响应（is_error_response）
                          -> 修复 1: 返回 200 兜底响应（不抛 500）
        注意：已移除"连续 N 轮无工具调用"计数器护栏，依靠 max_agent_loop 上限作为唯一轮次控制。

        修复后的提醒注入（修复 3）：
        - "必须调用 terminal_tool" 提醒仅在第一次需要时注入 1 次
        - 提醒使用 user role，避开 system 重复添加带来的注意力衰减
        """
        AGENT_LOOP_FINISH_TAG = "</agent_loop_finish>"

        # 修复 3: 重置本请求专属的提醒注入计数
        self._terminal_tool_remind_injected = False
        self._loop_remind_injected = False
        self._hard_stop_reason = None
        self._last_assistant_text = ""
        self._last_raw_response = ""
        self._last_had_tool_calls = False
        self._terminal_tool_already_called = False

        # P0 - 初始化任务跟踪器
        self._analyze_user_intent(messages)
        logger.debug(
            "process_agent_loop 启动: original_query='%s...', terminal_tool_required=%s",
            (self.task_tracker["original_query"] or "")[:50],
            self.task_tracker["terminal_tool_required"],
        )

        # P0 - 初始化本请求专属的 tracker
        mistake_tracker = MistakeTracker(max_consecutive=self.max_consecutive_failures)
        loop_tracker = LoopDetectionTracker(
            soft=self.loop_soft_threshold,
            hard=self.loop_hard_threshold,
        )

        for loop_count in range(1, max_agent_loop + 1):
            logger.debug("Agent Loop 第 %d 轮", loop_count)

            # 修复：禁用上下文压缩
            # 之前的 _compact_messages 实现存在严重 bug：在第 N 轮调用 write_file 后，
            # cut_idx 会定位到第 N 轮的 assistant 消息，导致：
            #   1) 第 N 轮之前的所有对话（包括大模型刚生成的完整文章、
            #      已成功调用的 write_file 工具结果、用户原始任务）被砍掉
            #   2) 同时插入一条 "[系统通知] 上下文窗口接近上限..." 的 system 消息
            # 这两个组合在一起会让大模型产生严重的"失忆"——以为任务从未开始，
            # 然后回复"看起来这是一个新的开始"（见 debug.log 第 10 轮现象）。
            #
            # 解决：不再调用 _compact_messages。
            # 用户的 deepseek-v4-pro 上下文窗口 200000，input_context_limit=20000
            # 配置过激，触发了不该触发的压缩。让大模型原生上下文管理即可。
            # _compact_messages 函数体保留，但永不再调用。
            # 如果未来需要压缩功能，必须重写以保留"完整对话链"和"工具调用证据"。

            # 记录当前轮次的消息列表
            # 单条 message content 截断到 500 字符，整个 snapshot 上限 200KB
            snapshot_parts = []
            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                content = str(msg.get("content", ""))[:500]
                snapshot_parts.append(f"[{msg.get('role', 'unknown')}]\n{content}")
            messages_snapshot = "\n\n".join(snapshot_parts)
            if len(messages_snapshot) > 200_000:
                messages_snapshot = (
                    messages_snapshot[:200_000]
                    + f"\n\n[...已截断，总长度 {len(messages_snapshot)} 字符...]"
                )
            log_to_file(f"AGENT LOOP 第 {loop_count} 轮 - 消息列表", messages_snapshot)

            # 调用LLM获取响应（流派A：不传tools参数）
            response_text = self._call_llm(messages)

            # 记录LLM响应
            log_to_file(f"AGENT LOOP 第 {loop_count} 轮 - LLM响应", response_text or "(空响应)")

            # 记录本轮 LLM 响应，供硬停止时构造兜底响应
            self._last_raw_response = response_text or ""
            self._last_assistant_text = (response_text or "").strip()

            # 解析XML工具调用标签
            tool_calls = parse_xml_tool_calls(response_text)

            # 检查响应是否有效（排除错误消息）
            is_error_response = (
                not response_text
                or response_text.startswith("Error calling LLM:")
            )

            if tool_calls:
                # 有工具调用，处理工具调用
                self._last_had_tool_calls = True
                logger.debug("检测到XML工具调用: %d 个", len(tool_calls))

                # 使用专门的函数移除XML标签，只保留普通文本部分
                assistant_content = remove_xml_tool_calls(response_text, tool_calls)
                assistant_content = assistant_content.strip()

                # 添加助手消息（包含模型的思考文本）
                if assistant_content:
                    messages.append({
                        "role": "assistant",
                        "content": assistant_content,
                    })

                # 处理每个工具调用
                failed_count = 0
                success_count = 0
                for parsed_tool in tool_calls:
                    logger.debug("Processing tool: %s", parsed_tool)

                    # P0 - 重复调用检测
                    if parsed_tool.get("tool_type") == "mcp":
                        tool_name_for_loop = (
                            f"{parsed_tool.get('server_name', '')}."
                            f"{parsed_tool.get('tool_name', '')}"
                        )
                        tool_args_for_loop = parsed_tool.get("arguments", {}) or {}
                    else:
                        # skill_disclosure 也用 skill_name + level 作为签名
                        tool_name_for_loop = (
                            f"skill.{parsed_tool.get('skill_name', '')}"
                            f".{parsed_tool.get('level', 'L2')}"
                        )
                        tool_args_for_loop = {"level": parsed_tool.get("level", "L2")}

                    loop_status, repeat_count = loop_tracker.check(
                        tool_name_for_loop, tool_args_for_loop
                    )
                    if loop_status == "hard":
                        # 硬停止 - 修复 1: 走兜底返回，不抛 500
                        self._hard_stop_reason = "loop"
                        logger.warning(
                            "LoopDetectionTracker 硬阈值触发: %s 连续 %d 次，触发硬停止",
                            tool_name_for_loop, repeat_count,
                        )
                        fallback = self._build_fallback_response(
                            reason="loop",
                            loop_count=loop_count,
                            last_text=assistant_content,
                        )
                        # 把助手文本也写进历史，让 SSE 能正常收尾
                        if assistant_content and (
                            not messages
                            or messages[-1].get("role") != "assistant"
                            or messages[-1].get("content") != assistant_content
                        ):
                            messages.append({
                                "role": "assistant",
                                "content": assistant_content,
                            })
                        return fallback, True, loop_count
                    if loop_status == "soft":
                        # 软提醒 - 修复 3: 改用 user role，仅注入 1 次
                        if not self._loop_remind_injected:
                            self._loop_remind_injected = True
                            self._inject_user_reminder(
                                messages,
                                f"提示：你刚刚连续 {repeat_count} 次以完全相同的参数调用了工具 "
                                f"`{tool_name_for_loop}`。这通常是死循环的征兆，"
                                f"请重新评估：是否需要不同的参数、不同的工具，或者直接结束任务。",
                            )
                        else:
                            logger.debug("LoopDetectionTracker 软提醒已注入过，本次跳过")

                    # 调用工具
                    tool_result = await self._handle_tool_call(parsed_tool)
                    logger.debug("Tool result: %s...", tool_result[:200])

                    # P0 - 工具结果截断
                    tool_result = self._truncate_tool_result(
                        tool_result, max_chars=self.tool_result_max_chars
                    )

                    # P0 - 统计成功 / 失败
                    if '"error"' in tool_result or "'error'" in tool_result:
                        failed_count += 1
                    else:
                        success_count += 1

                    # 添加工具结果消息（流派A：使用tool_result标签）
                    messages.append({
                        "role": "user",
                        "content": f"<tool_result>\n{tool_result}\n</tool_result>",
                    })

                # 关键修复：如果 assistant_content 为空，说明模型只输出了 XML 标签
                # 需要添加工具调用摘要消息，保持消息历史结构完整
                if not assistant_content.strip():
                    tool_summary = []
                    for tc in tool_calls:
                        if tc.get("tool_type") == "mcp":
                            tool_summary.append(
                                f"{tc.get('server_name', '')}.{tc.get('tool_name', '')}"
                            )
                        else:
                            tool_summary.append(f"skill.{tc.get('skill_name', '')}")
                    messages.append({
                        "role": "assistant",
                        "content": f"（已调用工具: {', '.join(tool_summary)}）",
                    })

                # P0 - MistakeTracker 记录本轮
                mistake_tracker.record_turn(failed_count, success_count)
                if mistake_tracker.is_limit_reached():
                    # 修复 1: 走兜底返回，不抛 500
                    self._hard_stop_reason = "mistake"
                    logger.warning(
                        "MistakeTracker 触发: 连续 %d 轮调用工具全部失败，触发硬停止",
                        mistake_tracker.consecutive_failures,
                    )
                    fallback = self._build_fallback_response(
                        reason="mistake",
                        loop_count=loop_count,
                        last_text=assistant_content,
                    )
                    return fallback, True, loop_count

                # 继续下一轮循环
                continue

            # ===== 没有工具调用 =====
            logger.debug(
                "本轮无工具调用，检查结束标志，response_len=%s",
                len(response_text) if response_text else 0,
            )

            # 关键修复：如果响应是错误消息，不添加到消息历史，避免错误累积
            # 只有有效响应才添加到消息历史
            if not is_error_response and response_text:
                messages.append({
                    "role": "assistant",
                    "content": response_text,
                })

            # ===== 修复 2: 条件 A —— 柔性结束 =====
            # 本轮无任何工具调用 AND terminal_tool_required 已被实际调用过
            # => 直接以本轮文本作为最终回答，结束循环
            target_tool = self.task_tracker.get("terminal_tool_required")
            if target_tool and self._check_terminal_tool_called(messages):
                self._terminal_tool_already_called = True
                final_response = response_text.replace(AGENT_LOOP_FINISH_TAG, "").strip()
                logger.debug(
                    "修复 2·条件 A 触发: 本轮无工具调用且 terminal_tool=%s 已调过，"
                    "以本轮文本作为最终回答",
                    target_tool,
                )
                return final_response, False, loop_count

            # ===== 修复 2: 条件 B —— 显式结束 =====
            if AGENT_LOOP_FINISH_TAG in response_text:
                # 如果声明了 terminal_tool 但还没调，修复 3: 注入 1 次 user 提醒
                target = self.task_tracker.get("terminal_tool_required")
                if target and not self._check_terminal_tool_called(messages):
                    if not self._terminal_tool_remind_injected:
                        self._terminal_tool_remind_injected = True
                        logger.warning(
                            "模型尝试结束但 terminal_tool_required=%s 未被调用，"
                            "注入 1 次 user 提醒并继续循环",
                            target,
                        )
                        self._inject_user_reminder(
                            messages,
                            f"系统检测到你声明了任务闭环工具 `{target}`，但它尚未被实际调用。"
                            f"请先调用该工具完成写入，再在该轮回答末尾添加 "
                            f"`</agent_loop_finish>` 结束标志。",
                        )
                    else:
                        # 修复 3: 提醒已注入过，不再重复，继续循环直到 max_agent_loop
                        logger.debug(
                            "修复 3: terminal_tool 提醒已注入过，本次跳过，继续循环",
                        )
                    continue

                # 移除结束标志后返回
                final_response = response_text.replace(AGENT_LOOP_FINISH_TAG, "").strip()
                logger.debug(
                    "修复 2·条件 B 触发: 检测到结束标志 <agent_loop_finish>，"
                    "Agent Loop 正常结束",
                )
                return final_response, False, loop_count

            # ===== 走到这里 = 没有 finish 也没有工具调用 =====
            # 注意：已移除“连续 N 轮无工具调用”计数器护栏。
            # 依靠 max_agent_loop 上限作为唯一轮次控制，让模型有充足机会补工具调用。
            target_tool_for_no_tool = self.task_tracker.get("terminal_tool_required")

            if not target_tool_for_no_tool:
                # 无 terminal_tool_required：空转且 LLM 给出有效文本
                # 视同“模型认为任务完成”（Cline 的 toolCalls.length === 0 语义）
                if not is_error_response and response_text:
                    final_response = response_text.replace(AGENT_LOOP_FINISH_TAG, "").strip()
                    logger.debug(
                        "未检测到工具调用且无 terminal_tool_required，"
                        "以本轮文本作为最终回答"
                    )
                    return final_response, False, loop_count

            # 如果响应是错误消息，走硬停止
            if is_error_response:
                self._hard_stop_reason = "no_tool"
                logger.warning(
                    "检测到错误响应: %s...",
                    (response_text or "")[:100],
                )
                fallback = self._build_fallback_response(
                    reason="no_tool",
                    loop_count=loop_count,
                    last_text=response_text or "",
                )
                return fallback, True, loop_count

            # 继续下一轮循环
            continue

        # ===== 修复 1+6: 达到最大循环次数，走兜底返回 =====
        self._hard_stop_reason = "max_iter"
        logger.warning(
            "达到最大Agent Loop次数 (%d)，触发硬停止"
            "（修复 1：返回 200 兜底响应）",
            max_agent_loop,
        )
        fallback = self._build_fallback_response(
            reason="max_iter",
            loop_count=max_agent_loop,
            last_text=self._last_assistant_text,
        )
        return fallback, True, max_agent_loop

    async def run(self) -> bool:
        """运行Agent客户端。"""
        try:
            await self.initialize()
        except RuntimeError as e:
            logger.error("启动失败: %s", e)
            await self.close()
            return False
        except Exception as e:
            logger.error("初始化未知异常: %s", e, exc_info=True)
            await self.close()
            return False

        app = self.create_app()

        print(f"\n启动服务: http://0.0.0.0:{self.exposure_port}")
        print(f"暴露模型: {self.exposure_model_name}")
        print(f"API Key: {self.exposure_key}")
        print("\n按 Ctrl+C 停止服务\n")

        config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=self.exposure_port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        try:
            await server.serve()
        except OSError as e:
            # 端口占用等系统级错误
            logger.error("uvicorn 启动失败: %s", e)
            return False
        finally:
            await self.close()

        return True


# ============================================================================
# 主函数
# ============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Agent客户端")
    parser.add_argument("--config", "-c", default=CONFIG_FILE, help="配置文件路径")
    parser.add_argument("--port", "-p", type=int, help="覆盖配置文件中的端口")

    args = parser.parse_args()

    try:
        config = load_config(args.config)

        if args.port:
            # exposure 配置可能缺失，给一个兜底 dict 避免 KeyError
            config.setdefault("exposure", {})["port"] = args.port

        client = AgentClient(config)
        asyncio.run(client.run())
    except KeyboardInterrupt:
        # Ctrl+C 时 uvicorn 已 graceful shutdown，这里只补一句提示
        print("\n\n服务已停止")
    except FileNotFoundError as e:
        print(f"\n错误: {e}")
        sys.exit(1)
    except ValueError as e:
        # AgentClient.__init__ 中参数校验失败会抛 ValueError
        print(f"\n配置错误: {e}")
        sys.exit(2)
    except json.JSONDecodeError as e:
        print(f"\n配置文件 JSON 解析失败: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error("运行异常: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
