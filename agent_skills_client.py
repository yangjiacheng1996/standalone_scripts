'''
# Agent Skills 开发指南：客户端与服务端设计

> 本报告深入解析 Agent Skills 的官方项目、目录结构规范，并给出完整的客户端开发示例，重点阐述渐进式披露（Progressive Disclosure）机制的实现。

---

## 一、官方项目与规范

### 1.1 核心规范与官方仓库

Agent Skills 作为开放标准，有两个关键官方项目：

| 项目 | 仓库地址 | 说明 |
|------|---------|------|
| **规范组织** | [github.com/agentskills/agentskills](https://github.com/agentskills/agentskills) | 维护 Agent Skills 开放规范、官方文档、skills-ref 参考实现库 |
| **官方示例** | [github.com/anthropics/skills](https://github.com/anthropics/skills) | Anthropic 官方发布的 16+ 个示例 Skills，覆盖文档处理、创意设计、开发工具等 |
| **规范文档** | [agentskills.io/specification](https://agentskills.io/specification) | Agent Skills 格式规范的权威参考 |
| **skills-ref** | [agentskills/agentskills/tree/main/skills-ref](https://github.com/agentskills/agentskills/tree/main/skills-ref) | Python 参考实现库，用于 Skills 解析、验证、Prompt 生成 |

```
# 安装 skills-ref Python 包（客户端开发可直接引用）
pip install skills-ref
# 或从源码安装
git clone https://github.com/agentskills/agentskills.git
cd agentskills/skills-ref && pip install -e .
```

### 1.2 官方示例 Skills 仓库结构

```
anthropics/skills/
├── skills/                      # 官方示例 Skills 集合
│   ├── docx/                    # Word 文档处理
│   ├── pdf/                     # PDF 处理
│   ├── pptx/                    # PowerPoint 处理
│   ├── xlsx/                    # Excel 数据分析
│   ├── algorithmic-art/         # 算法艺术生成
│   ├── canvas-design/           # Canvas 设计
│   ├── slack-gif-creator/       # Slack GIF 创建
│   ├── webapp-testing/          # Web 应用测试
│   ├── mcp-builder/             # MCP 服务器开发
│   ├── artifacts-builder/       # React 组件构建
│   └── skill-creator/           # 技能创建指南（元技能）
├── spec/                        # 规范文档
├── template/                    # 技能模板
├── AGENTS.md                    # Agent 配置
├── CLAUDE.md                    # Claude Code 集成说明
└── README.md                    # 项目说明
```

---

## 二、Skill 目录结构规范

根据 [agentskills.io/specification](https://agentskills.io/specification) 官方规范，一个标准 Skill 的目录结构如下：

```
skill-name/                      # 技能目录名必须与 name 字段匹配（小写 + 连字符）
├── SKILL.md                      # 【必需】核心文件：YAML frontmatter + Markdown 指令
├── scripts/                     # 【可选】可执行脚本（Python/Bash/JS 等）
├── references/                  # 【可选】参考文档（按需加载）
│   ├── REFERENCE.md             # 技术参考文档
│   ├── FORMS.md                # 表单模板或数据结构
│   └── *.md                    # 其他领域文档
├── assets/                      # 【可选】静态资源（模板、图片、数据文件）
│   ├── templates/              # 文档模板
│   └── images/                 # 示例图片
└── ...                          # 可添加任意辅助文件
```

### 2.1 SKILL.md 文件格式

`SKILL.md` 是每个 Skill 的核心文件，**必须**包含 YAML frontmatter（前置元数据），其后跟随 Markdown 格式的指令正文。

#### YAML Frontmatter 字段规范

| 字段 | 必需 | 约束 | 说明 |
|------|------|------|------|
| `name` | 是 | 最多 64 字符；仅小写字母、数字、连字符；不能以连字符开头/结尾；不能有连续连字符 | 技能标识符，必须与父目录名一致 |
| `description` | 是 | 最多 1024 字符；非空 | **核心触发机制**：描述技能功能和何时使用 |
| `license` | 否 | 许可证名称或引用捆绑许可证文件名 | 指定许可证 |
| `compatibility` | 否 | 最多 500 字符 | 环境要求（目标产品、系统包、网络访问等） |
| `metadata` | 否 | 任意键值映射 | 扩展元数据（author、version 等） |
| `allowed-tools` | 否 | 空格分隔的预批准工具列表 | 实验性功能 |

#### SKILL.md 示例

```markdown
---
name: pdf-processing
description: 提取 PDF 文本和表格、填写表单、合并文件。当处理 PDF 文档，或用户提到 PDF、表单、文档提取时使用。
version: "1.0"
metadata:
  author: example-org
---
# PDF 处理专家

## 使用时机
当用户需要处理 PDF 文件时使用本技能。

## 如何提取文本
1. 使用 pdfplumber 进行文本提取
2. 处理表格时使用 pdfplumber 的 table 功能
3. 处理表单时使用 pdftk 或 PyPDF2

## 如何填写表单
参考 [表单填写指南](references/FORMS.md)

## 常见问题
- 加密 PDF 需要先用 qpdf 解密
- 扫描版 PDF 需要先进行 OCR 处理
```

### 2.2 各目录用途说明

| 目录 | 用途 | 何时包含 | 加载方式 |
|------|------|---------|---------|
| **SKILL.md** | 核心指令文件 | 必须 | 技能被激活时加载 |
| **scripts/** | 可执行代码 | 重复性代码、需要确定性执行的逻辑 | 按需执行（不加载进上下文） |
| **references/** | 参考文档 | 详细的 API 文档、领域知识、模板说明 | 按需加载到上下文 |
| **assets/** | 静态资源 | 模板文件、图片、图标、示例数据 | 输出时引用，不加载进上下文 |

**重要约束**：
- 避免深度嵌套的引用链，文件引用应保持在 SKILL.md **一层深度以内**
- 大型参考文件（>300 行）应在顶部添加目录
- 技能**不应**包含 README.md、INSTALLATION_GUIDE.md 等辅助文档

---

## 三、渐进式披露机制（核心设计）

渐进式披露是 Agent Skills 的**核心技术特性**，通过分层加载机制解决上下文膨胀问题。

### 3.1 三层加载架构

| 层级 | 加载内容 | Token 消耗 | 加载时机 | 设计目的 |
|------|---------|-----------|---------|---------|
| **L1 元数据** | name + description | ~100 tokens | **始终加载** | 供模型路由决策与意图识别 |
| **L2 指令** | SKILL.md 正文 | <5000 tokens | **技能被激活后加载** | 定义具体业务逻辑与 SOP |
| **L3 资源** | scripts/、references/、assets/ | 按需 | **条件触发时加载** | 提供领域知识或执行副作用 |

```
启动时 (Always-On)
┌─────────────────────────────────────────────────────────────┐
│  <available_skills>                                        │
│    <skill>                                                 │
│      <name>pdf-processing</name>                            │
│      <description>Extract PDF text, fill forms...           │
│    </skill>                                                │
│    <skill>                                                 │
│      <name>data-analysis</name>                             │
│      <description>Analyze datasets, generate charts...     │
│    </skill>                                                │
│  </available_skills>                                       │
└─────────────────────────────────────────────────────────────┘
                               ↓ 模型判断需要使用某个 Skill
                               ↓ 加载完整 SKILL.md 正文（~5000 tokens）
                               ↓ 按需引用 references/ 中的文档或执行 scripts/
```

### 3.2 渐进式披露的优势

1. **上下文高效**：模型启动时仅需 ~100 tokens 即可知道所有可用技能
2. **精准触发**：description 字段精确描述触发条件，模型据此判断是否需要激活
3. **可扩展性**：可同时"掌握"数十甚至上百个技能，而不会上下文过载
4. **Token 节省**：实测可将长链条业务流程的 Token 消耗降低 60%-80%

### 3.3 设计与编写建议

| 层级 | 建议 |
|------|------|
| **description** | 包含技能功能 + 使用场景 + 具体触发条件（用数字编号列出场景）；长度 50-200 词 |
| **SKILL.md body** | 保持 <500 行、<5000 词；核心流程保留在 body，变体细节移到 references/ |
| **references/** | 只放必要的文档；大文件（>100 行）添加 grep 搜索模式；避免与 body 重复 |
| **scripts/** | 先测试确保无 bug；脚本可执行但不加载进上下文（Token 高效） |

---

## 四、客户端开发示例

### 4.1 系统架构设计

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Agent Client                                   │
├─────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                   │
│  │  Skill     │    │  Skill     │    │  Skill     │   ...              │
│  │  Loader    │    │  Matcher   │    │  Executor  │                   │
│  └─────────────┘    └─────────────┘    └─────────────┘                   │
│         ↓                 ↓                ↓                              │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    Progressive Disclosure Engine                  │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │   │
│  │  │ L1 Index │→│ L2 Load  │→│ L3 Ref   │→│ Execute  │             │   │
│  │  │ (metadata)│ │ (SKILL.md)│ │ (files) │  │ (scripts)│             │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                              ↓                                           │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    Agent Prompt Builder                            │   │
│  │  <available_skills> + activated skill content + user request      │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────────────────┘
                                     ↓
                          ┌─────────────────────┐
                          │   LLM Model          │
                          │  (上下文窗口)        │
                          └─────────────────────┘
```

---

## 五、最佳实践总结

### 5.1 客户端开发要点

| 阶段 | 实现要点 |
|------|---------|
| **初始化** | 启动时仅扫描目录并解析 frontmatter 的 name + description；使用 `skills-ref` 库的 `read_properties()` 和 `to_prompt()` |
| **元数据层** | 生成 `<available_skills>` XML；每个 skill ~50-100 tokens |
| **指令层** | 技能被激活时才加载完整 SKILL.md；使用 LRU 缓存避免重复读取 |
| **资源层** | 按需加载 references/ 中的文档；大文件实现流式读取 |
| **脚本执行** | 在沙箱环境中执行 scripts/；记录执行日志和输出 |

### 5.2 技能编写要点

| 层级 | 编写建议 |
|------|---------|
| **description** | 必须包含：技能功能 + 何时使用 + 具体触发条件（数字编号场景） |
| **SKILL.md body** | 保持 <500 行；使用命令式动词；提供具体示例 |
| **references/** | 只放必要文档；大文件添加目录和 grep 模式；避免与 body 重复 |
| **scripts/** | 先测试确保无 bug；添加错误处理；脚本可执行但不加载进上下文 |

### 5.3 性能优化建议

1. **元数据缓存**：启动时扫描一次并缓存，避免重复解析
2. **内容缓存**：L2 和 L3 内容使用 LRU 缓存
3. **延迟加载**：references/ 仅在 SKILL.md 中引用时才加载
4. **脚本隔离**：scripts/ 在独立进程或容器中执行，避免污染主进程
5. **连接池**：HTTP 客户端使用连接池复用连接

---

## 六、参考资料

| 资源 | 链接 |
|------|------|
| 官方规范 | https://agentskills.io/specification |
| 规范组织仓库 | https://github.com/agentskills/agentskills |
| Anthropic 官方 Skills | https://github.com/anthropics/skills |
| skills-ref Python 库 | https://github.com/agentskills/agentskills/tree/main/skills-ref |
| Anthropic 官方博客 | https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills |

---

*本报告生成时间：2026-06-04*

以上是我使用MiniMax agent类小龙虾产品生成的 Agent Skill客户端开发指南。
我已经执行了 git clone https://github.com/agentskills/agentskills.git ，项目就放在本项目根目录中，请你重点阅读一下几个文件：
1. agentskills/skills-ref/src/skills_ref/cli.py
2. agentskills/skills-ref/src/skills_ref/errors.py
3. agentskills/skills-ref/src/skills_ref/models.py
4. agentskills/skills-ref/src/skills_ref/parser.py
5. agentskills/skills-ref/src/skills_ref/prompt.py
6. agentskills/skills-ref/src/skills_ref/validator.py

这六个文件加起来只有不到2000行代码，所以在开发Agent Skill客户端之前，请你阅读这六个文件的全部代码。
我不希望直接使用skills_ref库来调用skill。因为官方项目的变动、删除会影响到我的脚本可用性；代码量不大，完全可以自己实现；避免开源协议纠纷；版权自主可控。
现在开始开发，结合上述小龙虾生成的开发指南，以及我提供的skills_ref相关代码，开发一个Agent Skill命令行客户端，这个客户端拥有官方skills_ref全部功能，且可以渐进式披露。
不需要测试，编写完第一版后我会阅读代码并手动测试。
将代码追加写到本文件下方，不要破坏这个开发计划。
'''

