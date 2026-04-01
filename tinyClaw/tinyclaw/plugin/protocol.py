"""
JSON-RPC 2.0 协议编解码
========================
提供 JSON-RPC 2.0 请求、通知的构造和响应解析函数。
"""

import json


def make_jsonrpc_request(method: str, params: dict, req_id: int) -> str:
    """
    构造 JSON-RPC 2.0 请求字符串。

    参数:
        method: 方法名
        params: 参数字典
        req_id: 请求 ID

    返回:
        JSON 字符串
    """
    request = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": method,
        "params": params,
    }
    return json.dumps(request, ensure_ascii=False)


def make_jsonrpc_notification(method: str, params: dict) -> str:
    """
    构造 JSON-RPC 2.0 通知字符串（无 id）。

    参数:
        method: 方法名
        params: 参数字典

    返回:
        JSON 字符串
    """
    notification = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
    }
    return json.dumps(notification, ensure_ascii=False)


def parse_jsonrpc_response(line: str) -> dict | None:
    """
    解析 JSON-RPC 2.0 响应。

    参数:
        line: 原始 JSON 行

    返回:
        解析后的字典，或 None（解析失败）
    """
    try:
        data = json.loads(line.strip())
    except json.JSONDecodeError:
        return None
    if "jsonrpc" not in data or data["jsonrpc"] != "2.0":
        return None
    return data


def make_jsonrpc_error(req_id: int | None, code: int, message: str, data: dict | None = None) -> str:
    """
    构造 JSON-RPC 2.0 错误响应。

    参数:
        req_id: 请求 ID
        code: 错误码
        message: 错误描述
        data: 附加错误数据

    返回:
        JSON 字符串
    """
    error: dict = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    response = {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": error,
    }
    return json.dumps(response, ensure_ascii=False)


def make_jsonrpc_result(req_id: int, result: dict) -> str:
    """
    构造 JSON-RPC 2.0 成功响应。

    参数:
        req_id: 请求 ID
        result: 结果字典

    返回:
        JSON 字符串
    """
    response = {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": result,
    }
    return json.dumps(response, ensure_ascii=False)
