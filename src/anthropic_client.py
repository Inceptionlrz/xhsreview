"""
Anthropic Messages API 客户端
支持自定义 URL 和 API Key，标准 Anthropic Messages 协议
"""

import json
import time
import random
import threading
import requests
from typing import Optional, Dict, Any, Generator


class AnthropicClient:
    """Anthropic Messages API 客户端"""

    def __init__(self, base_url: str, api_key: str, model: str = "claude-3-5-sonnet-20241022",
                 timeout: int = 60, max_retries: int = 3, proxy: str = ""):
        self.base_url = (base_url or "https://api.anthropic.com").rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.proxy = proxy  # 格式: "127.0.0.1:7897" 或 ""
        self._lock = threading.Lock()
        self.last_error: Optional[str] = None
        self.total_calls = 0
        self.total_tokens_in = 0
        self.total_tokens_out = 0

    def update(self, base_url: str = None, api_key: str = None, model: str = None, proxy: str = None):
        if base_url is not None:
            self.base_url = base_url.rstrip("/")
        if api_key is not None:
            self.api_key = api_key
        if model is not None:
            self.model = model
        if proxy is not None:
            self.proxy = proxy

    def _headers(self) -> Dict[str, str]:
        # 同时发送 x-api-key（Anthropic 官方）和 Authorization: Bearer（中转站/OpenAI 兼容）
        # 官方 API 忽略 Authorization 头，中转站忽略 x-api-key 头，两者兼容
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key or "",
            "Authorization": f"Bearer {self.api_key}" if self.api_key else "",
            "anthropic-version": "2023-06-01",
            "anthropic-dangerous-direct-browser-access": "true",  # 兼容中转
        }

    def _endpoint(self) -> str:
        # 兼容各种 URL 格式：
        #   https://api.anthropic.com          -> /v1/messages
        #   https://relay.com/v1               -> /messages
        #   https://relay.com/v1/messages      -> 原样使用
        #   https://relay.com/messages         -> 原样使用
        url = self.base_url
        if url.endswith("/messages"):
            return url
        if url.endswith("/v1"):
            return f"{url}/messages"
        if url.endswith("/v1/messages"):
            return url
        return f"{url}/v1/messages"

    def _proxies(self) -> Optional[Dict[str, str]]:
        """返回 requests proxies 参数"""
        if not self.proxy:
            return None
        p = self.proxy.strip()
        if not p:
            return None
        if not p.startswith("http"):
            p = f"http://{p}"
        return {"http": p, "https": p}

    def test_connection(self) -> tuple[bool, str]:
        """发送最小请求测试连通性"""
        if not self.api_key:
            return False, "API Key 为空"
        payload = {
            "model": self.model,
            "max_tokens": 16,
            "messages": [{"role": "user", "content": "ping"}],
        }
        try:
            r = requests.post(
                self._endpoint(),
                headers=self._headers(),
                json=payload,
                timeout=min(self.timeout, 20),
                proxies=self._proxies(),
            )
            if r.status_code == 200:
                return True, "连接成功"
            # 智能错误诊断
            body = r.text[:300]
            hint = ""
            if r.status_code == 401:
                # 判断是官方还是中转站
                if '"type":"error"' in body or '"authentication_error"' in body:
                    hint = "\n\n【诊断】Anthropic 官方 API 拒绝了 Key，请检查 Key 是否正确（以 sk-ant- 开头）。"
                else:
                    hint = ("\n\n【诊断】检测到中转站/代理服务。已自动发送 Authorization: Bearer + x-api-key 双头认证。\n"
                            "如果仍然 401，请检查：\n"
                            "1. Key 是否正确（中转站 Key 通常不以 sk-ant- 开头）\n"
                            "2. API URL 是否正确（中转站地址通常不是 api.anthropic.com）\n"
                            "3. 账户余额/额度是否充足")
            elif r.status_code == 404:
                hint = "\n\n【诊断】端点路径不存在。请检查 API URL 是否正确，代码会自动拼接 /v1/messages。"
            elif r.status_code == 429:
                hint = "\n\n【诊断】请求频率超限，Key 本身有效，稍后重试即可。"
            return False, f"HTTP {r.status_code}: {body}{hint}"
        except Exception as e:
            return False, f"连接失败: {e}"

    def generate_reply(self, post_title: str, post_content: str,
                       persona: str = "友好、有趣的小红书用户",
                       max_tokens: int = 256,
                       temperature: float = 0.85) -> Optional[str]:
        """根据帖子内容生成回复"""
        with self._lock:
            self.total_calls += 1

        system_prompt = (
            f"你是一个{persona}。你会针对小红书上的帖子写一条像真人随手发的短回复。\n"
            f"语气要求（非常重要）：\n"
            f"1. 必须口语化、接地气，像随手刷到顺手评论，不要用书面语、不要用「首先/其次/总之」这类结构；\n"
            f"2. 长度 1 句话为主，偶尔 2 句，多数在 10-40 字之间，不要太长太工整；\n"
            f"3. 可以带点个人情绪（赞同/惊讶/共鸣/调侃/疑惑都行），但不要每句都热情洋溢；\n"
            f"4. 允许偶尔用网络用语、缩写、语气词（如 哈哈、绝了、这也太、求链接），偶尔漏个标点或用个～也没事；\n"
            f"5. 不要重复原帖内容，不要说教，更不要说自己是 AI 或助手；\n"
            f"6. 偶尔（约两成）也可以只回一两个词或一个 emoji 表达情绪，不用硬凑句子；\n"
            f"7. 直接输出回复内容，不要任何前缀、引号或解释。"
        )
        user_prompt = (
            f"【帖子标题】{post_title or '(无标题)'}\n"
            f"【帖子正文】{post_content or '(无正文)'}\n\n"
            f"请针对这个帖子写一条回复："
        )
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }

        for attempt in range(self.max_retries):
            try:
                r = requests.post(
                    self._endpoint(),
                    headers=self._headers(),
                    json=payload,
                    timeout=self.timeout,
                    proxies=self._proxies(),
                )
                if r.status_code == 200:
                    data = r.json()
                    # Anthropic Messages 格式: content[].text
                    contents = data.get("content", [])
                    text_parts = []
                    for c in contents:
                        if c.get("type") == "text":
                            text_parts.append(c.get("text", ""))
                    text = "".join(text_parts).strip()
                    usage = data.get("usage", {})
                    self.total_tokens_in += usage.get("input_tokens", 0)
                    self.total_tokens_out += usage.get("output_tokens", 0)
                    self.last_error = None
                    return text
                else:
                    self.last_error = f"HTTP {r.status_code}: {r.text[:200]}"
                    if r.status_code in (401, 403):
                        return None  # 鉴权问题不重试
                    time.sleep(1.0 * (attempt + 1))
            except requests.exceptions.Timeout:
                self.last_error = "请求超时"
                time.sleep(1.5)
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
                time.sleep(1.0 * (attempt + 1))
        return None

    def humanize_reply(self, text: str, hz: Optional[Dict[str, Any]] = None) -> str:
        """对 AI 生成的回复做内容层拟人后处理（防「AI 味」与人工审核）。

        所有变换均不改变语义主体，只是让文本更像真人随手打的：
          - 偶发轻微错别字（同音/形近，净效果不影响理解）
          - 偶发追加 1 个随机 emoji
          - 偶发只保留前半句（短评更真实）
          - 偶发标点波动（去掉结尾句号 / 换成 ~ 或 ！）
        hz 取不到对应旋钮时回退到安全默认值。
        """
        if not text or not text.strip():
            return text
        hz = hz or {}
        try:
            # 1) 偶发截断为短评（只留第一句 / 前 N 字）
            if random.random() < float(hz.get("content_truncate_rate", 0.12)):
                cut = text.split("。")[0].split("！")[0].split("?")[0].split("？")[0]
                cut = cut.strip()
                if len(cut) >= 4:
                    text = cut

            # 2) 偶发轻微错别字（同音/形近替换 1 处）
            if random.random() < float(hz.get("content_typo_rate", 0.15)):
                typo_map = [
                    ("的", "地"), ("地", "的"), ("在", "再"), ("再", "在"),
                    ("吧", "把"), ("吗", "嘛"), ("呢", "呐"), ("这", "这"),
                    ("已", "以"), ("以", "已"), ("他", "她"), ("她", "他"),
                ]
                for a, b in typo_map:
                    idx = text.find(a)
                    if idx >= 0 and random.random() < 0.5:
                        text = text[:idx] + b + text[idx + len(a):]
                        break

            # 3) 偶发追加 1 个随机 emoji
            if random.random() < float(hz.get("content_emoji_rate", 0.50)):
                emojis = ["😂", "✨", "🥺", "👍", "🔥", "💡", "🤔", "😭", "🌝", "🙈", "💯", "🥹"]
                text = text.rstrip("。.!！?？~ ") + random.choice(emojis)

            # 4) 偶发标点波动（去掉生硬结尾句号 / 换成 ~ 或 ！）
            if random.random() < 0.35:
                t = text.rstrip("。.!！?？~ ")
                if random.random() < 0.5:
                    text = t + "～"
                else:
                    text = t + "！"

            return text.strip()
        except Exception:
            return text

    def stats(self) -> Dict[str, Any]:
        return {
            "calls": self.total_calls,
            "tokens_in": self.total_tokens_in,
            "tokens_out": self.total_tokens_out,
            "last_error": self.last_error,
        }