"""
Agent Skills 客户端库
=====================

一个完整的 Agent Skills 客户端实现，支持渐进式披露（Progressive Disclosure）机制。
提供与官方 skills-ref 库相同的功能，且可以独立使用。

主要功能：
- 解析 SKILL.md 文件的 YAML frontmatter
- 验证 Skill 目录结构和内容
- 生成 <available_skills> XML 提示块
- 支持三层渐进式披露（L1元数据、L2指令、L3资源）
- CLI 命令行工具

# 依赖库
pyyaml
"""



import html
import json
import os
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml


# ============================================================================
# 异常类 (与官方 skills-ref 兼容)
# ============================================================================

class SkillError(Exception):
    """所有 Skill 相关异常的基类。"""
    pass


class ParseError(SkillError):
    """SKILL.md 解析失败时抛出。"""
    pass


class ValidationError(SkillError):
    """Skill 属性无效时抛出。
    
    属性:
        errors: 验证错误消息列表（可能只包含一条）
    """
    def __init__(self, message: str, errors: list[str] | None = None):
        super().__init__(message)
        self.errors = errors if errors is not None else [message]


# ============================================================================
# 数据模型
# ============================================================================

@dataclass
class SkillProperties:
    """从 Skill 的 SKILL.md frontmatter 解析的属性。
    
    属性:
        name: kebab-case 格式的 Skill 名称（必需）
        description: Skill 功能及模型何时使用的描述（必需）
        license: Skill 的许可证（可选）
        compatibility: Skill 的兼容性信息（可选）
        allowed_tools: Skill 需要的工具模式（可选，实验性）
        metadata: 客户端特定属性的键值对（默认为空字典）
    """
    name: str
    description: str
    license: Optional[str] = None
    compatibility: Optional[str] = None
    allowed_tools: Optional[str] = None
    metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """转换为字典，排除 None 值。"""
        result = {"name": self.name, "description": self.description}
        if self.license is not None:
            result["license"] = self.license
        if self.compatibility is not None:
            result["compatibility"] = self.compatibility
        if self.allowed_tools is not None:
            result["allowed-tools"] = self.allowed_tools
        if self.metadata:
            result["metadata"] = self.metadata
        return result


