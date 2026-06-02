"""
开发计划：
我这里有一篇500字小学生作文，是歌颂春天的美好的，内容如下：

《春天的画卷》

寒冷的冬天悄悄地走了，春姑娘迈着轻盈的脚步，带着温暖和生机来到了我们的身边。她就像一位神奇的画家，用五彩斑斓的画笔，把大地装点得格外美丽。

你瞧，小草偷偷地从泥土里探出了小脑袋，好奇地张望着这个崭新的世界。它们嫩嫩的、绿绿的，给大地铺上了一层柔软的地毯。公园里的花儿们也竞相开放了，粉红的桃花像害羞的小姑娘，雪白的梨花挂满枝头，金灿灿的迎春花吹起了小喇叭，仿佛在告诉大家："春天来啦！春天来啦！"微风吹过，阵阵花香扑鼻而来，引来了翩翩起舞的蝴蝶和勤劳的小蜜蜂。

河边的柳树也抽出了新的枝条，长出了嫩绿的叶子。长长的柳枝垂在水面上，就像小姑娘在梳理自己美丽的长发。解冻的小溪"叮叮咚咚"地唱着欢快的歌儿，奔向远方。小燕子也从南方飞回来了，它们在屋檐下忙着筑巢，叽叽喳喳地叫着，好像在说："这里的春天真美啊！"

脱去厚重棉衣的我们，也像快乐的小鸟一样冲出家门。我们在草地上奔跑、放风筝，欢声笑语回荡在蓝天白云之间。

春天是一幅流动的画，春天是一首动听的歌。它给我们带来了无限的生机与希望。我爱这万物复苏、充满活力的美丽春天！

---
现在，我想使用FastAPI框架，把这个小作文变成一个可以被openai compatible框架调用的API，
用户访问/v1/chat/completions后，无论用户提问什么问题，都会将以上这篇作文通过SSE流式响应。
模型名称是zuowen，模型认证的sk是 sk-abcdefgh
用户可以通过/models等接口查询模型信息。
其他配套的接口都要有，比如模型测试接口/test等。
现在开始开发，请你将相关接口代码追加写入本文件下方，不要破坏开发提示词。
"""

'''
# 依赖
fastapi
uvicorn
'''

import time
import uuid
from typing import Annotated
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse

# 作文内容
ZuoWen_Content = """《春天的画卷》

寒冷的冬天悄悄地走了，春姑娘迈着轻盈的脚步，带着温暖和生机来到了我们的身边。她就像一位神奇的画家，用五彩斑斓的画笔，把大地装点得格外美丽。

你瞧，小草偷偷地从泥土里探出了小脑袋，好奇地张望着这个崭新的世界。它们嫩嫩的、绿绿的，给大地铺上了一层柔软的地毯。公园里的花儿们也竞相开放了，粉红的桃花像害羞的小姑娘，雪白的梨花挂满枝头，金灿灿的迎春花吹起了小喇叭，仿佛在大家一起说："春天来啦！春天来啦！"微风吹过，阵阵花香扑鼻而来，引来了翩翩起舞的蝴蝶和勤劳的小蜜蜂。

河边的柳树也抽出了新的枝条，长出了嫩绿的叶子。长长的柳枝垂在水面上，就像小姑娘在梳理自己美丽的长发。解冻的小溪"叮叮咚咚"地唱着欢快的歌儿，奔向远方。小燕子也从南方飞回来了，它们在屋檐下忙着筑巢，叽叽喳喳地叫着，好像在说："这里的春天真美啊！"

脱去厚重棉衣的我们，也像快乐的小鸟一样冲出家门。我们在草地上奔跑、放风筝，欢声笑语回荡在蓝天白云之间。

春天是一幅流动的画，春天是一首动听的歌。它给我们带来了无限的生机与希望。我爱这万物复苏、充满活力的美丽春天！"""

app = FastAPI(
    title="OpenAI Compatible API",
    description="一个返回春天作文的OpenAI兼容API",
    version="1.0.0"
)

# 配置
API_KEY = "sk-abcdefgh"
MODEL_NAME = "zuowen"


