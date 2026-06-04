"""
开发计划

openai_client.py是我编写的LLM客户端，现在我想使用视觉模型，上传一个或多个图片+提示词交给视觉大模型生成回答。

图片传输原理
图片并不是直接转化成纯字符串传给VLM的，而是经过一系列复杂的预处理，最终被转换成模型能够理解的**向量（Token序列）**形式。
具体来说，当你在AI客户端上传本地图片并输入提示词时，图片的传输和处理通常经历以下几个关键步骤：
**1. 图像的编码与传输**
在客户端和服务端之间传递图片时，由于网络协议的限制，图片通常会被转换为特定的格式进行传输。
最常见的方式是将图片文件读取后，转化为 **Base64 编码字符串**（例如 `data:image/<图片格式>;base64,<Base64编码>`），
或者提供一个可访问的图像URL。在这个阶段，它确实是以类似字符串的形式在网络中传输的，但这只是为了方便数据的搬运。
**2. 解码与像素矩阵转换**
服务端接收到 Base64 数据或下载完 URL 对应的图片后，会利用图像处理库（如 Pillow、OpenCV）将其解码。
如果图片包含透明通道（Alpha通道），通常还会被合并到白色背景上转为标准的 RGB 模式，并统一缩放到模型所需的输入尺寸，
最终转化成一个由数字组成的**像素矩阵（张量/Tensor）**。
**3. 切块（Patching）与线性投影**
这是将"视觉"转化为"语言"的核心步骤。为了适配大语言模型的架构，原始图像会被分割成固定大小的小块（例如 16×16 像素），
每个小块被称为一个 "patch"。随后，这些 patch 会通过线性投影（通常是 2D 卷积层）映射到一个高维的向量空间中，
变成一个个类似于文本单词的**视觉 Token**。
**4. 模态对齐与拼接**
为了让语言模型能够"读懂"这些视觉 Token，模型内部会有一个连接器（Connector/Projector）。
它的作用是对视觉特征进行维度映射和语义对齐，确保它们与文本 Token 处于同一个语义空间内。
最后，这些处理好的视觉 Token 会与你的文本提示词生成的文本 Token 拼接在一起，共同输入到大型语言模型（LLM）中进行注意力计算，从而生成最终的图文回答。
简单来说，图片在网络传输时可能会暂时以 Base64 字符串的形式存在，但进入 VLM 的大脑后，
它是被拆解成了无数个代表局部特征的"视觉单词（Token向量）"，再与你的文字一起进行深度推理的。

如果您要编写一个面向大模型服务商（如 OpenAI、阿里云等）的 VLM 客户端，您确实只需要关心第一步：图像的编码与传输。
至于后续的解码、切块（Patching）、特征提取、模态对齐以及最终的文本生成等复杂的深度计算步骤，都是由大模型服务商在服务端完成的，对客户端是完全透明的。

现在开始开发，参考openai_client.py ，设计一个视觉模型VLM客户端，允许用户上传多张图片+提示词。命令添加一个-p, --picture参数，接受本地图片的绝对路径。
客户端需要检查本脚本是否有权限读取图片，图片是否存在、路径所指文件是否为图片等。本脚本可以接受多个-p参数，每个参数只接受一个图片路径。
代码追加写入到本文件下方，不要破坏开发计划。

"""

'''
# 依赖包
requests
'''

import argparse
import sys
import json
import re
import os
import base64
import mimetypes
import requests
from typing import Iterator, Generator, Optional, List

# ========== 配置 ==========
DEFAULT_API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-4o"

# 支持的图片格式
SUPPORTED_IMAGE_FORMATS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}


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