class DisclosureLevel(Enum):
    """渐进式披露的层级枚举。"""
    L1_METADATA = "L1"  # 元数据层：name + description（始终加载）
    L2_INSTRUCTION = "L2"  # 指令层：SKILL.md 正文（技能激活后加载）
    L3_RESOURCE = "L3"  # 资源层：scripts/、references/、assets/（按需加载）


@dataclass
class Skill:
    """完整的 Skill 对象，包含所有层级的内容。"""
    path: Path
    properties: SkillProperties
    body: str = ""  # SKILL.md 正文
    references: dict[str, str] = field(default_factory=dict)  # 文件名 -> 内容
    scripts: dict[str, Path] = field(default_factory=dict)  # 脚本名 -> 路径
    assets: dict[str, Path] = field(default_factory=dict)  # 资产名 -> 路径
    location: Optional[Path] = None  # SKILL.md 文件路径


# ============================================================================
# 解析器模块
# ============================================================================

# 允许的 frontmatter 字段
ALLOWED_FIELDS = {
    "name",
    "description",
    "license",
    "allowed-tools",
    "metadata",
    "compatibility",
}

# 验证约束
MAX_SKILL_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
MAX_COMPATIBILITY_LENGTH = 500


def find_skill_md(skill_dir: Path) -> Optional[Path]:
    """在 Skill 目录中查找 SKILL.md 文件。
    
    优先使用 SKILL.md（大写），但也接受 skill.md（小写）。
    
    参数:
        skill_dir: Skill 目录的路径
        
    返回:
        SKILL.md 文件的路径，如果未找到则返回 None
    """
    for name in ("SKILL.md", "skill.md"):
        path = skill_dir / name
        if path.exists():
            return path
    return None


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """解析 SKILL.md 内容的 YAML frontmatter。
    
    参数:
        content: SKILL.md 文件的原始内容
        
    返回:
        (元数据字典, markdown 正文) 的元组
        
    抛出:
        ParseError: 如果 frontmatter 缺失或无效
    """
    if not content.startswith("---"):
        raise ParseError("SKILL.md must start with YAML frontmatter (---)")

    parts = content.split("---", 2)
    if len(parts) < 3:
        raise ParseError("SKILL.md frontmatter not properly closed with ---")

    frontmatter_str = parts[1]
    body = parts[2].strip()

    # 使用 pyyaml 解析 YAML frontmatter
    try:
        metadata = yaml.safe_load(frontmatter_str)
    except yaml.YAMLError as e:
        raise ParseError(f"Invalid YAML in frontmatter: {e}")

    if metadata is None:
        metadata = {}

    if not isinstance(metadata, dict):
        raise ParseError("SKILL.md frontmatter must be a YAML mapping")

    # 处理 metadata 字段中的嵌套字典
    if "metadata" in metadata and isinstance(metadata["metadata"], dict):
        metadata["metadata"] = {str(k): str(v) for k, v in metadata["metadata"].items()}

    return metadata, body


