"""
executor 노드 — OpenAI Function Calling 루프 실행

plan의 각 단계를 실행한다:
  - tool="__fc_loop__": OpenAI FC 루프 (bot_brain.py의 메인 루프와 동일)
  - tool=명시적 도구명: execute_tool()로 직접 호출
"""

from __future__ import annotations

import json
import traceback
from typing import Any


def _extract_tools_from_messages(oai_messages: list[dict]) -> list[dict]:
    """
    oai_messages[0]에 planner가 저장한 _tools 메타데이터를 추출.
    없으면 전체 TOOLS를 반환한다.
    """
    if oai_messages and "_tools" in oai_messages[0]:
        return oai_messages[0]["_tools"]

    from bot_brain import TOOLS
    return TOOLS


def _run_fc_loop(
    oai_messages: list[dict],
    tools: list[dict],
    max_turns: int,
    complexity_level: str,
    has_plan: bool,
    instruction: str,
    chat_id: str,
    plan: list[dict],
) -> tuple[list[dict], list[dict], int, str]:
    """
    OpenAI Function Calling 루프 실행.

    Args:
        oai_messages: 현재 메시지 히스토리 (수정됨)
        tools: 도메인 필터링된 TOOLS
        max_turns: 최대 턴 수
        complexity_level: SIMPLE/MODERATE/COMPLEX
        has_plan: COMPLEX 계획 존재 여부
        instruction: 원본 지시사항
        chat_id: Google Chat space name
        plan: 실행 계획 리스트

    Returns:
        (tool_results, oai_messages, fc_turn_count, final_response)
    """
    from bot_brain import (
        log, execute_tool, truncate_json, _verify_step_result,
        client, OPENAI_MODEL, OPENAI_MAX_TOKENS,
    )
    from gchat_sender import _send_message_impl

    tool_results: list[dict] = []
    final_response = ""
    # 중복 호출 감지용: (tool_name, args_json) → 호출 횟수
    _call_history: dict[str, int] = {}

    for turn in range(max_turns):
        # 첫 턴: 반드시 도구 호출 강제 / 이후: auto
        tc = "required" if turn == 0 else "auto"
        log(f"[executor] FC turn {turn + 1}/{max_turns} (tool_choice={tc})")

        # _tools 메타데이터 제거한 clean messages 생성
        clean_messages = []
        for msg in oai_messages:
            if isinstance(msg, dict) and "_tools" in msg:
                clean_msg = {k: v for k, v in msg.items() if k != "_tools"}
                clean_messages.append(clean_msg)
            else:
                clean_messages.append(msg)

        try:
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=clean_messages,
                tools=tools,
                tool_choice=tc,
                temperature=0.3,
                max_tokens=OPENAI_MAX_TOKENS,
            )
            log(f"[executor] FC turn {turn + 1} response OK")
        except Exception as e:
            final_response = f"OpenAI API 오류: {e}"
            log(f"[executor] OpenAI API error on turn {turn + 1}: {e}")
            log(traceback.format_exc())
            break

        choice = response.choices[0]
        msg = choice.message

        # 도구 호출이 없으면 최종 응답
        if not msg.tool_calls:
            final_response = msg.content or ""
            log(f"[executor] 최종 응답 수신 (len={len(final_response)})")
            break

        # 도구 호출 처리
        oai_messages.append(msg)
        log(f"[executor] {len(msg.tool_calls)} tool call(s) on turn {turn + 1}")

        for tool_call in msg.tool_calls:
            fn_name = tool_call.function.name
            try:
                fn_args = (
                    json.loads(tool_call.function.arguments)
                    if tool_call.function.arguments
                    else {}
                )
            except json.JSONDecodeError:
                fn_args = {}

            log(f"[executor] Tool call: {fn_name}({fn_args})")

            # ── 중복 호출 감지 ──
            call_key = f"{fn_name}:{json.dumps(fn_args, sort_keys=True)}"
            _call_history[call_key] = _call_history.get(call_key, 0) + 1

            if _call_history[call_key] > 1:
                # 동일 도구+인자 2회 이상 → API 호출 스킵
                log(f"[executor] 중복 호출 감지: {fn_name}({fn_args}) - {_call_history[call_key]}회째 → 스킵")
                dup_msg = (
                    f"[중복 호출 차단] {fn_name}은 동일 인자로 이미 호출되어 "
                    f"같은 결과를 반환했습니다. 같은 도구를 반복 호출해도 결과가 달라지지 않습니다. "
                    f"다른 도구를 사용하거나, 이전 결과를 기반으로 답변하세요."
                )
                oai_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": dup_msg,
                })
                tool_results.append({
                    "tool_name": fn_name,
                    "args": fn_args,
                    "result": dup_msg[:500],
                    "has_data": False,
                    "error": "duplicate_call",
                })
                continue

            try:
                result = execute_tool(fn_name, fn_args)
            except Exception as e:
                log(f"[executor] execute_tool({fn_name}) CRASHED: {e}")
                log(traceback.format_exc())
                result = {"error": f"Tool execution failed: {e}"}

            result_str = truncate_json(result)

            # 도구 결과를 oai_messages에 추가
            oai_messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result_str,
            })

            # 결과 축적
            from bot_brain import _result_has_data
            has_data = _result_has_data(result_str)
            tool_results.append({
                "tool_name": fn_name,
                "args": fn_args,
                "result": result_str[:500],
                "has_data": has_data,
                "error": result.get("error") if isinstance(result, dict) else None,
            })

            # COMPLEX 단계별 검증
            if has_plan and complexity_level == "COMPLEX":
                step_ok, suggestion = _verify_step_result(
                    fn_name, fn_args, result, instruction
                )
                if not step_ok and suggestion:
                    log(f"[executor] 단계 검증 실패: {fn_name} → {suggestion}")
                    oai_messages.append({
                        "role": "user",
                        "content": (
                            f"[시스템 힌트] {fn_name} 결과가 비어있습니다. "
                            f"{suggestion}"
                        ),
                    })

        # 중간 경과 보고
        if has_plan and turn > 0:
            step_idx = min(turn + 1, len(plan))
            try:
                _send_message_impl(chat_id, f"({step_idx}/{len(plan)} 단계 완료...)")
            except Exception:
                pass
        elif turn == 1:
            try:
                _send_message_impl(chat_id, "데이터 분석 중...")
            except Exception as e:
                log(f"[executor] progress message send FAILED: {e}")

    # for 루프가 0회 실행되면 turn 변수가 정의되지 않음
    try:
        fc_turn_count = turn + 1
    except NameError:
        fc_turn_count = 0

    return tool_results, oai_messages, fc_turn_count, final_response


