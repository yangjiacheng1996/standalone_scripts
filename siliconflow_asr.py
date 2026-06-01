"""
开发提示词：

硅基流动（https://cloud.siliconflow.cn/）是一个提供多种模型的综合平台。
包括大语言模型LLM、视觉语言模型VLM、嵌入式模型EM、重排序模型RM、语音识别模型ASR、文本到语音模型TTS、文生图L2I、文生视频L2V、图生视频I2V。
现在我希望使用ASR将本地视频/音频文件转化成文本。目前硅基流动包含两个个ASR模型TeleAI/TeleSpeechASR、FunAudioLLM/SenseVoiceSmall
关于FunAudioLLM/SenseVoiceSmall文档如下：

curl --request POST \
  --url https://api.siliconflow.cn/v1/audio/transcriptions \
  -H "Authorization: Bearer <YOUR_API_KEY>" \
  -F "file=@path/to/your/audio.mp3" \
  -F "model=FunAudioLLM/SenseVoiceSmall"

import requests
url = "https://api.siliconflow.cn/v1/audio/transcriptions"
file_path = "path/to/your/audio.mp3"
headers = {
    "Authorization": "Bearer <YOUR_API_KEY>"
}
with open(file_path, "rb") as audio_file:
    files = {
        "file": ("audio.mp3", audio_file),  # 根据文件类型调整 MIME 类型
        "model": (None, "FunAudioLLM/SenseVoiceSmall")
    }
    response = requests.post(url, headers=headers, files=files)

官方并未给出TeleAI/TeleSpeechASR的API文档，我猜想应该是一样的。
现在请你编写一个python命令行工具，用于调用硅基流动的ASR模型，将本地视频/音频文件转化成文本。
我设计的参数如下：
-f, --filepath: 本地视频/音频文件路径
-m, --model: ASR模型名称，TeleAI/TeleSpeechASR或FunAudioLLM/SenseVoiceSmall
-k, --apikey: 硅基流动API密钥
现在开始开发，代码追加写入本文件的下方，不要破坏开发提示词。
"""

'''
脚本依赖：
requests
'''

import argparse
import os
import requests
from pathlib import Path


API_URL = "https://api.siliconflow.cn/v1/audio/transcriptions"

SUPPORTED_MODELS = [
    "TeleAI/TeleSpeechASR",
    "FunAudioLLM/SenseVoiceSmall"
]

# 支持的音频文件扩展名
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.ogg', '.flac', '.aac', '.wma', '.webm'}


def get_mime_type(file_path: str) -> str:
    """根据文件扩展名返回MIME类型"""
    ext = Path(file_path).suffix.lower()
    mime_types = {
        '.mp3': 'audio/mpeg',
        '.wav': 'audio/wav',
        '.m4a': 'audio/mp4',
        '.ogg': 'audio/ogg',
        '.flac': 'audio/flac',
        '.aac': 'audio/aac',
        '.wma': 'audio/x-ms-wma',
        '.webm': 'audio/webm',
    }
    return mime_types.get(ext, 'application/octet-stream')


def transcribe_audio(api_key: str, file_path: str, model: str) -> str:
    """
    调用硅基流动ASR API将音频文件转录为文本
    
    Args:
        api_key: 硅基流动API密钥
        file_path: 本地音频文件路径
        model: ASR模型名称
    
    Returns:
        转录文本内容
    
    Raises:
        FileNotFoundError: 文件不存在
        ValueError: 文件不是支持的音频格式
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")
    
    ext = Path(file_path).suffix.lower()
    if ext not in AUDIO_EXTENSIONS:
        supported_list = ', '.join(sorted(AUDIO_EXTENSIONS))
        raise ValueError(f"不支持的文件格式: {ext}\n仅支持以下音频格式: {supported_list}")
    
    headers = {
        "Authorization": f"Bearer {api_key}"
    }
    
    file_name = os.path.basename(file_path)
    mime_type = get_mime_type(file_path)
    
    with open(file_path, "rb") as audio_file:
        files = {
            "file": (file_name, audio_file, mime_type),
            "model": (None, model)
        }
        
        response = requests.post(API_URL, headers=headers, files=files)
    
    response.raise_for_status()
    
    result = response.json()
    
    if "text" in result:
        return result["text"]
    else:
        raise ValueError(f"API响应格式异常: {result}")


def main():
    parser = argparse.ArgumentParser(
        description="使用硅基流动ASR模型将本地音频文件转录为文本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
支持的模型:
  - TeleAI/TeleSpeechASR
  - FunAudioLLM/SenseVoiceSmall

支持的音频格式: mp3, wav, m4a, ogg, flac, aac, wma, webm
        """
    )
    
    parser.add_argument(
        "-f", "--filepath",
        required=True,
        help="本地音频文件路径"
    )
    
    parser.add_argument(
        "-m", "--model",
        required=True,
        choices=SUPPORTED_MODELS,
        help="ASR模型名称"
    )
    
    parser.add_argument(
        "-k", "--apikey",
        required=True,
        help="硅基流动API密钥"
    )
    
    parser.add_argument(
        "-o", "--output",
        help="输出文件路径（可选，默认输出到控制台）"
    )
    
    parser.add_argument(
        "--encoding",
        default="utf-8",
        help="输出文件编码（默认: utf-8）"
    )
    
    args = parser.parse_args()
    
    print(f"正在使用模型 {args.model} 处理文件: {args.filepath}")
    print("请稍候...")
    
    try:
        text = transcribe_audio(args.apikey, args.filepath, args.model)
        
        if args.output:
            os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
            with open(args.output, 'w', encoding=args.encoding) as f:
                f.write(text)
            print(f"转录完成，已保存到: {args.output}")
        else:
            print("\n===== 转录结果 =====")
            print(text)
            print("=====================")
        
        return 0
        
    except FileNotFoundError as e:
        print(f"错误: {e}")
        return 1
    except requests.exceptions.RequestException as e:
        print(f"请求错误: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"响应内容: {e.response.text}")
        return 1
    except Exception as e:
        print(f"发生错误: {e}")
        return 1


if __name__ == "__main__":
    exit(main())

# ==================== 详细使用示例 ====================
# 
# 示例1：基本用法，使用 FunAudioLLM/SenseVoiceSmall 模型，直接输出到控制台
# python siliconflow_asr.py -f example.mp3 -m FunAudioLLM/SenseVoiceSmall -k your_api_key_here
# 
# 示例2：使用 TeleAI/TeleSpeechASR 模型
# python siliconflow_asr.py -f example.m4a -m TeleAI/TeleSpeechASR -k your_api_key_here
# 
# 示例3：将转录结果保存到文件
# python siliconflow_asr.py -f example.wav -m FunAudioLLM/SenseVoiceSmall -k your_api_key_here -o output.txt
# 
# 示例4：指定输出编码（解决中文乱码问题）
# python siliconflow_asr.py -f example.m4a -m FunAudioLLM/SenseVoiceSmall -k your_api_key_here -o output.txt --encoding utf-8
# 
# 参数说明：
#   -f, --filepath  : 音频文件路径（必填）
#   -m, --model    : ASR模型名称，可选 TeleAI/TeleSpeechASR 或 FunAudioLLM/SenseVoiceSmall（必填）
#   -k, --apikey   : 硅基流动API密钥（必填）
#   -o, --output   : 输出文件路径，可选，不填则输出到控制台
#   --encoding     : 输出文件编码，默认 utf-8