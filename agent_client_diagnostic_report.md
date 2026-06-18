# agent_client.py 诊断与改造规划报告

> 调研对象
> - 自研智能体客户端：`C:\Users\Administrator\.minimax-agent-cn\projects\standalone_scripts\agent_client.py`（1383 行），配套 `system_prompt.txt`、`agent_config.json`、三份失败会话日志 `history1/2/3.log`
> - 参考对象：`C:\Users\Administrator\.minimax-agent-cn\projects\cline\`（v3.89.2，2026-06）
> - 失败用例：Cherry Studio 调用 agent1，让其「联网搜索，查询上海交易所的今日新闻，并汇总所有新闻到本地 txt 文件」
> - 失败现象：三次均撞 `max_agent_loop=20` 而终止；Round 1-2 成功发起搜索，Round 3-19 完全停滞

报告由 Mavis 输出（基于代码与日志实测），结论与改造建议直接对应 `agent_client.py` 中的行号，便于按图索骥修改。

---

## 0. 一句话结论

**问题不是 XML 协议选错了（流派 A 的选择本身没问题，Cline 跑得好好的），而是「协议约束的强弱」和「循环状态的硬护栏」两层都没做对**：

1. **协议层**：完全靠模型自觉写正确的 `<use_mcp_tool>` 标签，没有任何结构性兜底（Cline 是 provider native tool calling + `lifecycle.completesRun`）。
2. **循环层**：以「字符串匹配 `</agent_loop_finish>`」作为唯一终止条件，配合脆弱的关键词提醒机制，既不能识别「模型在假性完成」也不能在卡死时主动救场（Cline 是结构化 `toolCalls.length === 0` + `MistakeTracker` + `LoopDetectionTracker`）。
3. **上下文层**：每轮都把全套 system prompt + 17 个 skill 元信息 + 19+ 个 MCP 工具 XML 定义重新塞回请求，到 Round 5 之后模型被自己的协议说明书淹没，注意力迅速溃散（Cline 是 system prompt 35 行、工具走独立 `tools` 字段、auto-compact 主动压缩）。
4. **错误恢复层**：工具结果用 user 角色 + `<tool_result>` 字符串回灌，错误信息没有结构化字段，模型想"自我纠错"也找不到抓手（Cline 用 `role: "tool"` + `isError: true` 的结构化消息）。

下面把每条问题对应到具体代码 + Cline 的做法 + 改造建议，全部串起来。

---

## 1. 失败模式复盘：3 份日志都在同一个地方翻车

### 1.1 失败模式统计

| 指标 | history1 | history2 | history3 |
|---|---|---|---|
| 实际发出 `<use_mcp_tool>` 的轮次 | 1-2（共 2 轮） | 1-2 | 1-2 |
| 后续空转轮次 | 3-19（17 轮） | 3-19 | 3-19 |
| 出现「I'll write the file」「立即写入」类空话轮次 | 16-19 | 16-19 | 16-19 |
| 是否发出 `</agent_loop_finish>` | 否 | 否 | 否 |
| 终止原因 | 撞 `max_agent_loop=20` | 撞 `max_agent_loop=20` | 撞 `max_agent_loop=20` |

三次会话在第 2 轮拿到第一波搜索结果后，从第 3 轮开始模型就完全不再发任何 `<use_mcp_tool>` 块了。第 16 轮之后甚至连工具调用的"语言承诺"都退化成了"让我重新尝试"这种空话。

### 1.2 Round 3 的典型 LLM 输出（取自 history1.log:2614）

```text
<think>
我已经获得了一些上交所的新闻。让我访问上交所官网的热点动态页面，
获取更多新闻。同时让我访问那个具体的新闻页面获取详细内容。
</think>
我已获得一些新闻线索。现在访问上交所的热点动态页面以及重要新闻的详细内容。
```

**问题**：模型只输出"思考 + 一句自然语言承诺"，**完全没有 `<use_mcp_tool>` 块**。客户端解析器拿不到任何工具调用。

### 1.3 Round 16 的典型 LLM 输出（取自 history1.log:9128 附近）

```text
<think>
Let me try writing the file using the create_directory and write_file tools.
</think>
（无任何工具调用）
```

**问题**：模型**知道**要调 `write_file`，但**没把它包成 XML**。脚本里的 `_check_pending_task` 触发了"注意：您还有未完成的任务"提醒（`agent_client.py:1300-1314`），但这条提醒又是 user 角色的纯文本消息，模型再读一遍还是只输出"我立即创建文件"——空话循环。

### 1.4 根因图谱

```
                  ┌──────────────────────────────────────────┐
                  │  失败：撞 max_agent_loop，无 finish 标志 │
                  └────────────────────┬─────────────────────┘
                                       │
            ┌──────────────────────────┼──────────────────────────┐
            │                          │                          │
            ▼                          ▼                          ▼
   ┌─────────────────┐      ┌──────────────────────┐   ┌──────────────────┐
   │ 模型不再发 XML  │      │ 提醒机制反而恶化问题 │   │ 上下文雪崩式膨胀 │
   │ (协议层无兜底)  │      │ (空话循环+空 user)  │   │ (system 重复塞)  │
   └─────────────────┘      └──────────────────────┘   └──────────────────┘
