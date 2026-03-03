"""
synthesizer_node -- 수집된 도구 결과를 기반으로 최종 응답 생성

SIMPLE은 gpt-4o-mini, MODERATE/COMPLEX는 gpt-4o로 합성.
final_response가 이미 존재하면 그대로 반환 (FC 루프에서 직접 생성된 경우).
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.state import AgentState


# ── 합성용 시스템 프롬프트 ──
_SYNTHESIS_SYSTEM_PROMPT = """당신은 업무 비서 AI입니다. 도구 호출 결과를 바탕으로 사용자 질문에 한국어로 답변합니다.

규칙:
1. 한국어로, 핵심만 간결하게 정리
2. 고객사별로 그룹핑하여 보기 좋게 구조화
3. 담당자 이름 표시 (개인명이 없으면 "정보 없음", 팀명만 있으면 팀명 표시)
4. UUID는 절대 표시하지 마세요
5. 영문 enum은 한국어로 번역:
   - ACTIVE=활성, EXPIRED=만료, PENDING=대기중
   - QUARTERLY=분기, MONTHLY=월간, SEMI_ANNUALLY=반기, ANNUALLY=연간
   - COMPLETED=완료, IN_PROGRESS=진행중, OPEN=미처리
6. 날짜는 YYYY-MM-DD 또는 YYYY년 M월 형식으로 표시
7. 해당 기간 데이터가 없으면 "해당 기간에 결과가 없습니다"라고 명확히 안내
8. 숫자는 필요 시 단위와 함께 표시 (건, 개, 명 등)"""


def synthesizer_node(state: AgentState) -> dict:
    """
    도구 결과를 종합하여 최종 응답을 생성한다.

    Returns:
        {"final_response": str}
    """
    from bot_brain import log

    final_response = state.get("final_response", "")

    # ── FC 루프에서 이미 응답이 생성된 경우 → 그대로 반환 ──
    if final_response:
        log("[synthesizer] final_response 이미 존재 → 그대로 반환")
        return {"final_response": final_response}

    # ── 도구 결과 수집 ──
    tool_results = state.get("tool_results", [])
    instruction = state.get("instruction", "")
    complexity_level = state.get("complexity_level", "SIMPLE")
    user_identity = state.get("user_identity")

    if not tool_results and not instruction:
        log("[synthesizer] 도구 결과 없음 + 지시사항 없음 → 빈 응답")
        return {"final_response": "처리할 내용이 없습니다."}

    # ── 모델 선택 ──
    model = _select_model(complexity_level)

    # ── 프롬프트 구성 ──
    user_prompt = _build_synthesis_prompt(
        instruction=instruction,
        tool_results=tool_results,
        user_identity=user_identity,
    )

    # ── 응답 생성 ──
    response_text = _call_synthesis(model, user_prompt)

    if not response_text:
        # LLM 실패 → 도구 결과 직접 요약
        response_text = _fallback_summary(tool_results)

    log(f"[synthesizer] 응답 생성 완료 (model={model}, len={len(response_text)})")

    return {"final_response": response_text}


def _select_model(complexity_level: str) -> str:
    """복잡도에 따라 모델 선택."""
    from bot_brain import OPENAI_MODEL, FAST_MODEL

    if complexity_level == "SIMPLE":
        return FAST_MODEL
    # MODERATE, COMPLEX → 주력 모델
    return OPENAI_MODEL


def _build_synthesis_prompt(
    instruction: str,
    tool_results: list[dict],
    user_identity: dict | None,
) -> str:
    """합성용 사용자 프롬프트 구성."""
    from bot_brain import truncate_json

    parts: list[str] = []

    # 사용자 질문
    parts.append(f"[사용자 질문]\n{instruction[:800]}")

    # 사용자 정보 (개인화)
    if user_identity:
        name = user_identity.get("name", "")
        email = user_identity.get("email", "")
        if name:
            parts.append(f"\n[사용자 정보]\n이름: {name}, 이메일: {email}")

    # 도구 결과
    if tool_results:
        parts.append("\n[도구 호출 결과]")
        for i, r in enumerate(tool_results, 1):
            tool_name = r.get("tool_name", "unknown")
            has_data = r.get("has_data", False)
            error = r.get("error", "")
            result = r.get("result", "")

            if error:
                parts.append(f"\n#{i} {tool_name}: 오류 - {str(error)[:200]}")
            elif not has_data:
                parts.append(f"\n#{i} {tool_name}: 결과 없음")
            else:
                result_str = truncate_json(result, max_len=3000)
                parts.append(f"\n#{i} {tool_name}:\n{result_str}")
    else:
        parts.append("\n[도구 결과 없음]")
        parts.append("도구 호출 없이 질문에 직접 답변해주세요.")

    return "\n".join(parts)


def _call_synthesis(model: str, user_prompt: str) -> str:
    """OpenAI API 호출로 응답 합성."""
    from bot_brain import log, client, OPENAI_MAX_TOKENS

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYNTHESIS_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=OPENAI_MAX_TOKENS,
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        log(f"[synthesizer] OpenAI 호출 실패: {e}")
        return ""


def _fallback_summary(tool_results: list[dict]) -> str:
    """LLM 실패 시 도구 결과를 직접 요약."""
    if not tool_results:
        return "도구 결과를 확인할 수 없습니다."

    lines: list[str] = ["도구 호출 결과 요약:"]
    for r in tool_results:
        tool_name = r.get("tool_name", "unknown")
        has_data = r.get("has_data", False)
        if has_data:
            result = r.get("result", "")
            preview = str(result)[:500] if result else "(데이터 있음)"
            lines.append(f"\n- {tool_name}: {preview}")
        else:
            lines.append(f"\n- {tool_name}: 결과 없음")

    return "\n".join(lines)
