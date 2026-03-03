"""
retry_executor_node -- Reflection 실패 시 Fallback 도구를 실행하고 재합성 준비

reflector가 fail 판정 시 TOOL_FALLBACK_MAP에서 대안을 찾아 실행한다.
실행 후 final_response를 초기화하여 synthesizer가 다시 응답을 생성하도록 한다.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.state import AgentState


def retry_executor_node(state: AgentState) -> dict:
    """
    Fallback 도구를 실행하고 재합성을 위해 상태를 갱신한다.

    Returns:
        {
            "tool_results": updated_list,
            "final_response": "",
            "reflection_count": N+1,
        }
    """
    from bot_brain import log, execute_tool, truncate_json, _result_has_data
    from agent.constants import TOOL_FALLBACK_MAP as CONST_FALLBACK_MAP

    tool_results = list(state.get("tool_results", []))
    reflection_count = state.get("reflection_count", 0)
    chat_id = state.get("chat_id", "")

    # ── 진행 알림 ──
    _notify_progress(chat_id)

    # ── Fallback 도구 결정 (Reflector 힌트 우선) ──
    retry_tool = ""
    retry_args: dict = {}

    # 1순위: Reflector가 제안한 retry_tool/retry_args
    hint_tool = state.get("reflection_retry_tool")
    hint_args = state.get("reflection_retry_args")
    if hint_tool:
        tried_tools = {r.get("tool_name", "") for r in tool_results}
        # 이미 같은 도구+같은 인자로 시도했는지 확인
        already_tried_same = any(
            r.get("tool_name") == hint_tool
            and r.get("args") == hint_args
            for r in tool_results
        )
        if not already_tried_same:
            retry_tool = hint_tool
            retry_args = hint_args if isinstance(hint_args, dict) else {}
            log(f"[retry_executor] Reflector 힌트 사용: {retry_tool}({retry_args})")

    # 2순위: TOOL_FALLBACK_MAP 기반
    if not retry_tool:
        retry_tool, retry_args = _determine_retry(tool_results)

    if not retry_tool:
        log("[retry_executor] 재시도할 도구 없음 → 원본 응답 유지")
        return {
            "tool_results": tool_results,
            "final_response": state.get("final_response", ""),
            "reflection_count": reflection_count + 1,
        }

    log(f"[retry_executor] 재시도 실행: {retry_tool}({json.dumps(retry_args, ensure_ascii=False)[:200]})")

    # ── 도구 실행 ──
    try:
        result = execute_tool(retry_tool, retry_args)
        result_str = truncate_json(result)
        has_data = _result_has_data(result_str)

        new_result = {
            "tool_name": retry_tool,
            "args": retry_args,
            "result": result,
            "has_data": has_data,
            "error": None,
        }
        tool_results.append(new_result)

        if has_data:
            log(f"[retry_executor] 재시도 데이터 확보 (len={len(result_str)})")
        else:
            log(f"[retry_executor] 재시도 도구도 빈 결과")

    except Exception as e:
        log(f"[retry_executor] 재시도 실행 오류: {e}")
        new_result = {
            "tool_name": retry_tool,
            "args": retry_args,
            "result": None,
            "has_data": False,
            "error": str(e),
        }
        tool_results.append(new_result)

    return {
        "tool_results": tool_results,
        "final_response": "",  # 초기화하여 synthesizer가 재생성
        "reflection_count": reflection_count + 1,
    }


def _determine_retry(tool_results: list[dict]) -> tuple[str, dict]:
    """
    실패한 도구를 분석하여 Fallback 도구와 인자를 결정.

    Returns:
        (retry_tool_name, retry_args) 또는 ("", {})
    """
    from agent.constants import TOOL_FALLBACK_MAP as CONST_FALLBACK_MAP

    # 이미 실행된 도구
    tried_tools: set[str] = {r.get("tool_name", "") for r in tool_results}

    # 빈 결과인 도구에서 Fallback 찾기
    for r in tool_results:
        if not r.get("has_data") and not r.get("error"):
            tool_name = r.get("tool_name", "")
            fallbacks = CONST_FALLBACK_MAP.get(tool_name, [])
            for fb in fallbacks:
                if fb not in tried_tools:
                    # 원래 인자 기반으로 Fallback 인자 구성
                    original_args = r.get("args", {})
                    if isinstance(original_args, str):
                        try:
                            original_args = json.loads(original_args)
                        except (json.JSONDecodeError, TypeError):
                            original_args = {}
                    return fb, dict(original_args)

    # 에러가 발생한 도구에서 Fallback 찾기
    for r in tool_results:
        if r.get("error"):
            tool_name = r.get("tool_name", "")
            fallbacks = CONST_FALLBACK_MAP.get(tool_name, [])
            for fb in fallbacks:
                if fb not in tried_tools:
                    original_args = r.get("args", {})
                    if isinstance(original_args, str):
                        try:
                            original_args = json.loads(original_args)
                        except (json.JSONDecodeError, TypeError):
                            original_args = {}
                    return fb, dict(original_args)

    return "", {}


def _notify_progress(chat_id: str) -> None:
    """재시도 진행 알림."""
    if not chat_id:
        return
    try:
        from bot_brain import _send_message_impl
        _send_message_impl(chat_id, "\ud83d\udd04 추가 검색 중...")
    except Exception:
        pass