```

---

## 2. Cline 是怎么做的：核心架构对照

Cline 的代码组织（`projects/cline/sdk/packages/`）：
- `@cline/agents` — 无状态 agent 循环主控（`agent-runtime.ts:583-688`）
- `@cline/core` — 会话编排 + 安全/状态（`session-runtime-orchestrator.ts`）
- `@cline/llms` — provider 网关 + AI SDK 适配（`compat.ts`、`ai-sdk.ts`）

### 2.1 工具调用协议：provider-native，不靠字符串

| 维度 | agent_client.py | Cline |
|---|---|---|
| 工具定义位置 | 拼在 system prompt 里（`get_mcp_tools_for_prompt`，`agent_client.py:574-625`） | 独立 `AgentModelRequest.tools` 字段（`agent.ts:189-196`） |
| 工具描述格式 | 自定义 XML 协议 `Usage: <use_mcp_tool>...</use_mcp_tool>`（`agent_client.py:615-622`） | 标准 JSON Schema（`tools/create.ts:5-79`） |
| 模型回传格式 | 期望模型**自觉输出** `<use_mcp_tool>` XML 字符串 | provider 原生 `tool_calls`（OpenAI）或 `tool_use` content block（Anthropic） |
| 工具结果回灌 | `role: "user"` + `<tool_result>...</tool_result>` 字符串（`agent_client.py:1242-1245`） | `role: "tool"` + 结构化 `tool-result` part（`agent-message-codec.ts:186-196`） |
| Schema 校验 | 解析时才崩（`parse_xml_tool_calls`，`agent_client.py:208-277`） | 注册时就抛（`normalizeToolInputInputSchema`，`tools/create.ts:5-79`） |

**关键差异**：Cline 用 provider 原生 tool calling，模型如果想调 `write_file` **必须**返回结构化 `tool_call.function.name="write_file"`+合法 JSON `arguments`。模型嘴上说"I'll call write_file"但不发 tool_call，provider 不会把这句话当作调用——**结构上消灭了"假性完成"**。

我现在的 agent 完全依赖模型自觉写对 XML，这是把协议正确性完全押在模型的服从性上。一不服从就崩。

### 2.2 终止条件：双层硬护栏

Cline 的两层"任务完成"判定（`agent-runtime.ts:625-648` + `:1083-1103`）：

1. **结构层**：`toolCalls.length === 0`（模型本轮没发任何工具调用）→ 直接 `finishRun("completed", ...)`。
2. **能力层**：有 `submit_and_exit` 这种 `lifecycle.completesRun: true` 的工具时，**必须**调用它才会结束；否则每轮注入 reminder 继续循环（`agent-runtime.ts:632-639`）。

agent_client.py 只有一个 `</agent_loop_finish>` 字符串匹配（`process_agent_loop`，`agent_client.py:1278-1282`）。这有三大问题：
- 模型不发就永远不结束
- 模型可以在还没写文件时就发（Round 16 的"我立即写入"如果真带了 finish 也会被接受，**没有任何"必须写完文件"的硬约束**）
- 没有"已完成 task 必须调用 terminal tool"的强约束

### 2.3 错误恢复：三层兜底

Cline 的错误处理是个完整体系（`mistake-tracker.ts:74-151` + `loop-detection.ts`）：

| 机制 | 触发条件 | 行为 |
|---|---|---|
| 单次 tool 错误 | `execute()` 抛异常 | 包装成 `role: "tool"` + `isError: true`，模型能看见并重试（`agent-runtime.ts:1062-1081`） |
| `MistakeTracker` 连续错误 | 连续 6 轮"全失败无成功" | 默认 abort runtime；可配 `continue` + 注入 guidance（`mistake-tracker.ts:106-142`） |
| `LoopDetectionTracker` 重复调用 | 同一 `toolName + input` 软阈值 3 / 硬阈值 5 | 软：注入 recovery notice；硬：走 MistakeTracker abort（`orchestrator.ts:1186-1216`） |
| Hook 强制停止 | `beforeRun/beforeModel/beforeTool` 任一返回 `{ stop: true }` | 抛 `ControlledStopError` 中断（`agent-runtime.ts:1421-1431`） |

agent_client.py 只有一个"连续 3 轮无工具调用就发提醒"（`_check_pending_task` + `reminder_msg`，`agent_client.py:1287-1314`），而且：
- 这条 reminder 是 user 消息，不是结构化指令
- 没有"连续 X 次相同 tool call"的检测
- 没有"连续 X 次同参数 tool call"的检测
- 没有"工具执行失败"的独立计数
- reminder 里的 `_check_pending_task` 用关键词匹配（"搜索" "查询" "新闻" "保存" "写入" "文件" "汇总"），脆弱得一塌糊涂

### 2.4 上下文管理：三道防线

Cline 的上下文管理（`message-builder.ts` + `compaction.ts`）：

| 防线 | 触发 | 处理 |
|---|---|---|
| MessageBuilder（每轮） | 总是 | `tool_result` 截断到 50k 字符；读类工具结果"过期标记"；媒体预算裁剪（`message-builder.ts:28-29, 41, 144-156`） |
| Auto Compact（按需） | `inputTokens > maxInputTokens - reserveTokens`（默认 200k - 16k = 184k 阈值，0.9 比例） | 两种策略：basic 规则化截断 / agentic 让模型自己生成结构化摘要（`compaction.ts:144-183`、`compaction-shared.ts:12-18, 413-447`） |
| Provider 自带 | `maxTokens` 截断 | 网关兜底（`llms/providers/gateway.ts:269-286`） |

最关键的设计：**压缩时强制 turn-start 对齐，绝不切坏 `tool_use`/`tool_result` 对**（`compaction-shared.ts:269-304` 的 `findCutIndex`）。

agent_client.py 完全没有上下文管理：
- `system_prompt.txt` 每次循环都**完整重发**（包含 19+ 工具 XML + 17 个 skill L1 元信息，~31KB），`agent_client.py:917-929`
- `messages` 列表只 append 不裁剪，`agent_client.py:1228-1245`
- `input_context_limit=20000` / `output_context_reserve=20000`（`agent_config.json:4-5`）配置了但**代码里完全没读**（`grep` 一下整个 `agent_client.py` 这两个 key 一次都没出现）
- 模型 200k context 一旦灌满就死锁

### 2.5 系统提示词：极简 + 动态注入

Cline 的默认 system prompt（`shared/src/prompt/system.ts:1-35`）**只有 35 行**：
- 不含任何工具名、参数、schema
- 模板占位符：`{{PLATFORM_NAME}}` `{{CURRENT_DATE}}` `{{CWD}}` `{{CLINE_RULES}}` `{{CLINE_METADATA}}`
- 关键约束只有两行（`system.ts:27-31`）：
  - `Do not indicates you will be using a tool unless you are actually going to use it.`
  - `IMPORTANT: Always includes tool calls in your response until the task is completed. Response without tool calls will considered as completed with final answer.`

agent_client.py 的 system prompt（`build_system_prompt`，`agent_client.py:731-814`）膨胀到 **612 行 ~31KB**：
- L1~L802 文字指令
- L803-806 起：MCP 工具列表（19 个工具，每个 ~30 行 XML 定义）
- L807-812 起：Agent Skills 列表（17 个 skill，每个 ~10 行 L1 元信息）
- 每次请求**整段重新发**

### 2.6 Plan vs Act 模式

Cline 用**工具集差异**而不是 prompt 大改来区分模式（`shared/src/session/runtime-config.ts:3` + `presets.ts:20-126`）：
- `act` 模式：开所有工具
- `plan` 模式：关掉 editor / apply_patch（不能写文件），但保留 read/search/bash
- `yolo` 模式：关 search/webfetch，开 `submit_and_exit`

plan 模式还有一个 `plan_mode_respond` 工具专门用于和用户对话，含 `needs_more_exploration` 逃生口（`PlanModeRespondHandler.ts:49-70`）。

agent_client.py 没有 mode 切换，全靠一段固定的 system prompt。

### 2.7 Checkpoint

Cline 的 checkpoint（`shared/src/types/config.ts:100-166` + `session-versioning-service.ts:128-233`）：
- 默认 git stash 快照
- 可插拔（`createCheckpoint` 是个函数注入）
- 配合 `restore(messages)` 完整恢复 agent 状态（`agent-runtime.ts:441-457`）
- 关键承诺：「`Session state was preserved. Send a new prompt to resume from the latest state.`」（`mistake-tracker.ts:181-182`）

agent_client.py 没有 checkpoint，失败后只能从头跑。

---

## 3. 问题诊断：逐条对应到 agent_client.py 的行号

### 问题 A：协议层无结构性兜底（严重）

**位置**：
- `parse_xml_tool_calls`（`agent_client.py:208-277`）— XML 解析
- `remove_xml_tool_calls`（`agent_client.py:280-322`）— 解析后剥离
- `_handle_tool_call`（`agent_client.py:1030-1078`）

**症状**：Round 3+ 模型输出「I'll call write_file」但没产 `<use_mcp_tool>` 块，解析器返回空 `tool_calls`，脚本就把整段输出当成"模型没工具调用的自由发挥"继续。

**根因**：协议把"工具调用"和"自然语言承诺"混在了同一个 channel（模型的文本输出）里，靠正则去捡。

**Cline 的解法**：
- 用 provider native tool calling（OpenAI `tools`/`tool_calls` 字段、Anthropic `tool_use` block）
- 模型**不可能**用自然语言"调用"工具——必须返回结构化字段
- 解析器读不到结构化字段 = 模型没打算调用，这直接是"任务完成"的信号

### 问题 B：终止条件单薄（严重）

**位置**：
- `process_agent_loop` 的 `AGENT_LOOP_FINISH_TAG` 检测（`agent_client.py:1278-1282`）
- `_check_pending_task` 关键词匹配（`agent_client.py:1096-1140`）
- `_no_tool_call_count` 提醒机制（`agent_client.py:1287-1314`）

**症状**：模型从来不发 `</agent_loop_finish>`，循环只能等 `max_agent_loop=20`。

**根因**：
1. 没有"必须调用 terminal tool"的硬约束（用户只说"汇总到本地文件"——但 agent 没有任何机制强制它必须调 `write_file` 才算完成）
2. reminder 是 user 角色的纯文本，对模型来说和用户追问没区别，模型可以继续空话循环
3. `_check_pending_task` 用硬编码关键词（"搜索" "查询" "新闻" "保存" "写入" "文件" "汇总"）判断任务有没有完成，规则脆弱且只能识别 4-5 种任务类型

**Cline 的解法**：
- 双层判定：`toolCalls.length === 0` 结构层 + `lifecycle.completesRun` 能力层
- 没有 `submit_and_exit` 工具 = 默认 `toolCalls.length === 0` 就结束（最常用）
- 有 `submit_and_exit` 工具 = 必须调用它，否则无限循环 + 注入 reminder

### 问题 C：空 user 消息 + 空 tool 消息污染历史（中等）

**位置**：
- `messages.append({role: "assistant", content: ""})` 当模型只输出 XML 没其他文本时（`agent_client.py:1247-1259`）— 实际插了「（已调用工具: ...）」的摘要，OK
- 工具结果包成 user 角色回灌（`agent_client.py:1242-1245`）

**症状**：每轮 1-2 条 user 消息（tool_result）+ 1 条 assistant 消息（思考 + 工具 XML）+ 1 条 system 消息（完整 system prompt），到 Round 5 之后历史里堆了几十条 `<tool_result>` 字符串，模型注意力被淹没。

**根因**：
- tool_result 是字符串 + user 角色，模型和 OpenAI 都不知道这是"工具返回值"
- OpenAI API 支持 `role: "tool"` 原生字段，能让模型明确知道这是工具结果（参考 Cline `agent-message-codec.ts:67-73`）
- 即便用 user 角色回灌，也应该限制 tool_result 长度（如 Cline 截到 50k 字符）

### 问题 D：上下文管理完全缺失（严重）

**位置**：
- `build_system_prompt`（`agent_client.py:731-814`）— 每次完整重新发
- `messages` 列表只 append 不裁剪（`agent_client.py:1166-1321` 整段循环）
- `agent_config.json:4-5` 配置的 `input_context_limit` / `output_context_reserve` **代码里完全没读**

**症状**：Round 5+ 请求的输入 token 增长到几十万，模型注意力涣散，开始重复"我立即写入"空话。

**Cline 的解法**：
- `MessageBuilder` 每轮截断 tool_result（默认 50k 字符）、标记过期文件
- `Auto Compact` 触发后用 LLM 自身生成结构化摘要（Goal/State/Highlights/Next/Files）
- 切点强制 turn-start 对齐，不切坏 tool_use/tool_result 对

### 问题 E：每轮重发 system prompt 浪费 token（中）

**位置**：
- `build_system_prompt`（`agent_client.py:731-814`）— 612 行完整 system prompt
- `process_agent_loop` 循环里直接复用 `all_messages = [system_msg] + messages`（`agent_client.py:929`）

**症状**：每轮请求多带 ~31KB 文本，Round 1-20 累计浪费 ~600KB 上下文。模型每轮都要重新"读完"工具说明书，注意力被工具 schema 占用。

**Cline 的解法**：
- system prompt 只有 35 行
- 工具走独立 `tools` 字段（OpenAI function calling），**不污染** system
- 工具描述只在注册时计算一次

### 问题 F：错误恢复几乎为零（中等）

**位置**：
- `_handle_tool_call` 内部 try/except（`agent_client.py:1074-1078`）— 只把异常包成 `{"error": "..."}` JSON 返回
- 没有失败计数器
- 没有重复调用检测

**症状**：
- 工具执行失败时，模型看到的就是"一段 JSON 错误字符串塞在 `<tool_result>` 里"，没有 `isError` 标记
- 模型在多轮次中可能重复发起**完全相同**的工具调用（比如连续调 5 次 `web_url_read(sse.com.cn)`），没有任何提示"你已经在干这个了"
- 工具返回的 `TextContent` 等特殊类型，`_serialize_tool_result` 处理逻辑是猜测式（`agent_client.py:1142-1164`）

**Cline 的解法**：
- `MistakeTracker` 连续错误计数（默认上限 6，混合判定：本轮有失败**且**无成功才算错；成功轮自动 reset）
- `LoopDetectionTracker` 同一 `toolName + input` 软阈值 3 / 硬阈值 5
- tool 失败永远走 `role: "tool"` + `isError: true`，模型结构性看见错误

### 问题 G：plan/act 模式缺失（中）

**位置**：无对应实现

**症状**：用户问"帮我做个计划" vs "帮我执行"，agent 表现一致——直接开干。在用户没想清楚前可能造成不可逆操作（写文件、调命令）。

**Cline 的解法**：`act` / `plan` / `yolo` / `zen` 模式 + 工具集动态裁剪 + `plan_mode_respond` 工具。

### 问题 H：没有 checkpoint / 状态恢复（中）

**位置**：无对应实现

**症状**：失败后必须从头跑（重发 system prompt、重跑所有工具调用），长任务代价大。

**Cline 的解法**：git stash 快照 + `restore(messages)` 状态恢复 + 「Send a new prompt to resume」承诺。

### 问题 I：没有 response streaming（轻）

**位置**：`create_app` 的 `/v1/chat/completions` 处理（`agent_client.py:891-966`）— 先跑完整 loop，最后一次性返回 SSE

**症状**：用户在前端要等 loop 完全跑完才能看到输出，30 秒+ 没有任何反馈。Cherry Studio 体验上"卡死"。

**Cline 的解法**：每个 turn 都 stream 到前端，工具执行也有事件流。

### 问题 J：没有 plan-then-act 工作流（轻）

**位置**：system prompt 第 780-789 行的「任务执行原则」（`agent_client.py:780-789`）— 只是个 prompt 提示，没有结构性 plan 阶段

**症状**：模型直接开干，不会先列计划。中等复杂任务容易跑偏（比如本例只搜 1 个数据源，没规划多数据源对比）。

---

## 4. 改造规划：分 4 个阶段

按"风险小→风险大"排列，每阶段都能独立 ship、独立验证。

### 阶段 0：P0 止血（1-2 天，必做）

解决 Round 3+ 的死循环，恢复 agent 可用性。

#### 0.1 引入"未达成任务追踪"硬护栏

**目标**：用结构化状态取代"字符串匹配 finish 标签"。

**实现**：
- 在 `AgentClient.__init__` 增加：
  ```python
  self.task_tracker = {
      "original_query": "",
      "sub_goals": [],            # 拆解后的子目标（可手填或 LLM 拆解）
      "achieved_goals": set(),
      "terminal_tool_required": None,  # 例：用户要求写文件时设为 "filesystem.write_file"
  }
  ```
- 解析用户 query 时（首轮）调用一次 LLM 拆解成 sub_goals（轻量 prompt，几十 token 即可）
- 当某轮检测到 `terminal_tool_required` 没被调用过 + 连续 N 轮无工具调用 → 注入**强结构化** reminder（不是 user 角色，是 system 追加或者 `role: "tool"` 的 error 块）

**对应问题**：B（终止条件单薄）、J（plan-then-act）

#### 0.2 引入"连续无工具调用"的硬截止

**位置**：`process_agent_loop`（`agent_client.py:1166-1321`）

**改造**：
```python
# 替换现有的 _no_tool_call_count 提醒机制
NO_TOOL_CALL_HARD_LIMIT = 2  # 连续 2 轮无工具调用即强制结束
```
- 第 1 次无工具调用且无 finish：注入一次精确 reminder
- 第 2 次：直接 `finishRun("aborted_no_progress", last_response)` 退出
- **不要**在 user 消息里塞提示词，那是空话循环的温床

**对应问题**：B

#### 0.3 工具结果改 `role: "tool"` 或截断

**位置**：`process_agent_loop` 的 tool result append 段（`agent_client.py:1242-1245`）

**改造**：
- 如果 provider 支持 OpenAI 兼容 `role: "tool"`，直接用 `tool_call_id` 关联（Cline 的做法）
- 如果必须用 user 角色，至少加一个 `truncate_tool_result(result, max_chars=50000)` 步骤（`message-builder.ts:28-29`）

**对应问题**：C

#### 0.4 实现 `input_context_limit` / `output_context_reserve` 实际生效

**位置**：`process_agent_loop` 进入循环前

**改造**：
- 每次发请求前用 tokenizer（推荐 `tiktoken` 或 `transformers` 的 AutoTokenizer）算 `len(messages)` token 数
- 超过 `input_context_limit` 就触发简化（先做规则化截断：删除早期 `tool_result`、删除过期的 system 块）
- **不要**先做 LLM 摘要，先做规则化截断

**对应问题**：D

### 阶段 1：P1 健壮性（3-5 天）

#### 1.1 引入 `MistakeTracker` 和 `LoopDetectionTracker`

**对应 Cline**：`mistake-tracker.ts:74-151` + `loop-detection.ts`

**实现**：
```python
class MistakeTracker:
    def __init__(self, max_consecutive=6):
        self.consecutive_failures = 0
        self.max_consecutive = max_consecutive
    
    def record_turn(self, failed_count, success_count):
        if failed_count > 0 and success_count == 0:
            self.consecutive_failures += 1
        elif success_count > 0:
            self.consecutive_failures = 0  # 关键：成功轮自动 reset
    
    def is_limit_reached(self):
        return self.consecutive_failures >= self.max_consecutive

