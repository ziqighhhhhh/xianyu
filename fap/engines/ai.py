"""OpenAI-compatible AI reply helper."""

from __future__ import annotations

import json

import httpx

from .. import db, knowledge

DEFAULT_SYSTEM_PROMPT = (
    "你是闲鱼店铺的客服助手。回答要简洁、礼貌、口语化，不要编造订单、物流或库存信息；"
    "不确定时请让买家稍等并转人工。"
)


class AIError(Exception):
    pass


def config(conn) -> dict:
    return {
        "enabled": db.get_setting(conn, "ai_enabled", "0") == "1",
        "base_url": db.get_setting(conn, "ai_base_url", "https://api.openai.com/v1").rstrip("/"),
        "api_key": db.get_setting(conn, "ai_api_key", ""),
        "model": db.get_setting(conn, "ai_model", "gpt-4o-mini"),
        "system_prompt": db.get_setting(conn, "ai_system_prompt", DEFAULT_SYSTEM_PROMPT),
        "kb_id": int(db.get_setting(conn, "ai_kb_id", "0") or 0) or None,
    }


def chat(conn, messages: list[dict], timeout: float = 30.0) -> str:
    cfg = config(conn)
    if not cfg["api_key"]:
        raise AIError("未配置 AI API Key")
    url = cfg["base_url"] + "/chat/completions"
    payload = {"model": cfg["model"], "messages": messages, "temperature": 0.6}
    headers = {"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise AIError(f"AI 请求失败: {exc}") from exc
    if resp.status_code >= 400:
        raise AIError(f"AI 接口返回 {resp.status_code}: {resp.text[:300]}")
    try:
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except (ValueError, KeyError, IndexError) as exc:
        raise AIError(f"AI 响应格式异常: {resp.text[:300]}") from exc


def reply(conn, text: str, history: list[dict] | None = None, goods: dict | None = None) -> str:
    cfg = config(conn)
    messages = [{"role": "system", "content": cfg["system_prompt"]}]
    if goods:
        messages.append({
            "role": "system",
            "content": (
                f"当前商品：{goods.get('title', '')}\n"
                f"价格：{goods.get('price', '')}\n"
                f"描述：{goods.get('description', '')}"
            ),
        })
    for item in (history or [])[-10:]:
        role = "assistant" if item.get("direction") == "out" else "user"
        messages.append({"role": role, "content": item.get("content", "")})
    if cfg["kb_id"]:
        query = " ".join(filter(None, [goods.get("title", "") if goods else "", text]))
        context = knowledge.build_context(conn, query, cfg["kb_id"], limit=3)
        if context:
            messages.append({
                "role": "system",
                "content": (
                    "以下是从店铺知识库检索到的参考资料。只在与买家问题相关时使用，"
                    "不要编造资料中没有的信息：\n" + context
                ),
            })
    messages.append({"role": "user", "content": text})
    return chat(conn, messages)


def test(conn) -> dict:
    cfg = config(conn)
    if not cfg["api_key"]:
        raise AIError("未配置 AI API Key")
    answer = chat(conn, [
        {"role": "system", "content": "你是连通性测试助手，只回复 OK。"},
        {"role": "user", "content": "ping"},
    ], timeout=20)
    return {"model": cfg["model"], "base_url": cfg["base_url"], "answer": answer}