def read_properties(skill_dir: Path) -> SkillProperties:
    """从 SKILL.md frontmatter 读取 Skill 属性。
    
    此函数解析 frontmatter 并返回属性。
    它不执行完整验证。如需验证，请使用 validate()。
    
    参数:
        skill_dir: Skill 目录的路径
        
    返回:
        包含解析元数据的 SkillProperties
        
    抛出:
        ParseError: 如果 SKILL.md 缺失或 YAML 无效
        ValidationError: 如果必需字段（name, description）缺失
    """
    skill_dir = Path(skill_dir)
    skill_md = find_skill_md(skill_dir)

    if skill_md is None:
        raise ParseError(f"SKILL.md not found in {skill_dir}")

    content = skill_md.read_text(encoding='utf-8')
    metadata, _ = parse_frontmatter(content)

    if "name" not in metadata:
        raise ValidationError("Missing required field in frontmatter: name")
    if "description" not in metadata:
        raise ValidationError("Missing required field in frontmatter: description")

    name = metadata["name"]
    description = metadata["description"]

    if not isinstance(name, str) or not name.strip():
        raise ValidationError("Field 'name' must be a non-empty string")
    if not isinstance(description, str) or not description.strip():
        raise ValidationError("Field 'description' must be a non-empty string")

    # 处理 metadata 字典
    metadata_dict = {}
    if "metadata" in metadata and isinstance(metadata["metadata"], dict):
        metadata_dict = {str(k): str(v) for k, v in metadata["metadata"].items()}

    return SkillProperties(
        name=name.strip(),
        description=description.strip(),
        license=metadata.get("license"),
        compatibility=metadata.get("compatibility"),
        allowed_tools=metadata.get("allowed-tools"),
        metadata=metadata_dict,
    )


def read_skill_body(skill_dir: Path) -> str:
    """读取 SKILL.md 的正文内容（不含 frontmatter）。"""
    skill_dir = Path(skill_dir)
    skill_md = find_skill_md(skill_dir)
    
    if skill_md is None:
        raise ParseError(f"SKILL.md not found in {skill_dir}")
    
    content = skill_md.read_text(encoding='utf-8')
    _, body = parse_frontmatter(content)
    return body


# ============================================================================
# 验证器模块
# ============================================================================

