# MCP 客户端与 LLM 之间的工具交换格式调研报告

> 调研时间：2026-06-17
> 调研人：Mavis
> 关联项目：`standalone_scripts/mcp_client.py`、`mcp_client_research.md`

---

## 一、问题边界：两套协议，两个方向

很多人第一次接触 MCP 时会把两件事混在一起：

- **MCP 协议**（Model Context Protocol）—— 只规定了 **MCP Client 与 MCP Server** 之间怎么对话（JSON-RPC 2.0 over stdio / SSE / StreamableHTTP）
- **LLM Tool Calling 协议** —— 规定 **MCP Client 与大模型** 之间怎么传递工具能力、怎么让模型"回答"中携带工具调用

这两套协议是**完全独立的**。MCP 协议本身**不**告诉 MCP Client 怎么把工具展示给大模型；MCP Client 拿到 `tools/list` 的结果后，要自己决定用什么格式塞给大模型。

所以本次调研要回答的是这**两件事**：

| 方向 | 客户端 → 大模型 | 大模型 → 客户端 |
|------|----------------|----------------|
| 目的 | 把 MCP 工具的能力"告诉"大模型 | 让大模型在回答里表达"我要调哪个工具、传什么参数" |
| 主流格式 | 原生 `tools` 字段（OpenAI / Anthropic 风格） **或** 拼进 System Prompt 的 XML/JSON 文本 | 原生 `tool_calls` 字段（OpenAI） / `tool_use` content block（Anthropic） **或** XML 标签（`<use_mcp_tool>` 等） |
| 解析方 | 大模型自己读 | 客户端用正则 / JSON parser |

---

## 二、演进史：工具调用协议是怎么走到 MCP 的

把这两条主线拉直了看，技术演进大致是这样：

```
阶段 1: 自由 Prompt 阶段 (2023 年 6 月之前)
  → 在 System Prompt 里手写"请输出 {"tool_name": ..., "parameters": {...}} 这样的 JSON"
  → 问题: 模型经常输出格式错误的 JSON，解析器要写很多容错

阶段 2: OpenAI Function Calling (2023 年 6 月)
  → API 引入 tools 字段，每个 tool 用 JSON Schema 描述
  → 模型的 tool_call 是一个结构化字段（不是文本）
  → 稳定性大幅提升，工具调用变成工程级能力

阶段 3: OpenAI Tool Calling (2024 年初)
  → 支持多工具并行调用
  → API 字段名从 functions 统一改成 tools

阶段 4: Anthropic Tool Use (2024 年)
  → Anthropic Messages API 的原生工具调用
  → 字段结构与 OpenAI 不完全兼容（详见第四节）

阶段 5: MCP 协议 (2024 年 11 月, Anthropic)
  → 不解决"怎么调工具"，解决"工具怎么被发现、复用、跨模型迁移"
  → 内部基于 JSON-RPC 2.0，工具定义仍沿用 JSON Schema
  → 2025 年获得 OpenAI、Google、主流 IDE 厂商支持
```

关键洞察：**MCP 没有发明新的工具调用格式**。它只是把"工具定义/调用"在 Client-Server 之间用 JSON-RPC 包了一层，**给大模型的那一面还是各家厂商自己的 tool calling 协议**。所以不同客户端才需要做"格式转换"这件事。

---

## 三、主流 MCP 客户端的真实做法

我重点查了 **Cline**（最透明，源码公开）、**Cherry Studio**、**Chatbox AI**、**Cursor**、**Claude Desktop**、**Continue**。结论是：**做法只分两大流派**。

### 3.1 流派 A：把工具塞进 System Prompt，用 XML 标签回传

**代表：Cline**（也是最值得参考的，因为源码完全公开）

Cline 的做法很激进：**不依赖任何模型原生 tool calling 能力**。它把内置工具 + MCP 工具**全部**描述成 XML 风格的文本，写进 System Prompt；模型也必须用 XML 标签回传工具调用。

#### 3.1.1 工具怎么展示给模型

Cline 的真实 System Prompt（`src/core/prompts/system.ts`，摘自实际抓包）中，对每个工具的描述格式如下：

