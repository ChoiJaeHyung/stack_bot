"""
도구 레지스트리 — 동적 도구 선택 + execute_tool / stack_api 래핑

bot_brain.py의 TOOLS, execute_tool, stack_api 등을 import하여 사용한다.
도메인 필터링으로 75개 도구를 10~25개로 축소하여 토큰 절감.
"""

from __future__ import annotations

import sys
import os
import json
from typing import Any

# bot_brain.py가 있는 디렉토리를 path에 추가
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)

from agent.constants import DOMAIN_GROUPS, ALWAYS_INCLUDE_DOMAINS


def _get_all_tools() -> list[dict]:
    """bot_brain.py에서 TOOLS 리스트를 가져온다."""
    from bot_brain import TOOLS
    return TOOLS


def get_tool_name(tool_def: dict) -> str:
    """도구 정의에서 이름 추출."""
    return tool_def.get("function", {}).get("name", "")


def get_tools_for_domains(domains: list[str]) -> list[dict]:
    """
    필요한 도메인의 도구만 반환.
    항상 memory + user_engineer 도메인은 포함.

    Args:
        domains: 활성 도메인 리스트 (예: ["checkup", "maintenance_contract"])

    Returns:
        도메인 필터링된 TOOLS 리스트 (75개 → 10~25개)
    """
    target_domains = set(domains) | ALWAYS_INCLUDE_DOMAINS

    # 대상 도메인에 속하는 도구 이름 수집
    target_tool_names: set[str] = set()
    for domain in target_domains:
        tool_names = DOMAIN_GROUPS.get(domain, [])
        target_tool_names.update(tool_names)

    # 내부 전용 도구 추가 (_combined_expiring_contracts 등은 TOOLS에 없으므로 무시)
    all_tools = _get_all_tools()
    filtered = [
        t for t in all_tools
        if get_tool_name(t) in target_tool_names
    ]

    return filtered


def get_all_domain_tool_names() -> set[str]:
    """모든 도메인의 도구 이름 집합."""
    names: set[str] = set()
    for tools in DOMAIN_GROUPS.values():
        names.update(tools)
    return names


def call_execute_tool(name: str, args: dict) -> Any:
    """bot_brain.py의 execute_tool() 래핑."""
    from bot_brain import execute_tool
    return execute_tool(name, args)


def call_stack_api(method: str, path: str, **kwargs) -> Any:
    """bot_brain.py의 stack_api() 래핑."""
    from bot_brain import stack_api
    return stack_api(method, path, **kwargs)


def truncate_result(data: Any, max_len: int | None = None) -> str:
    """bot_brain.py의 truncate_json() 래핑."""
    from bot_brain import truncate_json
    return truncate_json(data, max_len=max_len)


def result_has_data(content: Any) -> bool:
    """bot_brain.py의 _result_has_data() 래핑."""
    from bot_brain import _result_has_data
    return _result_has_data(content)


def normalize_api_response(result: Any) -> dict:
    """
    STACK API 응답 형식 5종을 정규화.

    입력 형식:
    1. {"data": [...]}
    2. {"data": {"items": [...], "totalElements": N}}
    3. {"content": [...]}
    4. 직접 배열 [...]
    5. {"error": "..."}

    출력: {"items": list, "total": int, "error": str|None}
    """
    if result is None:
        return {"items": [], "total": 0, "error": "No response"}

    # 형식 5: 에러
    if isinstance(result, dict) and result.get("error"):
        return {"items": [], "total": 0, "error": str(result["error"])}

    # 형식 4: 직접 배열
    if isinstance(result, list):
        return {"items": result, "total": len(result), "error": None}

    if not isinstance(result, dict):
        return {"items": [], "total": 0, "error": f"Unexpected type: {type(result)}"}

    # 형식 1: {"data": [...]}
    data = result.get("data")
    if data is not None:
        if isinstance(data, list):
            return {"items": data, "total": len(data), "error": None}
        # 형식 2: {"data": {"items": [...], "totalElements": N}}
        if isinstance(data, dict):
            items = data.get("items", [])
            if not isinstance(items, list):
                items = []
            total = data.get("totalElements", len(items))
            return {"items": items, "total": total, "error": None}

    # 형식 3: {"content": [...]} (Spring Page)
    for alt_key in ("content", "items", "list", "contracts", "results"):
        alt_val = result.get(alt_key)
        if alt_val and isinstance(alt_val, list):
            total = result.get("totalElements", len(alt_val))
            return {"items": alt_val, "total": total, "error": None}

    # 단일 객체 응답 (get_customer 등)
    if "id" in result or "name" in result:
        return {"items": [result], "total": 1, "error": None}

    # 기타 - 데이터는 있지만 형식 불명
    return {"items": [], "total": 0, "error": None}