# ========== 图片处理函数 ==========
def resize_image_if_needed(image_path: str, max_size: int = 512) -> Optional[bytes]:
    """
    如果图片尺寸过大，调整其大小
    
    MiniMax 等 API 对图片大小有限制，通常需要将图片缩小到最大 512px 左右
    以确保 base64 编码后不会超出上下文窗口限制
    
    Args:
        image_path: 图片文件路径
        max_size: 最大边长（像素），默认为 512
    
    Returns:
        调整后的图片字节数据，失败返回 None
    """
    try:
        from PIL import Image
        import io
        
        with Image.open(image_path) as img:
            # 转换 RGBA 模式为 RGB（如果有透明通道）
            if img.mode == 'RGBA':
                background = Image.new('RGB', img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[3])
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            # 检查是否需要调整大小
            width, height = img.size
            if width > max_size or height > max_size:
                # 计算缩放比例
                if width > height:
                    new_width = max_size
                    new_height = int(height * (max_size / width))
                else:
                    new_height = max_size
                    new_width = int(width * (max_size / height))
                
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # 保存到字节流
            output = io.BytesIO()
            # 根据原文件格式保存，或默认保存为 JPEG
            ext = os.path.splitext(image_path)[1].lower()
            if ext in ['.png', '.gif']:
                img.save(output, format='PNG')
            else:
                img.save(output, format='JPEG', quality=95)
            
            return output.getvalue()
    except ImportError:
        # 如果没有安装 Pillow，直接返回 None
        print("警告: 未安装 Pillow 库，无法自动调整图片大小", file=sys.stderr)
        return None
    except Exception as e:
        print(f"调整图片大小失败: {e}", file=sys.stderr)
        return None


def get_mime_type(file_path: str) -> Optional[str]:
    """
    获取文件的MIME类型
    
    Args:
        file_path: 文件路径
    
    Returns:
        MIME类型字符串，如 'image/png'，失败返回None
    """
    mime_type, _ = mimetypes.guess_type(file_path)
    return mime_type


def is_image_file(file_path: str) -> bool:
    """
    检查文件是否为图片
    
    Args:
        file_path: 文件路径
    
    Returns:
        是否为图片文件
    """
    # 检查扩展名
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in SUPPORTED_IMAGE_FORMATS:
        return False
    
    # 检查MIME类型
    mime_type = get_mime_type(file_path)
    if mime_type is None or not mime_type.startswith('image/'):
        return False
    
    return True


def validate_image_path(image_path: str) -> tuple[bool, str]:
    """
    验证图片路径是否有效
    
    Args:
        image_path: 图片路径
    
    Returns:
        (是否有效, 错误信息)
    """
    # 检查路径是否存在
    if not os.path.exists(image_path):
        return False, f"图片文件不存在: {image_path}"
    
    # 检查是否为文件
    if not os.path.isfile(image_path):
        return False, f"路径不是文件: {image_path}"
    
    # 检查是否有读取权限
    if not os.access(image_path, os.R_OK):
        return False, f"没有读取权限: {image_path}"
    
    # 检查是否为图片格式
    if not is_image_file(image_path):
        ext = os.path.splitext(image_path)[1].lower()
        return False, f"不支持的图片格式: {ext}，支持的格式: {', '.join(SUPPORTED_IMAGE_FORMATS)}"
    
    return True, ""