def _run_explicit_tool(
    tool_name: str,
    args_hint: str,
    instruction: str,
    user_identity: dict | None,
) -> dict:
    """
    명시적 도구를 직접 실행.

    Returns:
        tool_result dict
    """
    from bot_brain import log, execute_tool, truncate_json, _result_has_data

    # args_hint에서 인자 추출 시도
    args: dict = {}
    if args_hint:
        try:
            args = json.loads(args_hint)
        except (json.JSONDecodeError, TypeError):
            pass

    # 사용자 UUID 주입 (assigneeId 등)
    if user_identity and user_identity.get("uuid"):
        uuid = user_identity["uuid"]
        if "assignee" in tool_name.lower() or "assignee" in str(args_hint).lower():
            if "assigneeId" not in args and "assignee" not in args:
                args["assigneeId"] = uuid

    log(f"[executor] 명시적 도구 실행: {tool_name}({args})")

    try:
        result = execute_tool(tool_name, args)
    except Exception as e:
        log(f"[executor] execute_tool({tool_name}) CRASHED: {e}")
        result = {"error": f"Tool execution failed: {e}"}

    result_str = truncate_json(result)
    has_data = _result_has_data(result_str)

    return {
        "tool_name": tool_name,
        "args": args,
        "result": result_str[:500],
        "has_data": has_data,
        "error": result.get("error") if isinstance(result, dict) else None,
    }


def executor_node(state: dict) -> dict:
    """
    실행 계획의 현재 단계를 수행.

    - __fc_loop__ 단계: OpenAI FC 루프 (MAX_TOOL_TURNS 턴)
    - 명시적 도구 단계: execute_tool() 직접 호출

    Args:
        state: AgentState (plan, current_step_index, oai_messages,
               tool_results, fc_turn_count, complexity_level, instruction,
               chat_id, user_identity 등 필요)

    Returns:
        dict with keys: tool_results, oai_messages, fc_turn_count,
                        current_step_index, final_response
    """
    from bot_brain import log, MAX_TOOL_TURNS

    plan: list[dict] = state.get("plan", [])
    current_step_index: int = state.get("current_step_index", 0)
    oai_messages: list[dict] = list(state.get("oai_messages", []))  # shallow copy
    existing_results: list[dict] = list(state.get("tool_results", []))
    fc_turn_count: int = state.get("fc_turn_count", 0)
    complexity_level: str = state.get("complexity_level", "SIMPLE")
    instruction: str = state.get("instruction", "")
    chat_id: str = state.get("chat_id", "")
    user_identity: dict | None = state.get("user_identity")

    if current_step_index >= len(plan):
        log("[executor] 모든 계획 단계 완료")
        return {
            "current_step_index": current_step_index,
        }

    step = plan[current_step_index]
    tool_name = step.get("tool", "__fc_loop__")
    purpose = step.get("purpose", "")

    log(
        f"[executor] 단계 {current_step_index + 1}/{len(plan)} 실행: "
        f"{tool_name} ({purpose})"
    )

    final_response = ""
    new_results: list[dict] = []

    if tool_name == "__fc_loop__":
        # ── FC 루프 실행 ──
        tools = _extract_tools_from_messages(oai_messages)
        has_plan = complexity_level == "COMPLEX" and len(plan) > 1

        new_results, oai_messages, turns, final_response = _run_fc_loop(
            oai_messages=oai_messages,
            tools=tools,
            max_turns=MAX_TOOL_TURNS,
            complexity_level=complexity_level,
            has_plan=has_plan,
            instruction=instruction,
            chat_id=chat_id,
            plan=plan,
        )
        fc_turn_count += turns

    else:
        # ── 명시적 도구 직접 실행 ──
        args_hint = step.get("args_hint", "")
        result_entry = _run_explicit_tool(
            tool_name, args_hint, instruction, user_identity
        )
        new_results = [result_entry]

        # 결과를 oai_messages에 추가 (후속 FC 루프가 참고할 수 있도록)
        oai_messages.append({
            "role": "user",
            "content": (
                f"[도구 결과: {tool_name}]\n"
                f"{result_entry['result']}"
            ),
        })

    # 단계 완료 표시
    if current_step_index < len(plan):
        plan[current_step_index]["status"] = "completed"

    all_results = existing_results + new_results

    updates: dict[str, Any] = {
        "tool_results": all_results,
        "oai_messages": oai_messages,
        "fc_turn_count": fc_turn_count,
        "current_step_index": current_step_index + 1,
        "plan": plan,
    }

    if final_response:
        updates["final_response"] = final_response

    return updates
