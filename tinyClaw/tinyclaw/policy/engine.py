"""
安全策略引擎
============
在工具执行前检查权限。支持三种资源类型：
- filesystem: 文件系统访问控制
- network: 网络请求控制
- tools: 工具调用控制

规则按优先级排序，第一个匹配的规则生效。
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class PolicyRule:
    """
    策略规则。

    属性:
        id: 规则唯一标识
        action: 动作（allow / deny / sandbox）
        resource: 资源匹配模式（工具名 / 路径模式 / * 匹配所有）
        condition: 条件表达式（简单字符串匹配）
        priority: 优先级（数字越大优先级越高）
        description: 规则描述
    """
    id: str
    action: str          # allow / deny / sandbox
    resource: str        # 匹配的资源模式
    condition: str       # 条件表达式
    priority: int = 0
    description: str = ""


class PolicyEngine:
    """
    安全策略引擎。

    在工具执行前检查是否允许操作。
    规则按优先级降序排列，第一个匹配的规则生效。
    """

    def __init__(self, rules_path: str | Path | None = None):
        """
        初始化策略引擎。

        参数:
            rules_path: 自定义规则文件路径（JSON 格式）
        """
        self.rules: list[PolicyRule] = []
        if rules_path and Path(rules_path).exists():
            self._load_rules_from_file(Path(rules_path))
        else:
            self._load_default_rules()

    def _load_default_rules(self) -> None:
        """加载默认安全策略。"""
        self.rules = [
            # 禁止删除根目录
            PolicyRule(
                id="deny-rm-rf", action="deny", resource="bash",
                condition="rm -rf /", priority=100,
                description="禁止删除根目录",
            ),
            # 禁止访问 /etc/shadow
            PolicyRule(
                id="deny-shadow", action="deny", resource="bash",
                condition="/etc/shadow", priority=100,
                description="禁止访问 /etc/shadow",
            ),
            # 危险命令沙盒化
            PolicyRule(
                id="sandbox-curl", action="sandbox", resource="bash",
                condition="curl ", priority=50,
                description="curl 命令在沙盒中执行",
            ),
            PolicyRule(
                id="sandbox-wget", action="sandbox", resource="bash",
                condition="wget ", priority=50,
                description="wget 命令在沙盒中执行",
            ),
            # 默认允许
            PolicyRule(
                id="allow-all", action="allow", resource="*",
                condition="", priority=0,
                description="默认允许所有操作",
            ),
        ]
        self.rules.sort(key=lambda r: r.priority, reverse=True)

    def _load_rules_from_file(self, path: Path) -> None:
        """从 JSON 文件加载策略规则。"""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            rules_data = data.get("rules", [])
            self.rules = [
                PolicyRule(
                    id=r.get("id", ""),
                    action=r.get("action", "allow"),
                    resource=r.get("resource", "*"),
                    condition=r.get("condition", ""),
                    priority=r.get("priority", 0),
                    description=r.get("description", ""),
                )
                for r in rules_data
            ]
            self.rules.sort(key=lambda r: r.priority, reverse=True)
        except Exception as e:
            print(f"  [warn] 加载策略规则文件失败: {e}")
            self._load_default_rules()

    def add_rule(self, rule: PolicyRule) -> None:
        """添加一条新规则并重新排序。"""
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.priority, reverse=True)

    def remove_rule(self, rule_id: str) -> bool:
        """移除指定规则。"""
        original_len = len(self.rules)
        self.rules = [r for r in self.rules if r.id != rule_id]
        return len(self.rules) < original_len

    def check(self, tool_name: str, arguments: dict) -> tuple[str, str]:
        """
        检查工具调用是否被允许。

        参数:
            tool_name: 工具名称
            arguments: 工具参数

        返回:
            (action, reason) 元组
            action: "allow" / "deny" / "sandbox"
        """
        args_str = json.dumps(arguments, ensure_ascii=False)

        for rule in self.rules:
            # 检查资源匹配
            if rule.resource != "*" and rule.resource != tool_name:
                continue
            # 检查条件匹配
            if rule.condition and rule.condition not in args_str:
                continue
            # 匹配成功
            return rule.action, rule.description

        return "allow", "无匹配规则，默认允许"

    def list_rules(self) -> str:
        """列出所有策略规则。"""
        if not self.rules:
            return "没有策略规则"
        lines = []
        for r in self.rules:
            lines.append(
                f"  [{r.id}] {r.action} | resource={r.resource} | "
                f"priority={r.priority} | {r.description}"
            )
        return "\n".join(lines)
