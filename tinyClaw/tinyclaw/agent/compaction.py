"""
上下文压缩模块
==============
提供 token 估算、文本截断、对话上下文摘要压缩功能。
"""

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tinyclaw.provider.openai_compat import OpenAICompatProvider


def estimate_tokens(text: str) -> int:
    """
    粗略估算 token 数量。

    中文字符按 1.5 字符/token，其他字符按 4 字符/token。
    """
    if not text:
        return 0
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    other_chars = len(text) - chinese_chars
    return int(chinese_chars / 1.5 + other_chars / 4)


def messages_token_count(messages: list[dict]) -> int:
    """计算消息列表的总 token 数量。"""
    total = 0
    for msg in messages:
        if isinstance(msg, dict):
            content = msg.get("content", "")
            if content:
                total += estimate_tokens(content)
        else:
            content = getattr(msg, "content", "") or ""
            total += estimate_tokens(content)
    return total


def micro_compact(text: str, max_len: int = 4096) -> str:
    """截断过长文本，保留首尾。"""
    if len(text) <= max_len:
        return text
    half = max_len // 2
    return text[:half] + f"\n...[截断 {len(text) - max_len} 字符]...\n" + text[-half:]


def compact_messages(
    messages: list[dict],
    target_tokens: int = 20000,
    provider: "OpenAICompatProvider | None" = None,
) -> list[dict]:
    """
    压缩对话上下文：将旧消息摘要化，保留最近消息。

    参数:
        messages: 完整消息列表
        target_tokens: 目标 token 数量
        provider: LLM Provider，用于生成摘要

    返回:
        压缩后的消息列表
    """
    if len(messages) <= 5:
        return messages

    system_msg = messages[0] if messages[0].get("role") == "system" else None
    non_system = messages[1:] if system_msg else messages
    keep_recent = 8

    if len(non_system) <= keep_recent:
        return messages

    old_messages = non_system[:-keep_recent]
    recent_messages = non_system[-keep_recent:]

    # 构建旧消息文本用于摘要
    conversation_text = ""
    for msg in old_messages:
        content = msg.get("content", "")
        if content:
            conversation_text += f"[{msg.get('role', '?')}]: {content[:500]}\n"

    # 生成摘要
    summary = _generate_summary(conversation_text, provider)

    result = []
    if system_msg:
        result.append(system_msg)
    result.append({"role": "user", "content": f"[之前对话摘要]\n{summary}\n[摘要结束]"})
    result.extend(recent_messages)
    return result


def _generate_summary(
    conversation_text: str,
    provider: "OpenAICompatProvider | None" = None,
) -> str:
    """生成对话摘要。"""
    if provider is None:
        # 无 Provider 时做简单截断
        lines = conversation_text.split("\n")
        selected = lines[:10]
        return "（简易摘要）\n" + "\n".join(selected)

    try:
        summary = provider.simple_complete(
            prompt=conversation_text[:3000],
            system="将以下对话摘要为简洁要点，保留关键信息，200字以内。",
            max_tokens=300,
        )
        return summary or "(摘要失败)"
    except Exception as e:
        return f"(摘要出错: {e})"
