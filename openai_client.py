"""
开发计划：

本脚本是一个OpenAI Compatible命令行客户端。
用户向这个脚本输入--url、--key、--model等参数就可以连接OpenAI兼容的大模型。
其他命令行参数可以自己拟定。
脚本接收网络端大模型的sse响应后，有三种模式将大模型的返回到命令行：
1. SSE原始输出：OpenAI Compatible返回的是一个生成器，通过for循环读取生成器后可以原样输出SSE流式内容。内容是{data:}格式，一点一点打印到命令行的。
2. SSE解析输出：脚本会解析SSE流中的数据，只输出有用的内容，例如生成的文本。内容是一点一点打印到命令行的，只不过打印内容不是SSE固定的{data:}格式。
3. 非SSE解析输出：等待大模型全部生成完毕后一次性输出结果文本。
所以你需要一个函数获取到生成器，然后用三个函数处理这三种输出模式。
除了正常的QA功能，你还需要获取模型列表的功能，即访问 /v1/models 接口。
还需要模型测试功能，许多客户端在配置好大模型连接信息后，有个测试按钮看看模型是否可用，你需要实现这个测试功能。

本脚本选择requests库，而不选择使用openai库的原因如下：
1. 灵活性更高：脚本需要支持三种输出模式（SSE原始输出、SSE解析输出、非SSE解析输出），使用 `requests` 可以完全控制如何解析和处理 SSE 流。
2. OpenAI兼容API支持：脚本是 "OpenAI Compatible" 客户端，可能需要连接各种第三方 API（如 SiliconFlow、Ollama 等）。`openai` 库主要针对 OpenAI 官方 API 优化，对第三方兼容 API 的支持可能有限。
3. 零额外依赖：当前只依赖 `requests` 一个库。如果改用 `openai` 库，会引入更多传递依赖。
4. SSE 处理更直接：`requests.post(..., stream=True)` + `response.iter_lines()` 是处理 SSE 流的标准方式，代码简洁可控。

选择 `openai` 库的潜在问题：
1. `openai` 库内置的流式响应是通过 `OpenAI` 客户端对象处理的，输出格式固定，难以实现脚本需要的 "SSE原始输出" 模式。
2. 对于第三方兼容 API，可能需要额外配置 `base_url` 参数，且某些功能可能不兼容。

使用 `requests` 库是正确的选择。
请开始你的命令行开发，将代码追加写入本文件下方，不要破坏开发计划。
"""

'''
# 依赖包
requests
'''

import argparse
import sys
import json
import re
import requests
from typing import Iterator, Generator, Optional

# ========== 配置 ==========
DEFAULT_API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-3.5-turbo"


# ========== URL标准化函数 ==========
def normalize_url(url: str) -> str:
    """
    统一处理用户输入的URL，确保格式正确：
    - 如果用户只输入了 ip:port，会补全到 /v1
    - 如果用户输入了 /v1/chat/completions 这种形式，会截断到 /v1
    - 最终返回的是 /v1 结尾的基础URL
    
    Args:
        url: 用户输入的URL
    
    Returns:
        标准化后的URL，以 /v1 结尾
    """
    # 去掉末尾的斜杠
    url = url.rstrip('/')
    
    # 检查是否包含 /v1
    if '/v1' in url:
        # 截断到 /v1
        url = re.sub(r'/v1/.*$', '/v1', url)
    else:
        # 补全到 /v1
        url = url + '/v1'
    
    return url


def get_chat_completions_url(url: str) -> str:
    """
    获取完整的chat completions API端点URL
    
    Args:
        url: 标准化后的URL（/v1结尾）
    
    Returns:
        完整的API端点URL
    """
    return url + '/chat/completions'

# ========== 获取模型列表 ==========
def list_models(base_url: str, api_key: str) -> Optional[dict]:
    """
    获取可用的模型列表
    
    Args:
        base_url: API基础地址（/v1结尾，已经标准化）
        api_key: API密钥
    
    Returns:
        模型列表字典，失败返回None
    """
    models_url = f"{base_url}/models"
    
    headers = {
        "Authorization": f"Bearer {api_key}"
    }
    
    try:
        response = requests.get(models_url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"获取模型列表失败: {e}", file=sys.stderr)
        return None


def output_models(models_data: dict) -> None:
    """
    输出模型列表
    """
    if not models_data:
        return
    
    if 'data' in models_data:
        print("\n可用模型列表:")
        print("-" * 50)
        for model in models_data['data']:
            model_id = model.get('id', 'unknown')
            # 有些API会返回created或owned_by字段
            created = model.get('created', '')
            owned_by = model.get('owned_by', '')
            print(f"  - {model_id}", end='')
            if owned_by:
                print(f" (由 {owned_by} 创建)", end='')
            print()
        print("-" * 50)
        print(f"共 {len(models_data['data'])} 个模型")
    else:
        # 如果格式不同，直接打印原始数据
        print(json.dumps(models_data, ensure_ascii=False, indent=2))