def encode_image_to_base64(image_path: str, resize: bool = True) -> Optional[str]:
    """
    将图片文件编码为Base64字符串
    
    Args:
        image_path: 图片文件路径
        resize: 是否自动调整图片大小（默认为True，用于适配 MiniMax 等 API 的限制）
    
    Returns:
        Base64编码字符串（包含data URI前缀），失败返回None
    """
    try:
        image_data = None
        
        # 如果需要调整大小
        if resize:
            resized_data = resize_image_if_needed(image_path)
            if resized_data is not None:
                image_data = resized_data
        
        # 如果没有调整大小或调整失败，读取原始文件
        if image_data is None:
            with open(image_path, 'rb') as f:
                image_data = f.read()
        
        # 确定 MIME 类型（如果调整过大小，默认使用 jpeg 或 png）
        mime_type = get_mime_type(image_path)
        if mime_type is None:
            ext = os.path.splitext(image_path)[1].lower()
            if ext in ['.png', '.gif']:
                mime_type = 'image/png'
            else:
                mime_type = 'image/jpeg'
        
        base64_data = base64.b64encode(image_data).decode('utf-8')
        return f"data:{mime_type};base64,{base64_data}"
    
    except Exception as e:
        print(f"编码图片失败: {e}", file=sys.stderr)
        return None


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
def test_model(url: str, api_key: str, model: str, has_images: bool = False) -> bool:
    """
    测试模型是否可用
    
    Args:
        url: API地址
        api_key: API密钥
        model: 模型名称
        has_images: 是否使用图片测试
    
    Returns:
        测试是否成功
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    # 使用简单的测试消息
    if has_images:
        # 图片测试：发送一个简单的图片描述请求
        # 创建一个1x1像素的透明GIF图片作为测试
        test_image_base64 = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
        payload = {
            "model": model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Hi"},
                    {"type": "image_url", "image_url": {"url": test_image_base64}}
                ]
            }],
            "max_tokens": 5,
            "max_completion_tokens": 5,
            "stream": False
        }
    else:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 5,
            "max_completion_tokens": 5,
            "stream": False
        }
    
    print(f"\n正在测试模型 {model}...", flush=True)
    
    try:
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
    
    response = requests.post(url, headers=headers, json=payload, stream=True, timeout=120)
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
    自动过滤掉 <think>...</think> 标签内的思考内容
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "max_completion_tokens": 131072  # MiniMax-M3 推荐值
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=180)
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        # 尝试解析错误响应
        try:
            error_detail = e.response.json()
            print(f"\n错误: API返回错误 - {e.response.status_code}", file=sys.stderr)
            print(f"详情: {json.dumps(error_detail, ensure_ascii=False, indent=2)}", file=sys.stderr)
        except (json.JSONDecodeError, ValueError):
            # 如果无法解析JSON，直接输出原始响应
            print(f"\n错误: 请求失败 - {e}", file=sys.stderr)
            print(f"服务器响应: {e.response.text[:1000]}", file=sys.stderr)
        
        # 打印诊断信息
        print(f"\n诊断信息:", file=sys.stderr)
        print(f"  - 请求URL: {url}", file=sys.stderr)
        print(f"  - 模型: {model}", file=sys.stderr)
        
        # 检查图片相关问题
        for msg in messages:
            if msg.get('role') == 'user' and isinstance(msg.get('content'), list):
                for item in msg['content']:
                    if item.get('type') == 'image_url':
                        url_data = item.get('image_url', {}).get('url', '')
                        if url_data.startswith('data:'):
                            print(f"  - 检测到Base64编码图片，长度: {len(url_data)} 字符", file=sys.stderr)
                        else:
                            print(f"  - 检测到图片URL: {url_data[:50]}...", file=sys.stderr)
        sys.exit(1)
    
    result = response.json()
    
    # 解析并输出内容
    if 'choices' in result and len(result['choices']) > 0:
        content = result['choices'][0].get('message', {}).get('content', '')
        # 移除思考标签
        content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)
        print(content.strip())
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


# ========== 交互式输入 ==========
def get_user_message_with_images(image_paths: List[str], image_mode: str = "base64") -> dict:
    """
    获取用户消息，包含文本和图片内容
    
    Args:
        image_paths: 图片路径列表
        image_mode: 图片传输模式，"base64" 或 "url"
    
    Returns:
        用户消息字典
    """
    # 交互式获取文本输入
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
    
    user_text = '\n'.join(lines) if lines else ""
    
    # 构建消息内容
    content = []
    
    # 添加图片
    for img_path in image_paths:
        if image_mode == "base64":
            # Base64 模式：直接编码本地图片
            base64_image = encode_image_to_base64(img_path)
            if base64_image:
                image_item = {
                    "type": "image_url",
                    "image_url": {
                        "url": base64_image
                    }
                }
                # detail 字段是 OpenAI 特有的，部分第三方 API 不支持
                # image_item["image_url"]["detail"] = "auto"
                content.append(image_item)
        else:
            # URL 模式：需要图片可通过 HTTP 访问
            # 对于本地图片，检查是否为有效的 HTTP/HTTPS URL
            if img_path.startswith('http://') or img_path.startswith('https://'):
                image_item = {
                    "type": "image_url",
                    "image_url": {
                        "url": img_path
                    }
                }
                content.append(image_item)
            else:
                print(f"警告: URL模式下，本地图片路径无效: {img_path}", file=sys.stderr)
                print(f"  请提供可访问的 HTTP/HTTPS URL，或使用 --image-mode base64", file=sys.stderr)
    
    # 添加文本
    if user_text:
        content.insert(0, {"type": "text", "text": user_text})
    
    return {"role": "user", "content": content}


def get_user_message_text_only() -> dict:
    """
    仅获取用户文本消息（用于非图片模式）
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
    
    user_text = '\n'.join(lines) if lines else ""
    
    return {"role": "user", "content": user_text}