```text
# Tool: use_mcp_tool
Description: Request to use a tool provided by a connected MCP server.
Each MCP server can provide multiple tools with different capabilities.
Tools have defined input schemas that specify required and optional parameters.

Parameters:
- server_name: (required) The name of the MCP server providing the tool
- tool_name: (required) The name of the tool to execute
- arguments: (required) A JSON object containing the tool's input parameters,
  following the tool's input schema

Usage:
<use_mcp_tool>
<server_name>server name here</server_name>
<tool_name>tool name here</tool_name>
{ "param1": "value1", "param2": "value2" }
</use_mcp_tool>
```

注意几个细节：

1. **所有工具都按统一格式描述**：每个工具有 `Description` / `Parameters` / `Usage` 三段。
2. **每个参数都标 `(required)` 或 `(optional)`** —— 这部分是 Cline 自己从 MCP 返回的 JSON Schema 解析后注入的。
3. **使用示例是用 XML 标签写的** —— 实际上是 Cline 在"教"模型怎么回传调用。
4. **`<arguments>` 里嵌的是 JSON 对象** —— 嵌套 JSON 是允许的。
5. **专门有一个元工具 `use_mcp_tool`** —— 它是模型调用任何 MCP 工具的"入口"，参数里带 `server_name` 区分。

#### 3.1.2 模型怎么回传工具调用

Cline 期望模型输出**完全匹配** Usage 段的 XML：

```xml
<use_mcp_tool>
  <server_name>weather-server</server_name>
  <tool_name>get_forecast</tool_name>
  <arguments>{"city": "San Francisco", "days": 5}</arguments>
</use_mcp_tool>
```

Cline 客户端**用正则解析这段 XML**，提取：
- `server_name` → 路由到哪个 MCP Client 连接
- `tool_name` → 调用哪个工具
- `arguments`（一个 JSON 字符串）→ 反序列化为参数 dict

然后调用 SDK 的 `client.callTool({name, arguments})` 走 JSON-RPC，拿到结果后再以 `<tool_result>` 标签塞回给模型。

#### 3.1.3 Cline 这么干的好处

- **模型无关**：DeepSeek、Qwen、Llama、本地小模型——只要模型能遵循 XML 模板就行，不需要原生 function calling
- **统一调度**：内置工具（读文件、执行命令）和 MCP 工具走完全相同的 XML 协议，调度逻辑只需要一份
- **可观察性强**：所有工具调用都是文本，能在 UI 上直接渲染、修改、复制

#### 3.1.4 Cline 的代价

- **每轮都要把工具描述塞进 System Prompt**（Cline 的 System Prompt 有 47KB 之大）
- **依赖模型的指令遵循能力**——小模型经常漏标签、参数错位
- **解析器要写复杂的容错**（标签被截断、JSON 格式错误、嵌套引号转义等）

### 3.2 流派 B：使用模型原生 Tool Calling，把 MCP 工具转换为各家格式

**代表：Cherry Studio、Chatbox AI、Cursor、Claude Desktop、Continue**

这一派把模型原生 tool calling 能力作为"信使"，由客户端做 MCP 工具定义到厂商 schema 的转换。

#### 3.2.1 Cherry Studio

- 文档明确说"需要搭配支持 Function Call 的模型"
- 在设置里把 MCP Server 的 `tools/list` 结果**转换为 OpenAI 兼容的 `tools` 数组**，传给所选模型
- 如果选的是 Claude 模型，会进一步转换为 Anthropic 的 `tools` + `input_schema` 格式
- 模型的 `tool_calls` 字段返回时，Cherry Studio 解析出 `function.name` 和 `arguments`，再路由到对应的 MCP Server

#### 3.2.2 Chatbox AI

- 闭源，做法与 Cherry Studio 类似
- 内部实现了 OpenAI / Anthropic 两套 schema 的转换层
- MCP 工具调用结果以 `tool` role 的 message 形式回传到对话

#### 3.2.3 Cursor

- 同时支持 Anthropic 原生 `tool_use` 和 OpenAI 兼容的 `tool_calls`
- `mcp.json` 配置的 MCP Server，工具以 `ListToolsRequestSchema` 的方式注册
- 工具调用走 `CallToolRequestSchema` 协议
- Cursor 内部把 MCP 工具和编辑器内建能力（读文件、命令执行等）一起转成模型需要的 schema

#### 3.2.4 Claude Desktop