def verify_api_key(authorization: Annotated[str | None, Header()] = None, x_api_key: Annotated[str | None, Header()] = None):
    """验证API密钥
    
    支持两种认证方式：
    1. Authorization: Bearer <token> (标准OpenAI格式)
    2. X-Api-Key: <token>
    """
    api_key = None
    
    # 优先使用 Authorization Bearer 方式
    if authorization:
        if authorization.startswith("Bearer "):
            api_key = authorization[7:]  # 去掉 "Bearer " 前缀
        else:
            api_key = authorization
    
    # 如果没有 Authorization，则尝试 X-Api-Key
    if api_key is None and x_api_key:
        api_key = x_api_key
    
    if api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")


def generate_chunk(content: str, chunk_id: str, index: int = 0):
    """生成单个SSE chunk"""
    import json
    data = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": MODEL_NAME,
        "choices": [{
            "index": index,
            "delta": {"content": content},
            "finish_reason": None
        }]
    }
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def generate_done_chunk(chunk_id: str):
    """生成结束chunk"""
    import json
    data = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": MODEL_NAME,
        "choices": [{
            "index": 0,
            "delta": {},
            "finish_reason": "stop"
        }]
    }
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def generate_non_stream_response(content: str):
    """生成非流式响应的完整JSON"""
    import json
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": MODEL_NAME,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop"
        }],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": len(content),
            "total_tokens": len(content)
        }
    }


@app.get("/v1/models")
async def list_models():
    """返回可用模型列表"""
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_NAME,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "standalone_scripts"
            }
        ]
    }


from fastapi.responses import JSONResponse


@app.post("/v1/chat/completions")
async def chat_completions(
    body: dict,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None
):
    """流式返回作文内容"""
    # 验证API密钥
    verify_api_key(authorization, x_api_key)
    
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
    
    # 获取 stream 参数，默认为 True（保持向后兼容）
    stream = body.get("stream", True)
    
    if not stream:
        # 非流式响应：直接返回完整的 JSON
        return JSONResponse(content=generate_non_stream_response(ZuoWen_Content))
    
    # 流式响应：将作文内容按字符或词语分割成多个chunk进行流式返回
    # 使用词语分割，每10个字符为一个chunk，这样效果更好
    chunk_size = 10
    chunks = [ZuoWen_Content[i:i+chunk_size] for i in range(0, len(ZuoWen_Content), chunk_size)]
    
    async def generate_stream():
        # 首先发送一个带有role的chunk（可选，这里我们直接发送content）
        for i, chunk_content in enumerate(chunks):
            yield generate_chunk(chunk_content, chunk_id, index=0)
            # 模拟流式延迟，可选
            # await asyncio.sleep(0.01)
        
        # 发送最后一个chunk，包含finish_reason
        yield generate_done_chunk(chunk_id)
        
        # 发送结束标记
        yield "data: [DONE]\n\n"
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Request-ID": chunk_id
        }
    )


@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {"status": "ok"}


@app.post("/test")
async def test_model(
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None
):
    """测试接口 - 用于验证API密钥和模型是否正常工作
    
    通过此接口可以测试模型是否可用，不需要发送完整的请求体。
    成功时返回测试信息和模型状态。
    """
    # 验证API密钥
    verify_api_key(authorization, x_api_key)
    
    return {
        "status": "success",
        "message": "API密钥验证通过，模型正常工作",
        "model": MODEL_NAME,
        "api_key": "sk-abcdefgh"
    }


@app.get("/test")
async def test_model_get(
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None
):
    """测试接口 (GET) - 用于验证API密钥和模型是否正常工作"""
    # 验证API密钥
    verify_api_key(authorization, x_api_key)
    
    return {
        "status": "success",
        "message": "API密钥验证通过，模型正常工作 (GET)",
        "model": MODEL_NAME,
        "test_content_preview": ZuoWen_Content[:50] + "..."
    }


@app.get("/models")
async def models_endpoint():
    """/models 别名 - 返回可用模型列表（与 /v1/models 相同）"""
    return await list_models()


@app.get("/v1/models/{model_id}")
async def get_model_info(model_id: str):
    """获取特定模型的信息"""
    if model_id != MODEL_NAME:
        raise HTTPException(status_code=404, detail="Model not found")
    
    return {
        "id": MODEL_NAME,
        "object": "model",
        "created": int(time.time()),
        "owned_by": "standalone_scripts",
        "permission": [],
        "root": MODEL_NAME
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)