# ========== 模型测试功能 ==========
def test_model(url: str, api_key: str, model: str) -> bool:
    """
    测试模型是否可用
    
    Args:
        url: API地址
        api_key: API密钥
        model: 模型名称
    
    Returns:
        测试是否成功
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    # 使用简单的测试消息
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Hi"}],
        "max_tokens": 5,
        "stream": False  # 必须指定 stream=False 才能获取 JSON 响应
    }
    
    print(f"\n正在测试模型 {model}...", flush=True)
    
    try:
        # 必须使用 stream=False 来获取 JSON 响应，否则服务器会返回 SSE 流导致解析失败
        response = requests.post(url, headers=headers, json=payload, stream=False, timeout=60)
        response.raise_for_status()
        result = response.json()
        
        # 检查返回是否有有效内容
        if 'choices' in result and len(result['choices']) > 0:
            content = result['choices'][0].get('message', {}).get('content', '')
            if content:
                print(f"[OK] 模型测试成功！")
                print(f"  响应: {content[:100]}{'...' if len(content) > 100 else ''}")
                return True
        
        # 即使没有choices，也说明连接成功
        print(f"[OK] 模型测试成功！（API响应正常）")
        return True
        
    except requests.exceptions.Timeout:
        print(f"[X] 模型测试失败: 请求超时", file=sys.stderr)
        return False
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print(f"[X] 模型测试失败: API密钥无效 (401 Unauthorized)", file=sys.stderr)
        elif e.response.status_code == 404:
            print(f"[X] 模型测试失败: 模型 {model} 不存在 (404 Not Found)", file=sys.stderr)
        elif e.response.status_code == 400:
            print(f"[X] 模型测试失败: 请求参数错误 (400 Bad Request)", file=sys.stderr)
        else:
            print(f"[X] 模型测试失败: HTTP错误 {e.response.status_code}", file=sys.stderr)
        return False
    except requests.exceptions.RequestException as e:
        print(f"[X] 模型测试失败: {e}", file=sys.stderr)
        return False

# ========== 获取SSE生成器 ==========
def get_sse_generator(url: str, api_key: str, model: str, messages: list, stream: bool = True) -> Generator:
    """
    获取OpenAI兼容API的SSE流式响应生成器
    
    Args:
        url: API地址
        api_key: API密钥
        model: 模型名称
        messages: 消息列表
        stream: 是否启用流式输出
    
    Returns:
        SSE流式响应生成器
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    payload = {
        "model": model,
        "messages": messages,
        "stream": stream
    }
    
    response = requests.post(url, headers=headers, json=payload, stream=True, timeout=60)
    response.raise_for_status()
    
    return response.iter_lines()


# ========== 模式1: SSE原始输出 ==========
def output_sse_raw(generator: Generator) -> None:
    """
    原始输出SSE流内容，逐行打印{data:}格式的数据
    """
    for line in generator:
        if line:
            # SSE格式通常是: data: {...}
            decoded_line = line.decode('utf-8') if isinstance(line, bytes) else line
            if decoded_line.startswith('data:'):
                print(decoded_line, flush=True)


# ========== 模式2: SSE解析输出 ==========
def output_sse_parsed(generator: Generator) -> None:
    """
    解析SSE流，只输出有用的文本内容（生成的内容是一点一点打印的）
    """
    for line in generator:
        if line:
            decoded_line = line.decode('utf-8') if isinstance(line, bytes) else line
            # 跳过ping和空行
            if decoded_line.startswith('data: '):
                data_str = decoded_line[6:]  # 去掉 "data: " 前缀
                if data_str == '[DONE]':
                    break
                try:
                    data = json.loads(data_str)
                    # 提取增量内容
                    if 'choices' in data and len(data['choices']) > 0:
                        delta = data['choices'][0].get('delta', {})
                        if 'content' in delta:
                            print(delta['content'], end='', flush=True)
                except json.JSONDecodeError:
                    continue