- Anthropic 官方客户端，**最直接**——直接用 Anthropic Messages API 的原生 `tools` + `input_schema`
- MCP 工具的 JSON Schema 几乎原样塞进 `tools`，因为 Anthropic 自己就是 MCP 的设计者
- 模型的 `tool_use` content block 原样解析，再走 MCP `tools/call`

#### 3.2.5 流派 B 的共同特点

| 步骤 | 客户端做的事 |
|------|-------------|
| 1. 启动时 | 调 `tools/list` 拿到所有 MCP 工具的 JSON Schema |
| 2. 转换 | 把 MCP Schema 转为目标模型厂商的格式（OpenAI `tools` 或 Anthropic `tools` + `input_schema`） |
| 3. 注入 | 把转换后的工具列表作为请求参数的一部分（OpenAI 的 `tools` 字段 / Anthropic 的 `tools` 字段），**不是放在 System Prompt 里** |
| 4. 接收 | 模型返回时，从 `tool_calls` / `tool_use` 里拿到工具名和参数 |
| 5. 调用 | 找到对应的 MCP Server，调 SDK 的 `client.callTool()` |
| 6. 回传 | 把结果按厂商格式回传（OpenAI: 新增 `role: "tool"` 的 message；Anthropic: 新增 `role: "user"` 但 content 是 `tool_result` 块） |

### 3.3 两种流派的对比

| 维度 | 流派 A：System Prompt + XML | 流派 B：原生 Tool Calling |
|------|---------------------------|--------------------------|
| 代表 | Cline、部分小众客户端 | Cherry Studio、Chatbox、Cursor、Claude Desktop、Continue |
| 模型要求 | 任意能遵循指令的模型 | 必须支持原生 tool calling |
| 工具描述位置 | System Prompt（每轮都带） | API 请求的 `tools` 字段（厂商侧处理） |
| 工具调用回传 | XML 标签，客户端正则解析 | 结构化字段，厂商 API 解析 |
| 解析复杂度 | 客户端高（容错、嵌套、转义） | 客户端低（厂商帮你解析） |
| 多工具并行 | 模型一次性输出多个 XML 块 | 模型一次性返回多个 `tool_calls` |
| 流式响应 | 难以做（XML 标签是连续的） | 原生支持，工具调用和文本可交错流式输出 |
| 切换模型成本 | 极低（XML 通用） | 中（不同厂商 schema 要做转换层） |
| 小模型可用 | 可用（只要能遵循指令） | 不可用（无 function calling 能力） |
| Token 消耗 | 高（每轮都带所有工具描述） | 低一点点（厂商侧有上下位缓存，缓存载入的价格是Token的一半，但是现在的模型Token很便宜，差别不大） |

---

## 四、OpenAI 与 Anthropic 工具 Schema 的关键差异

如果你要做流派 B 的转换层，**必须**了解 OpenAI 和 Anthropic 之间的 schema 差异。简单说：**它们不兼容**，不能直接"换个字段名"互通。

### 4.1 顶层结构

**OpenAI：**
```json
{
  "type": "function",
  "function": {
    "name": "get_weather",
    "description": "查询指定城市的天气",
    "parameters": {
      "type": "object",
      "properties": { ... },
      "required": ["city"]
    }
  }
}
```

**Anthropic：**
```json
{
  "name": "get_weather",
  "description": "查询指定城市的天气",
  "input_schema": {
    "type": "object",
    "properties": { ... },
    "required": ["city"]
  }
}
```

差异：
- OpenAI 把工具的元信息和函数签名分了两层（`type: "function"` + `function.name`）
- Anthropic 是平铺的，工具名直接是 `name`
- OpenAI 用 `parameters`，Anthropic 用 `input_schema`

### 4.2 必填字段的处理

| 厂商 | 做法 | 强度 |
|------|------|------|
| OpenAI | 显式 `required` 数组 | 硬约束：模型漏传 → API 返回 400 |
| Anthropic | **没有**统一 `required` 字段；推荐把"必填"写进 `description` | 软约束：靠模型自己理解，必填缺失不在 API 层校验 |

### 4.3 enum 校验

- **OpenAI**：模型生成 enum 之外的值 → API 直接 400
- **Anthropic**：模型可能根据 description 推断出一个语义相近但不在 enum 列表的值，**不会**报错

### 4.4 additionalProperties