def _validate_name(name: str, skill_dir: Path) -> list[str]:
    """验证 Skill 名称格式和目录匹配。
    
    Skill 名称支持国际化字符（Unicode 字母）加上连字符。
    名称必须小写，不能以连字符开头/结尾。
    """
    errors = []

    if not name or not isinstance(name, str) or not name.strip():
        errors.append("Field 'name' must be a non-empty string")
        return errors

    name = unicodedata.normalize("NFKC", name.strip())

    if len(name) > MAX_SKILL_NAME_LENGTH:
        errors.append(
            f"Skill name '{name}' exceeds {MAX_SKILL_NAME_LENGTH} character limit "
            f"({len(name)} chars)"
        )

    if name != name.lower():
        errors.append(f"Skill name '{name}' must be lowercase")

    if name.startswith("-") or name.endswith("-"):
        errors.append("Skill name cannot start or end with a hyphen")

    if "--" in name:
        errors.append("Skill name cannot contain consecutive hyphens")

    if not all(c.isalnum() or c == "-" for c in name):
        errors.append(
            f"Skill name '{name}' contains invalid characters. "
            "Only letters, digits, and hyphens are allowed."
        )

    if skill_dir:
        dir_name = unicodedata.normalize("NFKC", skill_dir.name)
        if dir_name != name:
            errors.append(
                f"Directory name '{skill_dir.name}' must match skill name '{name}'"
            )

    return errors


def _validate_description(description: str) -> list[str]:
    """验证描述格式。"""
    errors = []

    if not description or not isinstance(description, str) or not description.strip():
        errors.append("Field 'description' must be a non-empty string")
        return errors

    if len(description) > MAX_DESCRIPTION_LENGTH:
        errors.append(
            f"Description exceeds {MAX_DESCRIPTION_LENGTH} character limit "
            f"({len(description)} chars)"
        )

    return errors


def _validate_compatibility(compatibility: str) -> list[str]:
    """验证兼容性格式。"""
    errors = []

    if not isinstance(compatibility, str):
        errors.append("Field 'compatibility' must be a string")
        return errors

    if len(compatibility) > MAX_COMPATIBILITY_LENGTH:
        errors.append(
            f"Compatibility exceeds {MAX_COMPATIBILITY_LENGTH} character limit "
            f"({len(compatibility)} chars)"
        )

    return errors


def _validate_metadata_fields(metadata: dict) -> list[str]:
    """验证只存在允许的字段。"""
    errors = []

    extra_fields = set(metadata.keys()) - ALLOWED_FIELDS
    if extra_fields:
        errors.append(
            f"Unexpected fields in frontmatter: {', '.join(sorted(extra_fields))}. "
            f"Only {sorted(ALLOWED_FIELDS)} are allowed."
        )

    return errors


def validate_metadata(metadata: dict, skill_dir: Optional[Path] = None) -> list[str]:
    """验证已解析的 Skill 元数据。
    
    这是核心验证函数，对已解析的元数据进行验证，
    避免在从解析器调用时重复文件 I/O。
    
    参数:
        metadata: 已解析的 YAML frontmatter 字典
        skill_dir: Skill 目录的可选路径（用于名称目录匹配检查）
        
    返回:
        验证错误消息列表。空列表表示有效。
    """
    errors = []
    errors.extend(_validate_metadata_fields(metadata))

    if "name" not in metadata:
        errors.append("Missing required field in frontmatter: name")
    else:
        errors.extend(_validate_name(metadata["name"], skill_dir))

    if "description" not in metadata:
        errors.append("Missing required field in frontmatter: description")
    else:
        errors.extend(_validate_description(metadata["description"]))

    if "compatibility" in metadata:
        errors.extend(_validate_compatibility(metadata["compatibility"]))

    return errors


def validate(skill_dir: Path) -> list[str]:
    """验证 Skill 目录。
    
    参数:
        skill_dir: Skill 目录的路径
        
    返回:
        验证错误消息列表。空列表表示有效。
    """
    skill_dir = Path(skill_dir)

    if not skill_dir.exists():
        return [f"Path does not exist: {skill_dir}"]

    if not skill_dir.is_dir():
        return [f"Not a directory: {skill_dir}"]

    skill_md = find_skill_md(skill_dir)
    if skill_md is None:
        return ["Missing required file: SKILL.md"]

    try:
        content = skill_md.read_text(encoding='utf-8')
        metadata, _ = parse_frontmatter(content)
    except ParseError as e:
        return [str(e)]

    return validate_metadata(metadata, skill_dir)


# ============================================================================
# Prompt 生成器模块
# ============================================================================

def to_prompt(skill_dirs: list[Path]) -> str:
    """生成用于 Agent 提示的 <available_skills> XML 块。
    
    这是 Anthropic 使用并推荐给 Claude 模型的 XML 格式。
    Skill 客户端可以根据其模型或偏好以不同格式格式化技能信息。
    
    参数:
        skill_dirs: Skill 目录路径列表
        
    返回:
        包含 <available_skills> 块的 XML 字符串，每个技能包含
        名称、描述和位置。
        
    示例输出:
        <available_skills>
        <skill>
        <name>pdf-reader</name>
        <description>Read and extract text from PDF files</description>
        <location>/path/to/pdf-reader/SKILL.md</location>
        </skill>
        </available_skills>
    """
    if not skill_dirs:
        return "<available_skills>\n</available_skills>"

    lines = ["<available_skills>"]

    for skill_dir in skill_dirs:
        skill_dir = Path(skill_dir).resolve()
        props = read_properties(skill_dir)

        lines.append("<skill>")
        lines.append("<name>")
        lines.append(html.escape(props.name))
        lines.append("</name>")
        lines.append("<description>")
        lines.append(html.escape(props.description))
        lines.append("</description>")

        skill_md_path = find_skill_md(skill_dir)
        lines.append("<location>")
        lines.append(str(skill_md_path))
        lines.append("</location>")

        lines.append("</skill>")

    lines.append("</available_skills>")

    return "\n".join(lines)


