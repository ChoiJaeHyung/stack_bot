"""
evaluator_node -- 수집된 데이터가 질문에 답하기 충분한지 판단

대부분 규칙 기반(LLM 호출 0). COMPLEX 쿼리의 부분 데이터만 gpt-4o-mini 호출.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.state import AgentState


def evaluator_node(state: AgentState) -> dict:
    """
    수집 결과 평가 → evaluation 반환.

    Returns:
        {"evaluation": "sufficient"|"need_more"|"replan"}
    """
    from bot_brain import log, MAX_TOOL_TURNS
    from agent.constants import TOOL_FALLBACK_MAP as CONST_FALLBACK_MAP

    plan = state.get("plan", [])
    tool_results = state.get("tool_results", [])
    fc_turn_count = state.get("fc_turn_count", 0)
    final_response = state.get("final_response", "")
    is_write = state.get("is_write_operation", False)
    complexity_level = state.get("complexity_level", "SIMPLE")
    plan_revision_count = state.get("plan_revision_count", 0)
    instruction = state.get("instruction", "")

    # ── 규칙 7 (안전장치): 재계획 2회 이상 → 가진 것으로 합성 ──
    if plan_revision_count >= 2:
        log("[evaluator] 재계획 2회 도달 → sufficient (안전장치)")
        return {"evaluation": "sufficient"}

    # ── 규칙 4: final_response가 이미 존재 (FC 루프에서 생성) ──
    if final_response:
        log("[evaluator] final_response 이미 존재 → sufficient")
        return {"evaluation": "sufficient"}

    # ── 규칙 3: FC 턴 예산 소진 ──
    if fc_turn_count >= MAX_TOOL_TURNS:
        log(f"[evaluator] FC 턴 예산 소진 ({fc_turn_count}/{MAX_TOOL_TURNS}) → sufficient")
        return {"evaluation": "sufficient"}

    # ── 규칙 2: 쓰기 작업이 성공적으로 완료 ──
    if is_write:
        write_results = [
            r for r in tool_results
            if r.get("has_data") or not r.get("error")
        ]
        if write_results:
            log("[evaluator] 쓰기 작업 완료 → sufficient")
            return {"evaluation": "sufficient"}

    # ── 규칙 1: 모든 계획 단계 완료 + 데이터 존재 ──
    if plan:
        completed_steps = [s for s in plan if s.get("status") == "done"]
        failed_steps = [s for s in plan if s.get("status") == "failed"]
        pending_steps = [s for s in plan if s.get("status") not in ("done", "failed")]

        # 아직 실행하지 않은 단계가 남아있으면 need_more
        if pending_steps:
            log(f"[evaluator] 미완료 단계 {len(pending_steps)}개 → need_more")
            return {"evaluation": "need_more"}

        # 모든 단계 완료 + 데이터 존재
        has_any_data = any(r.get("has_data") for r in tool_results)
        if len(completed_steps) == len(plan) and has_any_data:
            log("[evaluator] 모든 계획 단계 완료 + 데이터 존재 → sufficient")
            return {"evaluation": "sufficient"}

        # ── 규칙 5: 실패 단계 존재 + Fallback 가능 ──
        if failed_steps:
            has_fallback = False
            for step in failed_steps:
                tool_name = step.get("tool", "")
                if tool_name in CONST_FALLBACK_MAP:
                    has_fallback = True
                    break
            if has_fallback:
                log("[evaluator] 실패 단계 + Fallback 가능 → replan")
                return {"evaluation": "replan"}

        # 모든 단계 완료했지만 데이터 없음
        if not has_any_data and len(completed_steps) == len(plan):
            # 데이터 없음 = 해당 조건에 맞는 결과가 없다는 것도 정답일 수 있음
            log("[evaluator] 모든 단계 완료 + 데이터 없음 → sufficient (없다는 것도 답)")
            return {"evaluation": "sufficient"}
    else:
        # 계획 없이 도구 실행한 경우 (SIMPLE/MODERATE)
        if tool_results:
            has_any_data = any(r.get("has_data") for r in tool_results)
            failed_tools = [r for r in tool_results if not r.get("has_data") and not r.get("error")]

            if has_any_data:
                log("[evaluator] 도구 결과 데이터 있음 → sufficient")
                return {"evaluation": "sufficient"}

            # 실패한 도구에 Fallback이 있으면 replan
            for r in tool_results:
                if not r.get("has_data"):
                    tool_name = r.get("tool_name", "")
                    if tool_name in CONST_FALLBACK_MAP:
                        log(f"[evaluator] {tool_name} 실패 + Fallback 있음 → replan")
                        return {"evaluation": "replan"}

            # 도구가 있지만 데이터 없음 → sufficient (없다는 답변)
            log("[evaluator] 도구 실행 완료 + 데이터 없음 → sufficient")
            return {"evaluation": "sufficient"}

    # ── 규칙 6: COMPLEX + 부분 데이터 → gpt-4o-mini 판단 ──
    if complexity_level == "COMPLEX" and tool_results:
        partial_data = any(r.get("has_data") for r in tool_results)
        missing_data = any(not r.get("has_data") for r in tool_results)

        if partial_data and missing_data:
            verdict = _llm_judge_sufficiency(instruction, tool_results)
            log(f"[evaluator] COMPLEX LLM 판단: {verdict}")
            return {"evaluation": verdict}

    # 기본: 데이터가 없으면 need_more, 있으면 sufficient
    if tool_results:
        log("[evaluator] 기본 판단 → sufficient")
        return {"evaluation": "sufficient"}

    log("[evaluator] 도구 결과 없음 → need_more")
    return {"evaluation": "need_more"}


def _llm_judge_sufficiency(instruction: str, tool_results: list[dict]) -> str:
    """COMPLEX 쿼리의 부분 데이터에 대해 gpt-4o-mini로 충분성 판단."""
    from bot_brain import log, client, FAST_MODEL

    results_summary = []
    for r in tool_results:
        status = "데이터 있음" if r.get("has_data") else "빈 결과"
        preview = str(r.get("result", ""))[:200]
        results_summary.append(f"- {r.get('tool_name', '?')}: {status} | {preview}")

    prompt = f"""다음 사용자 질문에 답변하기 위해 여러 도구를 호출했습니다.
현재 수집된 데이터로 질문에 답변할 수 있는지 판단해주세요.

[질문]
{instruction[:500]}

[도구 결과]
{chr(10).join(results_summary)}

판단:
- 핵심 데이터가 있어서 답변 가능 → "sufficient"
- 핵심 데이터가 부족하여 추가 조회 필요 → "need_more"

한 단어만 답변: sufficient 또는 need_more"""

    try:
        resp = client.chat.completions.create(
            model=FAST_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=20,
        )
        answer = (resp.choices[0].message.content or "").strip().lower()
        if "sufficient" in answer:
            return "sufficient"
        elif "need_more" in answer:
            return "need_more"
        else:
            # 판단 불가 → 가진 것으로 합성
            return "sufficient"
    except Exception as e:
        log(f"[evaluator] LLM 판단 실패: {e} → sufficient")
        return "sufficient"