# ========== 模式3: 非SSE解析输出 ==========
def output_non_sse(url: str, api_key: str, model: str, messages: list) -> None:
    """
    等待大模型全部生成完毕后一次性输出结果文本
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    payload = {
        "model": model,
        "messages": messages,
        "stream": False
    }
    
    response = requests.post(url, headers=headers, json=payload, timeout=120)
    response.raise_for_status()
    
    result = response.json()
    
    # 解析并输出内容
    if 'choices' in result and len(result['choices']) > 0:
        content = result['choices'][0].get('message', {}).get('content', '')
        print(content)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


# ========== 交互式输入 ==========
def get_user_messages() -> list:
    """
    交互式获取用户消息
    """
    print("\n请输入您的消息（新增一行并输入 </enter> 结束输入，输入 /q 退出）：\n", flush=True)
    
    lines = []
    while True:
        try:
            line = input()
            if line.strip() == '/q':
                sys.exit(0)
            if line.strip() == '</enter>':
                break
            lines.append(line)
        except EOFError:
            break
    
    if not lines:
        return []
    
    # 第一行作为用户消息
    user_message = '\n'.join(lines)
    
    return [{"role": "user", "content": user_message}]


# ========== 主函数 ==========
def main():
    parser = argparse.ArgumentParser(
        description='OpenAI Compatible 命令行客户端',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
使用示例:
  # 测试模型是否可用
  python openai_client.py -u http://127.0.0.1:8000/v1 -k sk-abcdefgh -m gpt-3.5 -t
  
  # 列出可用模型列表
  python openai_client.py -u http://127.0.0.1:8000/v1 -k sk-abcdefgh -l
  
  # 对话模式（默认SSE解析输出）
  python openai_client.py -u http://127.0.0.1:8000/v1 -k sk-abcdefgh -m gpt-3.5
  
  # 非流式输出模式
  python openai_client.py -u http://127.0.0.1:8000/v1 -k sk-abcdefgh -m gpt-3.5 --no-stream
  
  # SSE原始输出模式
  python openai_client.py -u http://127.0.0.1:8000/v1 -k sk-abcdefgh -m gpt-3.5 --mode sse_raw
  
快捷参数说明:
  -u, --url      API地址 (支持简写，如 http://127.0.0.1:8000/ 会自动补全为 /v1)
  -k, --key      API密钥
  -m, --model    模型名称
  -t, --test     测试模型连接
  -l, --list-models  列出可用模型
  --no-stream    禁用流式输出（一次性返回结果）
  --mode         输出模式: sse_raw(原始SSE), sse_parsed(解析SSE), non_sse(非流式)
  -s, --system   系统提示词

退出方式: 输入 /q 退出程序
        '''
    )
    
    parser.add_argument('--url', '-u', default=DEFAULT_API_URL, help='API地址')
    parser.add_argument('--key', '-k', default='', help='API密钥')
    parser.add_argument('--model', '-m', default=DEFAULT_MODEL, help='模型名称')
    parser.add_argument('--mode', choices=['sse_raw', 'sse_parsed', 'non_sse'], default='sse_parsed',
                        help='输出模式: sse_raw(原始SSE), sse_parsed(解析SSE), non_sse(非流式)')
    parser.add_argument('--system', '-s', default='', help='系统提示词')
    parser.add_argument('--no-stream', action='store_true', help='禁用流式输出（等同于 --mode non_sse）')
    parser.add_argument('--list-models', '-l', action='store_true', help='列出可用模型')
    parser.add_argument('--test', '-t', action='store_true', help='测试模型连接')
    
    args = parser.parse_args()
    
    # 参数检查
    if not args.key:
        print("错误: 请提供API密钥 (--key)", file=sys.stderr)
        sys.exit(1)
    
    # 标准化URL：确保统一以 /v1 结尾
    base_url = normalize_url(args.url)
    
    # 获取模型列表模式
    if args.list_models:
        models_data = list_models(base_url, args.key)
        if models_data:
            output_models(models_data)
        sys.exit(0)
    
    # 测试模型模式
    if args.test:
        success = test_model(get_chat_completions_url(base_url), args.key, args.model)
        sys.exit(0 if success else 1)
    
    # 构建消息列表
    messages = []
    if args.system:
        messages.append({"role": "system", "content": args.system})
    
    # 获取用户消息
    user_messages = get_user_messages()
    if not user_messages:
        print("错误: 没有输入消息", file=sys.stderr)
        sys.exit(1)
    
    messages.extend(user_messages)
    
    # 获取完整的API端点URL
    api_url = get_chat_completions_url(base_url)
    
    # 根据模式执行
    if args.no_stream or args.mode == 'non_sse':
        output_non_sse(api_url, args.key, args.model, messages)
    else:
        try:
            generator = get_sse_generator(api_url, args.key, args.model, messages, stream=True)
            if args.mode == 'sse_raw':
                output_sse_raw(generator)
            else:  # sse_parsed
                output_sse_parsed(generator)
        except requests.exceptions.RequestException as e:
            print(f"\n错误: 请求失败 - {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == '__main__':
    main()