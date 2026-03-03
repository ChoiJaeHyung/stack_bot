"""
reflector_node -- 최종 응답을 검증하고 재시도 필요 여부를 결정

bot_brain.py의 _verify_response() 로직을 LangGraph 노드로 포팅.
Quick-Pass 규칙으로 70% 요청은 추가 API 호출 없이 통과.
"""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.state import AgentState


def reflector_node(state: AgentState) -> dict:
    """
    최종 응답의 품질을 검증한다.

    Quick-Pass 규칙:
      1. 쓰기 작업 → skip
      2. 모든 도구 데이터 있음 + 응답 >= 200자 → skip
      3. 빈 결과 없음 + 응답 >= 100자 → skip
      4. 도구가 "없습니다" 반환 + 응답에 "없" 포함 → skip

    Returns:
        {"reflection_verdict": "pass"|"fail"|"skip", "reflection_count": N}
    """
    from bot_brain import log
    from agent.constants import WRITE_TOOLS as CONST_WRITE_TOOLS

    tool_results = state.get("tool_results", [])
    final_response = state.get("final_response", "")
    is_write = state.get("is_write_operation", False)
    reflection_count = state.get("reflection_count", 0)
    instruction = state.get("instruction", "")

    # ── 도구 호출이 없었으면 검증 불필요 ──
    if not tool_results:
        log("[reflector] 도구 호출 없음 → skip")
        return {"reflection_verdict": "skip", "reflection_count": reflection_count}

    # ── Quick-Pass 분석 ──
    called_tools = {r.get("tool_name", "") for r in tool_results}
    all_have_data = all(r.get("has_data", True) for r in tool_results)
    any_empty = any(r.get("has_data") is False for r in tool_results)
    used_write_tool = is_write or bool(called_tools & CONST_WRITE_TOOLS)
    response_len = len(final_response)

    # 규칙 1: 쓰기 작업 → 빈 결과가 실패가 아님
    if used_write_tool:
        log("[reflector] Quick-Pass: 쓰기 작업 → skip")
        return {"reflection_verdict": "skip", "reflection_count": reflection_count}

    # 규칙 2: 모든 도구가 데이터 반환 + 응답 200자 이상
    if all_have_data and response_len >= 200:
        log("[reflector] Quick-Pass: 모든 도구 데이터 있음 + 응답 충분 → skip")
        return {"reflection_verdict": "skip", "reflection_count": reflection_count}

    # 규칙 3: 빈 결과 없음 + 응답 100자 이상
    if not any_empty and response_len >= 100:
        log("[reflector] Quick-Pass: 빈 결과 없음 + 응답 100자 이상 → skip")
        return {"reflection_verdict": "skip", "reflection_count": reflection_count}

    # 규칙 4: 도구가 "없습니다" 명시적 반환 + 응답도 "없" 포함
    tool_returned_empty_msg = any(
        "없습니다" in str(r.get("result", ""))[:500]
        for r in tool_results
    )
    response_says_none = "없" in final_response and response_len >= 30
    if tool_returned_empty_msg and response_says_none:
        log("[reflector] Quick-Pass: 도구 '없습니다' + 응답 확인 → skip")
        return {"reflection_verdict": "skip", "reflection_count": reflection_count}

    # ── LLM 검증 ──
    log(f"[reflector] LLM 검증 시작 (도구 {len(tool_results)}개, 응답 {response_len}자)")
    verdict_data = _llm_verify(instruction, final_response, tool_results)

    verdict = verdict_data.get("verdict", "pass")
    new_count = reflection_count + 1
    log(f"[reflector] 검증 결과: {verdict} (count={new_count})")

    result: dict = {"reflection_verdict": verdict, "reflection_count": new_count}

    # Reflector가 제안한 재시도 힌트를 state에 전달
    if verdict == "fail":
        retry_tool = verdict_data.get("retry_tool")
        retry_args = verdict_data.get("retry_args")
        if retry_tool:
            result["reflection_retry_tool"] = retry_tool
            result["reflection_retry_args"] = retry_args if isinstance(retry_args, dict) else {}
            log(f"[reflector] 재시도 힌트: {retry_tool}({retry_args})")

    return result


def _llm_verify(
    instruction: str,
    response: str,
    tool_results: list[dict],
) -> dict:
    """gpt-4o-mini로 응답 품질 검증. verdict dict 반환."""
    from bot_brain import log, client, REFLECTION_MODEL

    # 도구 요약 구성
    tool_summary_lines: list[str] = []
    for r in tool_results:
        tool_name = r.get("tool_name", "?")
        has_data = r.get("has_data", False)
        args_str = json.dumps(r.get("args", {}), ensure_ascii=False)[:100]
        status = "데이터 있음" if has_data else "빈 결과/오류"
        tool_summary_lines.append(f"- {tool_name}({args_str}): {status}")

    tool_summary = "\n".join(tool_summary_lines)

    verify_prompt = f"""다음 사용자 질문에 대해 AI 비서가 도구를 호출하고 답변을 생성했습니다. 답변의 품질을 검증해주세요.

[사용자 질문]
{instruction[:500]}

[호출된 도구 및 결과]
{tool_summary}

[생성된 답변]
{response[:1000]}

검증 기준:
1. 질문에 관련된 데이터를 실제로 찾았는가?
2. 빈 결과를 받았는데 "찾을 수 없습니다"로 포기하지 않았는가?
3. 다른 도구로 재시도하면 더 나은 결과를 얻을 수 있는가?
4. 답변의 날짜/기간/월이 사용자가 요청한 것과 일치하는가?
5. 데이터가 있지만 질문과 무관한 결과를 보여주고 있지 않은가?

응답 형식 (반드시 JSON):
- 통과: {{"verdict": "pass"}}
- 재시도 필요: {{"verdict": "fail", "reason": "이유", "retry_tool": "대체도구명", "retry_args": {{...}}}}

주의: 특정 월/기간 조회 시 결과가 없으면 "해당 기간에 없다"가 정답일 수 있음. 이 경우 verdict=pass."""

    try:
        verify_response = client.chat.completions.create(
            model=REFLECTION_MODEL,
            messages=[{"role": "user", "content": verify_prompt}],
            temperature=0.1,
            max_tokens=500,
        )
        verify_text = verify_response.choices[0].message.content or ""
        log(f"[reflector] LLM 검증 응답: {verify_text[:200]}")

        # JSON 파싱
        verdict_data = _parse_verdict_json(verify_text)

        if verdict_data is None or "verdict" not in verdict_data:
            log("[reflector] JSON 파싱 실패 → pass 처리")
            return {"verdict": "pass"}

        return verdict_data

    except Exception as e:
        log(f"[reflector] LLM 검증 오류: {e} → pass 처리")
        return {"verdict": "pass"}


def _parse_verdict_json(text: str) -> dict | None:
    """검증 응답에서 verdict JSON을 추출."""
    # 방법 1: ```json ... ``` 블록
    code_block = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if code_block:
        try:
            return json.loads(code_block.group(1))
        except json.JSONDecodeError:
            pass

    # 방법 2: 전체에서 JSON 객체 (greedy)
    brace_match = re.search(r'\{.*\}', text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group())
        except json.JSONDecodeError:
            pass

    # 방법 3: 단순 flat JSON
    flat_match = re.search(r'\{[^{}]*"verdict"[^{}]*\}', text)
    if flat_match:
        try:
            return json.loads(flat_match.group())
        except json.JSONDecodeError:
            pass

    return None