- **OpenAI**：支持完整 JSON Schema 语义，`additionalProperties: false` 严格生效
- **Anthropic**：对 `additionalProperties` 的支持有限，有时候会**静默丢弃**未声明字段，而不是报错

### 4.5 description 的权重

- **OpenAI**：description 是元信息，帮助模型理解工具，但**不影响**参数校验
- **Anthropic**：description 是 Schema 的"一等公民"，对工具选择和参数填充的影响非常大

### 4.6 流式响应

- **OpenAI**：流式响应里 `function_call` 分块返回，调用方自己拼接
- **Anthropic**：流式响应里 `content_block` 携带 `tool_use`，需要按 `input_json_delta` 累积参数

### 4.7 转换层实现要点

如果你要在自己的 MCP 客户端里同时支持两家模型（流派 B 的实现），至少要写：

1. **字段名映射**：`parameters` ↔ `input_schema`，外层 `type: "function"` 包装的拆/装
2. **`required` 处理**：从 OpenAI 的 `required` 数组 → 在 Anthropic 的每个必填字段的 description 前加 "(required)"
3. **响应解析分流**：OpenAI 解析 `tool_calls[]`，Anthropic 解析 `content[]` 里 type=`tool_use` 的块
4. **结果回传格式不同**：
   - OpenAI: `{"role": "tool", "tool_call_id": "...", "content": "..."}`
   - Anthropic: `{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "...", "content": "..."}]}`

---

## 五、工具调用结果怎么回传给大模型

调完工具后，结果也要按厂商格式回传。这一步是另一个容易踩坑的点。

### 5.1 OpenAI 风格

```json
{
  "messages": [
    {"role": "user", "content": "北京今天天气怎么样？"},
    {
      "role": "assistant",
      "content": null,
      "tool_calls": [
        {
          "id": "call_abc123",
          "type": "function",
          "function": {
            "name": "get_weather",
            "arguments": "{\"city\": \"北京\"}"
          }
        }
      ]
    },
    {
      "role": "tool",
      "tool_call_id": "call_abc123",
      "content": "{\"temperature\": 18, \"condition\": \"多云\"}"
    },
    {
      "role": "assistant",
      "content": "北京今天 18°C，多云。"
    }
  ]
}
```

注意：`tool_call_id` 必须**精确匹配**上一次 assistant 消息里 `tool_calls[i].id`。

### 5.2 Anthropic 风格

```json
{
  "messages": [
    {"role": "user", "content": "北京今天天气怎么样？"},
    {
      "role": "assistant",
      "content": [
        {"type": "text", "text": "我帮你查一下。"},
        {"type": "tool_use", "id": "toolu_abc123", "name": "get_weather", "input": {"city": "北京"}}
      ]
    },
    {
      "role": "user",
      "content": [
        {"type": "tool_result", "tool_use_id": "toolu_abc123", "content": "{\"temperature\": 18, \"condition\": \"多云\"}"}
      ]
    },
    {
      "role": "assistant",
      "content": [{"type": "text", "text": "北京今天 18°C，多云。"}]
    }
  ]
}
```

注意：Anthropic 把工具结果放在**下一条 user 消息**里，且用 `tool_result` block 包装。

### 5.3 Cline（XML 流派）的回传方式

Cline 把工具结果**作为"用户的下一条消息"**回传给模型，但用 `<tool_result>` 标签包裹：

```xml
<tool_result>
  {"temperature": 18, "condition": "多云"}
</tool_result>
```

下一轮模型继续以 XML 工具调用的方式工作。

### 5.4 结果可以是多种内容类型

MCP 协议规定的工具返回结果是一个**数组**，每个元素有 `type` 字段，常见的有：

- `type: "text"` —— 文本
- `type: "image"` —— 图片（含 base64 数据 + mimeType）
- `type: "resource"` —— 资源引用（需要再调 `resources/read` 拿内容）

模型客户端拿到这些结果后要分别处理：
- text → 直接塞进 `tool`/`tool_result` 的 content
- image → 转换为厂商的多模态格式（OpenAI 的 `image_url` / Anthropic 的 `image` block）
- resource → 二次调用后回传

---

## 六、给你的 `mcp_client.py` 的建议

你的 `mcp_client.py` 当前已经完整实现了"MCP Client ↔ MCP Server"那一段（list/call），这是必要前提。但**离真正"用大模型驱动工具调用"还差一层转换**。基于本次调研，落地时建议这样分层：