# ============================================================================
# 渐进式披露引擎
# ============================================================================

class ProgressiveDisclosureEngine:
    """渐进式披露引擎。
    
    实现三层加载架构：
    - L1: 元数据（name + description）- 始终加载
    - L2: 指令（SKILL.md 正文）- 技能被激活后加载
    - L3: 资源（scripts/、references/、assets/）- 按需加载
    """
    
    def __init__(self, skills_root: Path, max_cache_size: int = 100):
        """初始化渐进式披露引擎。
        
        参数:
            skills_root: Skills 根目录路径
            max_cache_size: LRU 缓存的最大大小
        """
        self.skills_root = Path(skills_root)
        self._metadata_cache = {}  # L1 缓存
        self._instruction_cache = {}  # L2 缓存
        self._resource_cache = {}  # L3 缓存
        self._max_cache_size = max_cache_size
    
    def scan_skills(self) -> dict[str, SkillProperties]:
        """扫描 Skills 根目录，返回所有技能元数据。
        
        这是 L1 层级的加载，用于模型启动时的路由决策。
        
        返回:
            技能名称到 SkillProperties 的映射
        """
        if not self.skills_root.exists():
            return {}
        
        skills = {}
        for item in self.skills_root.iterdir():
            if item.is_dir():
                try:
                    props = read_properties(item)
                    skills[props.name] = props
                    self._metadata_cache[props.name] = props
                except (ParseError, ValidationError):
                    # 跳过无效的 Skill 目录
                    continue
        
        return skills
    
    def load_skill_instruction(self, skill_name: str) -> Skill:
        """加载技能指令（L2 层级）。
        
        当模型决定使用某个技能时调用此方法。
        
        参数:
            skill_name: 技能名称
            
        返回:
            完整的 Skill 对象，包含指令内容
            
        抛出:
            SkillError: 如果技能不存在或无法加载
        """
        # 查找技能目录
        skill_dir = None
        for item in self.skills_root.iterdir():
            if item.is_dir() and item.name == skill_name:
                skill_dir = item
                break
        
        if skill_dir is None:
            # 尝试在缓存中查找
            if skill_name in self._metadata_cache:
                props = self._metadata_cache[skill_name]
                # 根据 name 查找目录
                for item in self.skills_root.iterdir():
                    if item.is_dir():
                        try:
                            item_props = read_properties(item)
                            if item_props.name == skill_name:
                                skill_dir = item
                                break
                        except:
                            continue
        
        if skill_dir is None:
            raise SkillError(f"Skill not found: {skill_name}")
        
        # 获取属性（从缓存或重新读取）
        if skill_name in self._metadata_cache:
            props = self._metadata_cache[skill_name]
        else:
            props = read_properties(skill_dir)
            self._metadata_cache[skill_name] = props
        
        # 获取正文
        if skill_name in self._instruction_cache:
            body = self._instruction_cache[skill_name]
        else:
            body = read_skill_body(skill_dir)
            self._instruction_cache[skill_name] = body
        
        # 构建 Skill 对象
        skill = Skill(
            path=skill_dir,
            properties=props,
            body=body,
            location=find_skill_md(skill_dir),
        )
        
        # 扫描可选目录
        self._scan_optional_dirs(skill)
        
        return skill
    
    def _scan_optional_dirs(self, skill: Skill) -> None:
        """扫描技能目录中的可选目录（scripts/、references/、assets/）。"""
        # 扫描 scripts/
        scripts_dir = skill.path / "scripts"
        if scripts_dir.exists():
            for file in scripts_dir.iterdir():
                if file.is_file():
                    skill.scripts[file.name] = file
        
        # 扫描 references/
        references_dir = skill.path / "references"
        if references_dir.exists():
            for file in references_dir.iterdir():
                if file.is_file() and file.suffix == '.md':
                    skill.references[file.stem] = file.read_text(encoding='utf-8')
        
        # 扫描 assets/
        assets_dir = skill.path / "assets"
        if assets_dir.exists():
            for root, dirs, files in os.walk(assets_dir):
                for file in files:
                    rel_path = Path(root).relative_to(assets_dir)
                    skill.assets[str(rel_path / file)] = Path(root) / file
    
    def load_reference(self, skill_name: str, ref_name: str) -> str:
        """按需加载参考文档（L3 层级）。
        
        参数:
            skill_name: 技能名称
            ref_name: 参考文档名称（不含 .md 扩展名）
            
        返回:
            参考文档内容
            
        抛出:
            SkillError: 如果参考文档不存在
        """
        cache_key = f"{skill_name}:{ref_name}"
        
        if cache_key in self._resource_cache:
            return self._resource_cache[cache_key]
        
        skill = self.load_skill_instruction(skill_name)
        
        if ref_name in skill.references:
            content = skill.references[ref_name]
            self._cache_resource(cache_key, content)
            return content
        
        # 尝试从文件加载
        ref_file = skill.path / "references" / f"{ref_name}.md"
        if ref_file.exists():
            content = ref_file.read_text(encoding='utf-8')
            self._cache_resource(cache_key, content)
            return content
        
        raise SkillError(f"Reference not found: {ref_name} in skill {skill_name}")
    
    def _cache_resource(self, key: str, content: str) -> None:
        """缓存资源内容，使用 LRU 策略。"""
        if len(self._resource_cache) >= self._max_cache_size:
            # 移除最早的条目
            first_key = next(iter(self._resource_cache))
            del self._resource_cache[first_key]
        self._resource_cache[key] = content
    
    def execute_script(self, skill_name: str, script_name: str, *args) -> tuple[int, str, str]:
        """执行技能脚本。
        
        参数:
            skill_name: 技能名称
            script_name: 脚本名称
            args: 传递给脚本的参数
            
        返回:
            (返回码, stdout, stderr) 的元组
            
        抛出:
            SkillError: 如果脚本不存在或执行失败
        """
        skill = self.load_skill_instruction(skill_name)
        
        if script_name not in skill.scripts:
            raise SkillError(f"Script not found: {script_name} in skill {skill_name}")
        
        script_path = skill.scripts[script_name]
        
        try:
            result = subprocess.run(
                [str(script_path)] + list(args),
                capture_output=True,
                text=True,
                timeout=60
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            raise SkillError(f"Script execution timed out: {script_name}")
        except Exception as e:
            raise SkillError(f"Script execution failed: {e}")
    
    def get_skill_prompt(self, skill_name: str, level: DisclosureLevel = DisclosureLevel.L2_INSTRUCTION) -> str:
        """获取技能提示内容。
        
        参数:
            skill_name: 技能名称
            level: 披露层级
            
        返回:
            指定层级的技能内容
        """
        if level == DisclosureLevel.L1_METADATA:
            props = self.load_skill_instruction(skill_name).properties
            return f"<skill>\n<name>{props.name}</name>\n<description>{props.description}</description>\n</skill>"
        elif level == DisclosureLevel.L2_INSTRUCTION:
            skill = self.load_skill_instruction(skill_name)
            return f"# {skill.properties.name}\n\n{skill.body}"
        elif level == DisclosureLevel.L3_RESOURCE:
            skill = self.load_skill_instruction(skill_name)
            parts = [f"# {skill.properties.name}\n\n{skill.body}"]
            for ref_name, content in skill.references.items():
                parts.append(f"\n## {ref_name}\n\n{content}")
            return "\n".join(parts)
        
        return ""


# ============================================================================
# CLI 命令行工具
# ============================================================================

def _is_skill_md_file(path: Path) -> bool:
    """检查路径是否直接指向 SKILL.md 或 skill.md 文件。"""
    return path.is_file() and path.name.lower() == "skill.md"


def cli_validate(skill_path: Path) -> int:
    """验证 Skill 目录。
    
    检查 Skill 是否有有效的 SKILL.md 和正确的前置元数据、
    命名约定和必需字段。
    
    退出码:
        0: 有效的 Skill
        1: 发现验证错误
    """
    if _is_skill_md_file(skill_path):
        skill_path = skill_path.parent

    errors = validate(skill_path)

    if errors:
        print(f"Validation failed for {skill_path}:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    else:
        print(f"Valid skill: {skill_path}")
        return 0


def cli_read_properties(skill_path: Path) -> int:
    """读取并以 JSON 格式打印 Skill 属性。
    
    解析 SKILL.md 的 YAML frontmatter 并以 JSON 格式输出属性。
    
    退出码:
        0: 成功
        1: 解析错误
    """
    try:
        if _is_skill_md_file(skill_path):
            skill_path = skill_path.parent

        props = read_properties(skill_path)
        print(json.dumps(props.to_dict(), indent=2, ensure_ascii=False))
        return 0
    except SkillError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cli_to_prompt(skill_paths: list[Path]) -> int:
    """为 Agent 提示生成 <available_skills> XML。
    
    接受一个或多个 Skill 目录。
    
    退出码:
        0: 成功
        1: 错误
    """
    try:
        resolved_paths = []
        for skill_path in skill_paths:
            if _is_skill_md_file(skill_path):
                resolved_paths.append(skill_path.parent)
            else:
                resolved_paths.append(skill_path)

        output = to_prompt(resolved_paths)
        print(output)
        return 0
    except SkillError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cli_scan(skills_root: Path, include_body: bool = False) -> int:
    """扫描 Skills 目录并列出所有技能。
    
    参数:
        skills_root: Skills 根目录
        include_body: 是否包含 SKILL.md 正文
        
    退出码:
        0: 成功
        1: 错误
    """
    try:
        engine = ProgressiveDisclosureEngine(skills_root)
        skills = engine.scan_skills()
        
        for name, props in sorted(skills.items()):
            print(f"📁 {name}")
            print(f"   描述: {props.description[:80]}...")
            if props.license:
                print(f"   许可证: {props.license}")
            if props.compatibility:
                print(f"   兼容性: {props.compatibility}")
            
            if include_body:
                try:
                    skill = engine.load_skill_instruction(name)
                    print(f"   正文长度: {len(skill.body)} 字符")
                    print(f"   脚本数: {len(skill.scripts)}")
                    print(f"   参考文档数: {len(skill.references)}")
                except:
                    pass
            print()
        
        print(f"共找到 {len(skills)} 个技能")
        return 0
    except SkillError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cli_disclosure(skill_name: str, skills_root: Path, level: str = "L2") -> int:
    """展示技能内容的渐进式披露。
    
    参数:
        skill_name: 技能名称
        skills_root: Skills 根目录
        level: 披露层级 (L1/L2/L3)
        
    退出码:
        0: 成功
        1: 错误
    """
    try:
        engine = ProgressiveDisclosureEngine(skills_root)
        
        if level == "L1":
            disclosure_level = DisclosureLevel.L1_METADATA
        elif level == "L3":
            disclosure_level = DisclosureLevel.L3_RESOURCE
        else:
            disclosure_level = DisclosureLevel.L2_INSTRUCTION
        
        content = engine.get_skill_prompt(skill_name, disclosure_level)
        print(content)
        return 0
    except SkillError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def print_help():
    """打印帮助信息。"""
    print("""Agent Skills 客户端工具
========================

用法: python agent_skills_client.py <命令> [选项] [参数]

命令:
  validate <path>        验证 Skill 目录
  read-properties <path> 读取并打印 Skill 属性为 JSON
  to-prompt <paths...>    为 Agent 提示生成 <available_skills> XML
  scan <path>            扫描并列出所有 Skills
  disclosure <name>       展示技能的渐进式披露内容

示例:
  python agent_skills_client.py validate ./my-skill
  python agent_skills_client.py read-properties ./my-skill
  python agent_skills_client.py to-prompt ./skill1 ./skill2
  python agent_skills_client.py scan ./skills
  python agent_skills_client.py disclosure pdf-processing --root ./skills --level L2
""")


# ============================================================================
# 主入口点
# ============================================================================

def main():
    """CLI 主入口点。"""
    if len(sys.argv) < 2:
        print_help()
        sys.exit(0)
    
    command = sys.argv[1].lower()
    
    if command == "validate":
        if len(sys.argv) < 3:
            print("错误: 需要指定 Skill 路径", file=sys.stderr)
            sys.exit(1)
        path = Path(sys.argv[2])
        sys.exit(cli_validate(path))
    
    elif command == "read-properties":
        if len(sys.argv) < 3:
            print("错误: 需要指定 Skill 路径", file=sys.stderr)
            sys.exit(1)
        path = Path(sys.argv[2])
        sys.exit(cli_read_properties(path))
    
    elif command == "to-prompt":
        if len(sys.argv) < 3:
            print("错误: 需要指定至少一个 Skill 路径", file=sys.stderr)
            sys.exit(1)
        paths = [Path(p) for p in sys.argv[2:]]
        sys.exit(cli_to_prompt(paths))
    
    elif command == "scan":
        if len(sys.argv) < 3:
            print("错误: 需要指定 Skills 根目录", file=sys.stderr)
            sys.exit(1)
        path = Path(sys.argv[2])
        include_body = "--verbose" in sys.argv or "-v" in sys.argv
        sys.exit(cli_scan(path, include_body))
    
    elif command in ("disclosure", "show"):
        # 解析 disclosure 命令的选项
        skill_name = None
        skills_root = Path(".")
        level = "L2"
        
        i = 2
        while i < len(sys.argv):
            arg = sys.argv[i]
            if arg == "--root" or arg == "-r":
                if i + 1 < len(sys.argv):
                    skills_root = Path(sys.argv[i + 1])
                    i += 2
                else:
                    print("错误: --root 需要一个路径参数", file=sys.stderr)
                    sys.exit(1)
            elif arg == "--level" or arg == "-l":
                if i + 1 < len(sys.argv):
                    level = sys.argv[i + 1]
                    i += 2
                else:
                    print("错误: --level 需要一个层级参数", file=sys.stderr)
                    sys.exit(1)
            elif arg == "--help" or arg == "-h":
                print("用法: python agent_skills_client.py disclosure <skill-name> [--root <path>] [--level L1|L2|L3]")
                sys.exit(0)
            else:
                skill_name = arg
                i += 1
        
        if not skill_name:
            print("错误: 需要指定技能名称", file=sys.stderr)
            sys.exit(1)
        
        sys.exit(cli_disclosure(skill_name, skills_root, level))
    
    elif command in ("help", "--help", "-h"):
        print_help()
        sys.exit(0)
    
    else:
        print(f"错误: 未知命令 '{command}'", file=sys.stderr)
        print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()