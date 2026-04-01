"""
钩子系统模块
============
定义 6 个生命周期钩子点，支持注册/注销处理器，链式触发。
"""

from typing import Callable

# 定义 6 个钩子点
HOOK_POINTS = [
    "before_system_prompt",   # 构建系统提示词之前
    "after_system_prompt",    # 构建系统提示词之后
    "before_model_call",      # 调用模型之前
    "after_model_call",       # 调用模型之后
    "before_tool_call",       # 执行工具之前
    "after_tool_call",        # 执行工具之后
]


class HookSystem:
    """
    钩子系统：在 Agent 生命周期的关键节点触发钩子。

    钩子处理器签名: handler(hook_point: str, data: dict) -> dict | None
    处理器可以修改 data 并返回，链式传递给下一个处理器。
    """

    def __init__(self):
        self._hooks: dict[str, list[Callable]] = {hp: [] for hp in HOOK_POINTS}

    def register(self, hook_point: str, handler: Callable) -> None:
        """
        注册一个钩子处理器。

        参数:
            hook_point: 钩子点名称
            handler: 处理器函数
        """
        if hook_point not in self._hooks:
            print(f"  [warn] 未知钩子点: {hook_point}，可用: {', '.join(HOOK_POINTS)}")
            return
        self._hooks[hook_point].append(handler)

    def unregister(self, hook_point: str, handler: Callable) -> None:
        """取消注册一个钩子处理器。"""
        if hook_point in self._hooks and handler in self._hooks[hook_point]:
            self._hooks[hook_point].remove(handler)

    def fire(self, hook_point: str, data: dict) -> dict:
        """
        触发指定钩子点的所有处理器。

        处理器链式执行：每个处理器可以修改 data 并返回，
        返回的 dict 将传递给下一个处理器。

        参数:
            hook_point: 钩子点名称
            data: 传递给处理器的数据

        返回:
            经过所有处理器处理后的数据
        """
        if hook_point not in self._hooks:
            return data
        for handler in self._hooks[hook_point]:
            try:
                result = handler(hook_point, data)
                if isinstance(result, dict):
                    data = result
            except Exception as e:
                print(f"  [warn] 钩子处理器出错 ({hook_point}): {e}")
        return data

    def list_hooks(self) -> str:
        """列出所有已注册的钩子及其处理器数量。"""
        lines = []
        for hp in HOOK_POINTS:
            handlers = self._hooks.get(hp, [])
            count = len(handlers)
            lines.append(f"  {hp}: {count} 个处理器")
        return "\n".join(lines)

    def clear(self, hook_point: str | None = None) -> None:
        """
        清空钩子处理器。

        参数:
            hook_point: 指定钩子点（留空清空所有）
        """
        if hook_point:
            if hook_point in self._hooks:
                self._hooks[hook_point].clear()
        else:
            for hp in HOOK_POINTS:
                self._hooks[hp].clear()