class LoopDetectionTracker:
    def __init__(self, soft=3, hard=5):
        self.recent_signatures = deque(maxlen=10)
        self.soft_threshold = soft
        self.hard_threshold = hard
    
    def check(self, tool_name, tool_args):
        sig = (tool_name, json.dumps(tool_args, sort_keys=True))
        self.recent_signatures.append(sig)
        # 检测连续相同签名次数
        ...
```

**对应问题**：F

#### 1.2 工具定义与 system prompt 分离

**对应 Cline**：`agent.ts:189-196` + `agent-runtime.ts:753-757`

**改造**：
- 短期：把 system prompt 拆成两段
  - `static_prompt`：35 行核心指令（含 `</agent_loop_finish>` 约束、`task_execution_principles`）
  - `dynamic_appendix`：工具列表 + skills 列表，每轮**只发一次**作为独立 user 消息，或者放进 system 但**用 sentinel 标记**让模型知道「这部分不要重复发」
- 中期：直接迁移到 OpenAI `tools` 字段，system prompt 不再含工具 schema

**对应问题**：E

#### 1.3 streaming 改造

**位置**：`create_app` 的 `/v1/chat/completions`（`agent_client.py:891-966`）

**改造**：
- 把 `process_agent_loop` 改成 async generator：每轮 LLM 响应实时 stream 出去
- 工具执行过程也作为 event 推送（`tool_started` / `tool_result` / `text_delta`）
- Cherry Studio 体验会立刻变好（实时看到模型在做什么）

**对应问题**：I

### 阶段 2：P2 协议升级（1-2 周）

#### 2.1 改用 provider native tool calling（流派 B 混合）

**背景**：你已经在 `agent_client_format_research.md` 里详细比较了 A/B 流派。结论是 A 通用但脆弱，B 精确但绑死 model provider。

**建议**：**双协议同时支持**，根据 model capability 自动选择：
- 模型支持 native tool calling（OpenAI / Anthropic） → 用 B 协议，工具走 `tools` 字段，结果走 `role: "tool"`
- 模型只支持文本（部分开源小模型） → 用 A 协议（当前 XML 风格）
- 通过 `agent_config.json` 加 `tool_calling_protocol: "native" | "xml" | "auto"` 字段

**对应问题**：A

#### 2.2 引入 `submit_and_exit` 类终止工具

**对应 Cline**：`extensions/tools/definitions.ts:772-795` 的 `submit_and_exit` + `lifecycle.completesRun: true`

**实现**：
- 在 MCP 层注册一个永远在场的虚拟工具 `submit_final_answer`
- 它的 `input_schema` 只接受 `{ "answer": "最终答案文本", "evidence_paths": ["已写入的文件路径"] }`
- 在 `lifecycle` 元数据里标 `completesRun: true`
- 启动时自动设置 `completionPolicy: { requireCompletionTool: true }`
- 改造 `process_agent_loop`：检测到 `submit_final_answer` 的 tool_call + result → 提取 `answer` 字段，结束 loop

**对应问题**：B

#### 2.3 渐进式 Skills 披露的实际生效

**当前状态**：system prompt 列了 17 个 skill 的 L1 元信息，但**模型从未在 3 次失败中调用过 `<skill_disclosure>`**——估计模型压根没把这个 XML 协议当回事。

**改造**：
- Skill 列表也搬到 system prompt **外部**（第一轮时作为 user 消息呈现）
- 简化 `<skill_disclosure>` 协议：只接受 L2，L3 走"告诉我该读哪个 reference 文档"
- 加一个简短的"Skill 使用规则"说明

**对应问题**：A（协议太复杂也是问题）

### 阶段 3：P3 高级特性（可选）

#### 3.1 plan/act 模式切换

参考 Cline `runtime-config.ts:3` + `presets.ts:20-126`：

- `/v1/chat/completions` 增加 `mode: "plan" | "act"` 参数
- plan 模式：system prompt 注入"先列计划，不要写文件"，并在工具集里**临时屏蔽** `write_file` / `edit_file` / shell command
- 切换到 act 模式时恢复

#### 3.2 Checkpoint（git stash 风格）

参考 Cline `session-versioning-service.ts:128-233`：

- 每次 root agent run 开始时记录 git HEAD（或自定义快照）
- 失败 / 中断时提供 `/v1/resume` 端点，恢复 messages 和 workspace 状态

#### 3.3 Auto Compact

参考 Cline `compaction.ts:144-183`：

- 当 `input_tokens > max_input - reserve` 时触发
- 两种模式：basic 规则化截断 / agentic 让模型自己生成结构化摘要
- 切点必须 turn-start 对齐

---

## 5. 优先级矩阵

| 问题 | 严重度 | 改造阶段 | 工作量 | 见效 |
|---|---|---|---|---|
| A 协议无兜底 | P0 | 阶段 2.1 | 1-2 周 | 高 |
| B 终止条件单薄 | P0 | 阶段 0.1-0.2 | 1-2 天 | 立竿见影 |
| C 空消息污染 | P1 | 阶段 0.3 | 0.5 天 | 中 |
| D 上下文管理缺失 | P0 | 阶段 0.4 + 阶段 3.3 | 2-3 天 | 立竿见影 |
| E system prompt 膨胀 | P1 | 阶段 1.2 | 1 天 | 中 |
| F 错误恢复弱 | P1 | 阶段 1.1 | 1-2 天 | 中 |
| G 无 plan/act | P2 | 阶段 3.1 | 3-5 天 | 体验提升 |
| H 无 checkpoint | P2 | 阶段 3.2 | 3-5 天 | 长任务受益 |
| I 无 streaming | P1 | 阶段 1.3 | 1-2 天 | 体验提升 |
| J 无 plan-then-act | P1 | 阶段 0.1 | 已含 | 中 |

**最小可用修复（仅阶段 0）预计 1-2 天**，能直接解决当前 Round 3+ 死循环问题，建议**立即动手**。

---

## 6. 关键代码位置速查

### standalone_scripts
- `agent_client.py:208-277` — `parse_xml_tool_calls`（协议解析）
- `agent_client.py:574-625` — `get_mcp_tools_for_prompt`（工具 schema 进 prompt）
- `agent_client.py:731-814` — `build_system_prompt`（~31KB 巨型 prompt）
- `agent_client.py:917-929` — `system_msg` 注入（每轮重发）
- `agent_client.py:1096-1140` — `_check_pending_task`（脆弱关键词匹配）
- `agent_client.py:1166-1321` — `process_agent_loop`（主循环）
- `agent_client.py:1242-1245` — tool_result user 角色回灌
- `agent_client.py:1278-1282` — `</agent_loop_finish>` 字符串检测
- `agent_client.py:1287-1314` — `_no_tool_call_count` 提醒机制
- `agent_config.json:4-5` — `input_context_limit` / `output_context_reserve`（**未生效**）

### Cline 参考
- `sdk/packages/agents/src/agent-runtime.ts:583-688` — 主 while 循环
- `sdk/packages/agents/src/agent-runtime.ts:511-547` — `getRequiredCompletionToolNames` / `getCompletionToolReminderMessage`
- `sdk/packages/agents/src/agent-runtime.ts:625-648` — 「无 tool call = 完成」分支
- `sdk/packages/agents/src/agent-runtime.ts:745-979` — `generateAssistantMessage`（每轮请求构造）
- `sdk/packages/agents/src/agent-runtime.ts:1062-1320` — `executeToolCalls`（含 try/catch 包 `isError`）
- `sdk/packages/agents/src/agent-runtime.ts:1083-1103` — `findCompletingToolMessage`（`completesRun` 早停）
- `sdk/packages/shared/src/prompt/system.ts:1-35` — 35 行 system prompt
- `sdk/packages/shared/src/agent.ts:189-196` — `AgentModelRequest.tools` 独立字段
- `sdk/packages/shared/src/tools/create.ts:5-79` — `normalizeToolInputSchema`（注册时校验）
- `sdk/packages/core/src/runtime/safety/mistake-tracker.ts:74-151` — `MistakeTracker`
- `sdk/packages/core/src/runtime/safety/loop-detection.ts` — `LoopDetectionTracker`
- `sdk/packages/core/src/extensions/context/compaction.ts:144-183` — Auto Compact 触发
- `sdk/packages/core/src/extensions/context/compaction-shared.ts:269-304` — `findCutIndex`（turn-start 对齐）
- `sdk/packages/core/src/session/services/message-builder.ts:64-115` — 消息预处理（截断、过期、媒体预算）
- `sdk/packages/core/src/extensions/tools/definitions.ts:772-795` — `submit_and_exit`（带 `completesRun: true`）
- `sdk/packages/core/src/extensions/tools/presets.ts:20-126` — act/plan/yolo/zen/search/minimal 预设
- `sdk/packages/shared/src/session/runtime-config.ts:3` — `AgentMode` 枚举
- `sdk/packages/core/src/session/session-versioning-service.ts:128-233` — Checkpoint 恢复

---

## 7. 后续验证清单

完成阶段 0 后，用以下场景回归测试：

1. **原失败用例**（必过）：Cherry Studio 调 agent1，"联网搜索上海交易所今日新闻，汇总到本地 txt"——期望 Round 5 内完成
2. **空话循环注入**（必过）：伪造一个 LLM 让它连续 3 轮输出"我立即写入"——期望第 2-3 轮硬截止
3. **上下文超限**（必过）：构造一个 30 轮的长任务——期望 Round 10+ 触发截断/压缩，loop 不死
4. **工具重复调用**（必过）：让 LLM 连续调 5 次相同参数的 `web_url_read`——期望第 3 次注入 reminder，第 5 次 abort
5. **streaming**（体验）：Cherry Studio 端能实时看到"模型在思考 / 工具在执行"的事件流

完成阶段 1 后追加：
6. **混合错误**：第 3 轮故意让一个工具返回错误——期望 LLM 第 4 轮能看到 `isError=true` 并重试
7. **terminal tool**：让 LLM 必须调用 `submit_final_answer` 才算完成——期望漏调时持续 reminder

完成阶段 2 后追加：
8. **native tool calling**：用一个支持 OpenAI `tools` 字段的模型——期望走 B 协议，系统 prompt 不含工具
9. **XML 协议降级**：用一个只支持文本的模型——期望走 A 协议（兼容老路径）

---

## 8. 一句话总结

**失败的根因不是 XML 协议选错，而是「协议正确性完全押在模型的服从性」+「循环没有任何结构性硬护栏」**。Cline 用 provider native tool calling（结构上消灭"假性完成"）+ 双层终止条件（`toolCalls.length === 0` + `lifecycle.completesRun`）+ 三层错误恢复（Mistake / Loop Detection / Hook）+ Auto Compact 上下文压缩，给了完整的工程化护栏。阶段 0 改造（1-2 天）就能让 agent 走出当前死循环，建议立刻动手。