# ========== 主函数 ==========
def main():
    parser = argparse.ArgumentParser(
        description='OpenAI Compatible 视觉模型(VLM)命令行客户端',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
使用示例:
  # 测试视觉模型是否可用
  python openai_vlm_client.py -u http://127.0.0.1:8000/v1 -k sk-abcdefgh -m gpt-4o -t
  
  # 测试视觉模型（图片模式）
  python openai_vlm_client.py -u http://127.0.0.1:8000/v1 -k sk-abcdefgh -m gpt-4o -t -p /path/to/image.png
  
  # 列出可用模型列表
  python openai_vlm_client.py -u http://127.0.0.1:8000/v1 -k sk-abcdefgh -l
  
  # 上传单张图片进行对话
  python openai_vlm_client.py -u http://127.0.0.1:8000/v1 -k sk-abcdefgh -m gpt-4o -p /path/to/image.png
  
  # 上传多张图片进行对话
  python openai_vlm_client.py -u http://127.0.0.1:8000/v1 -k sk-abcdefgh -m gpt-4o -p /path/to/image1.png -p /path/to/image2.jpg
  
  # 非流式输出模式
  python openai_vlm_client.py -u http://127.0.0.1:8000/v1 -k sk-abcdefgh -m gpt-4o -p /path/to/image.png --no-stream

快捷参数说明:
  -u, --url        API地址 (支持简写，如 http://127.0.0.1:8000/ 会自动补全为 /v1)
  -k, --key        API密钥
  -m, --model      模型名称 (默认: gpt-4o)
  -t, --test       测试模型连接
  -l, --list-models  列出可用模型
  -p, --picture    图片路径（可多次使用添加多张图片）
  --no-stream      禁用流式输出（一次性返回结果）
  --mode           输出模式: sse_raw(原始SSE), sse_parsed(解析SSE), non_sse(非流式)
  -s, --system     系统提示词

支持的图片格式: PNG, JPG, JPEG, GIF, WEBP, BMP

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
    parser.add_argument('--picture', '-p', action='append', default=[], dest='pictures',
                        help='图片路径（可多次使用添加多张图片）')
    parser.add_argument('--image-mode', choices=['base64', 'url'], default='base64',
                        help='图片传输模式: base64(将图片转为Base64编码) 或 url(使用HTTP URL，需图片可访问)')
    
    args = parser.parse_args()
    
    # 参数检查
    if not args.key:
        print("错误: 请提供API密钥 (--key)", file=sys.stderr)
        sys.exit(1)
    
    # 验证图片路径
    image_paths = args.pictures
    validated_image_paths = []
    for img_path in image_paths:
        is_valid, error_msg = validate_image_path(img_path)
        if not is_valid:
            print(f"错误: {error_msg}", file=sys.stderr)
            sys.exit(1)
        validated_image_paths.append(img_path)
    
    if validated_image_paths:
        print(f"已加载 {len(validated_image_paths)} 张图片")
    
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
        has_images = len(validated_image_paths) > 0
        success = test_model(get_chat_completions_url(base_url), args.key, args.model, has_images)
        sys.exit(0 if success else 1)
    
    # 构建消息列表
    messages = []
    if args.system:
        messages.append({"role": "system", "content": args.system})
    
    # 获取用户消息（根据是否有图片选择不同的处理方式）
    if validated_image_paths:
        user_message = get_user_message_with_images(validated_image_paths, args.image_mode)
    else:
        user_message = get_user_message_text_only()
    
    if isinstance(user_message.get('content'), str) and not user_message['content']:
        print("错误: 没有输入消息", file=sys.stderr)
        sys.exit(1)
    
    # 检查消息是否为空（对于有图片的情况）
    if isinstance(user_message.get('content'), list):
        # 有图片的情况：检查是否有文本内容（图片可以单独存在）
        has_text = any(c.get('type') == 'text' and c.get('text', '').strip() 
                       for c in user_message['content'] if isinstance(c, dict))
        has_images = any(c.get('type') == 'image_url' for c in user_message['content'] if isinstance(c, dict))
        
        if not has_images and not has_text:
            print("错误: 没有输入消息或图片", file=sys.stderr)
            sys.exit(1)
        
        if not has_text:
            print("\n提示: 您只上传了图片，没有输入文字描述。模型可能会基于图片内容进行回答。\n")
    
    messages.append(user_message)
    
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


# ========== 命令行使用示例 ==========
"""
脚本命令行使用示例

基础使用
--------
1. 测试视觉模型是否可用（文本模式）
   python openai_vlm_client.py -u http://127.0.0.1:8000/v1 -k sk-abcdefgh -m gpt-4o -t

2. 测试视觉模型是否可用（图片模式）
   python openai_vlm_client.py -u http://127.0.0.1:8000/v1 -k sk-abcdefgh -m gpt-4o -t -p /path/to/image.png

3. 列出可用模型列表
   python openai_vlm_client.py -u http://127.0.0.1:8000/v1 -k sk-abcdefgh -l

4. 上传单张图片进行对话
   python openai_vlm_client.py -u http://127.0.0.1:8000/v1 -k sk-abcdefgh -m gpt-4o -p /path/to/image.png

5. 上传多张图片进行对话
   python openai_vlm_client.py -u http://127.0.0.1:8000/v1 -k sk-abcdefgh -m gpt-4o -p /path/to/image1.png -p /path/to/image2.jpg

6. 非流式输出模式（一次性返回结果）
   python openai_vlm_client.py -u http://127.0.0.1:8000/v1 -k sk-abcdefgh -m gpt-4o -p /path/to/image.png --no-stream

使用系统提示词
--------------
7. 添加系统提示词
   python openai_vlm_client.py -u http://127.0.0.1:8000/v1 -k sk-abcdefgh -m gpt-4o -p /path/to/image.png -s "你是一个专业的图像分析师"

8. 非流式输出 + 系统提示词
   python openai_vlm_client.py -u http://127.0.0.1:8000/v1 -k sk-abcdefgh -m gpt-4o -p /path/to/image.png -s "你是一个专业的图像分析师" --no-stream

输出模式选择
------------
9. SSE原始输出模式（显示所有SSE数据）
   python openai_vlm_client.py -u http://127.0.0.1:8000/v1 -k sk-abcdefgh -m gpt-4o -p /path/to/image.png --mode sse_raw

10. SSE解析输出模式（只显示生成的文本，流式输出）
    python openai_vlm_client.py -u http://127.0.0.1:8000/v1 -k sk-abcdefgh -m gpt-4o -p /path/to/image.png --mode sse_parsed

11. 非流式输出模式（等待生成完毕后一次性输出）
    python openai_vlm_client.py -u http://127.0.0.1:8000/v1 -k sk-abcdefgh -m gpt-4o -p /path/to/image.png --mode non_sse

使用第三方API
-------------
12. 使用 OpenAI API
    python openai_vlm_client.py -u https://api.openai.com/v1 -k sk-xxxxxxxxxxxxxxxx -m gpt-4o -p /path/to/image.png

13. 使用 SiliconFlow API
    python openai_vlm_client.py -u https://api.siliconflow.cn/v1 -k sk-xxxxxxxxxxxxxxxx -m Qwen/Qwen2.5-VL-72B-Instruct -p /path/to/image.png

14. 使用阿里云百炼 API
    python openai_vlm_client.py -u https://dashscope.aliyuncs.com/compatible-mode/v1 -k sk-xxxxxxxxxxxxxxxx -m qwen-vl-max -p /path/to/image.png

实战场景
--------
15. 描述图片内容
    python openai_vlm_client.py -u http://127.0.0.1:8000/v1 -k sk-abcdefgh -m gpt-4o -p screenshot.png
    # 输入提示: 请描述这张图片的内容

16. 识别截图中的代码并解释
    python openai_vlm_client.py -u http://127.0.0.1:8000/v1 -k sk-abcdefgh -m gpt-4o -p error_screenshot.png
    # 输入提示: 这段代码有什么问题，应该如何修复？

17. 多图对比分析
    python openai_vlm_client.py -u http://127.0.0.1:8000/v1 -k sk-abcdefgh -m gpt-4o -p image1.png -p image2.png
    # 输入提示: 比较这两张图片的差异

18. 识别表格并转为结构化数据
    python openai_vlm_client.py -u http://127.0.0.1:8000/v1 -k sk-abcdefgh -m gpt-4o -p table_image.png -s "请将图片中的表格转为CSV格式输出"
    # 输入提示: 请将表格转为CSV格式

快捷参数汇总
------------
-u, --url      API地址
-k, --key      API密钥
-m, --model    模型名称 (默认: gpt-4o)
-t, --test     测试模型连接
-l, --list-models  列出可用模型
-p, --picture  图片路径（可多次使用添加多张图片）
--no-stream    禁用流式输出
--mode         输出模式: sse_raw, sse_parsed, non_sse
-s, --system   系统提示词

注意: 输入 /q 可以退出程序，输入 </enter> 结束多行输入
"""