```
┌────────────────────────────────────────────────────────────┐
│  LLM Provider Adapter (新增)                                │
│  - 把 MCP tool schema 转为 OpenAI / Anthropic 格式         │
│  - 解析模型返回的 tool_calls / tool_use                      │
│  - 按厂商格式回传 tool_result                               │
└──────────────────────┬─────────────────────────────────────┘
                       │
┌──────────────────────┴─────────────────────────────────────┐
│  Agent Loop (新增)                                          │
│  - 维护 messages 列表                                       │
│  - 调 chat completion，看到 tool_calls 就 dispatch          │
│  - 把 tool_result 塞回 messages，继续下一轮                 │
│  - 直到 stop_reason == end_turn / finish_reason == stop    │
└──────────────────────┬─────────────────────────────────────┘
                       │
┌──────────────────────┴─────────────────────────────────────┐
│  你已有的 MCPClient (本项目)                                │
│  - list_tools / call_tool                                  │
│  - 内部走 JSON-RPC 到 MCP Server                            │
└────────────────────────────────────────────────────────────┘
```

具体要做的三件事：

1. **LLM Provider 抽象层**：定义一个 `LLMProvider` 接口，至少实现 `OpenAIProvider` 和 `AnthropicProvider` 两个适配器，把 MCP 的 `tools/list` 结果转成各家 `tools` 字段，把模型响应里的 `tool_calls` / `tool_use` 抽成统一的 `ToolCallRequest` 数据类。

2. **Agent Loop**：拿到 `ToolCallRequest(server_name, tool_name, arguments)` 后，调用你已有的 `MCPClient.call_tool()`，把结果包成对应厂商的格式（OpenAI 的 `role: "tool"` / Anthropic 的 `tool_result` block），追加进 `messages`，再次请求 LLM，循环直到 LLM 给出最终文本。

3. **配置上**：在 `mcp_servers.json` 旁边加一个 `llm_config.json`，配置 API Key、模型名、是否启用某个 MCP Server。

如果你打算支持"小模型 + Cline 风格"（流派 A），可以加一个 `XmlStyleProvider`，把工具描述拼成 XML System Prompt，模型返回时用正则解析。两条路可以根据模型能力动态切换。

---

## 七、一句话总结

- **MCP 协议只管 Client ↔ Server**，它**不**规定 Client 怎么把工具能力给大模型
- **大模型那一侧用的是各家厂商的 tool calling 协议**（OpenAI 的 `tools` + `tool_calls`、Anthropic 的 `tools` + `tool_use`）
- 主流客户端分两大流派：**Cline 派**用 XML 塞 System Prompt（兼容所有模型），**其他主流派**用原生 tool calling（更标准、效率更高，但要求模型有 function calling 能力）
- OpenAI 和 Anthropic 的 tool schema **不兼容**，要做好转换层（字段名、`required` 处理、回传格式）
- 工具结果回传也按厂商格式来，OpenAI 用 `role: "tool"`，Anthropic 用 `role: "user"` 包裹 `tool_result` block

---

## 八、参考链接

- Cline 源码：`https://github.com/cline/cline`（`src/core/prompts/system.ts`、`src/services/mcp/McpHub.ts`）
- Cline 抓包 prompt 全文（中文社区分析）：`https://blog.csdn.net/...`（关键词"Cline 抓包-prompt 原文"）
- Cherry Studio MCP 文档：`https://docs.cherry-ai.com/advanced-basic/mcp`
- Cursor MCP 扩展实战：`https://juejin.cn/post/...`（关键词"使用 MCP 协议扩展 Cursor 功能"）
- MCP 官方协议规范：`https://modelcontextprotocol.io`
- OpenAI Function Calling：`https://platform.openai.com/docs/guides/function-calling`
- Anthropic Tool Use：`https://docs.anthropic.com/en/docs/tool-use`
- 工具调用演进综述：`https://blog.csdn.net/...`（关键词"function call 到 MCP 技术演进"）
- Anthropic vs OpenAI Schema 差异：`https://www.cnblogs.com/...`（关键词"OpenAI Anthropic Tool Schema JSON 规范差异"）
- MCP + Function Calling 关系：`https://blog.csdn.net/Python_cocola/article/details/147146422`
