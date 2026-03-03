"""
fast_executor 노드 — Fast Path 직접 실행

router에서 fast_path_tool/fast_path_args가 세팅된 경우,
OpenAI FC 루프를 건너뛰고 도구를 직접 호출한 뒤 gpt-4o-mini로 응답을 생성한다.
"""

from __future__ import annotations

import re
from datetime import datetime


def fast_executor_node(state: dict) -> dict:
    """
    Fast Path 도구 실행 + 경량 모델 응답 생성.

    Args:
        state: AgentState (fast_path_tool, fast_path_args, instruction,
               user_identity, chat_id 필요)

    Returns:
        dict with keys: final_response, reflection_verdict
        실패 시 fast_path_tool=None으로 세팅하여 planner fallback 유도
    """
    from bot_brain import (
        log, execute_tool, truncate_json, client,
        FAST_MODEL, FAST_SYSTEM_PROMPT, OPENAI_MAX_TOKENS,
    )

    fast_path_tool: str = state.get("fast_path_tool", "")
    fast_path_args: dict = state.get("fast_path_args") or {}
    instruction: str = state.get("instruction", "")
    user_identity: dict | None = state.get("user_identity")

    if not fast_path_tool:
        log("[fast_executor] fast_path_tool 없음 → 스킵")
        return {}

    log(f"[fast_executor] 실행: {fast_path_tool}({fast_path_args})")

    # ── 1. 도구 실행 ──
    try:
        fp_result = execute_tool(fast_path_tool, fast_path_args)
        fp_result_str = truncate_json(fp_result)
        log(
            f"[fast_executor] 도구 결과 len={len(fp_result_str)}, "
            f"preview={fp_result_str[:200]}"
        )
    except Exception as e:
        log(f"[fast_executor] 도구 실행 실패 → planner fallback: {e}")
        return {
            "fast_path_tool": None,
            "fast_path_args": None,
        }

    # ── 2. 순수 질문 추출 (24h 컨텍스트 / 메타데이터 제거) ──
    fp_question = instruction.strip()
    if "\n---\n" in fp_question:
        fp_question = fp_question.split("\n---\n")[0].strip()
    req_match = re.search(r"\[요청\s*\d+\].*?\n(.+)", fp_question, re.DOTALL)
    if req_match:
        fp_question = req_match.group(1).strip()

    # ── 3. 사용자 신원 컨텍스트 ──
    user_identity_context = ""
    if user_identity:
        user_identity_context = (
            f"\n현재 사용자: {user_identity['name']} ({user_identity.get('email', '')})"
            f"\n사용자 UUID: {user_identity['uuid']}"
            f'\n"내", "나의" 등 본인 관련 질문 시 이 UUID 기준으로 필터링.'
        )

    # ── 4. gpt-4o-mini 응답 생성 ──
    fp_prompt = (
        f"현재 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        f"{user_identity_context}\n\n"
        f"[질문]\n{fp_question[:300]}\n\n"
        f"[도구 결과: {fast_path_tool}]\n{fp_result_str}\n\n"
        "중요: 반드시 위 [도구 결과]의 데이터만 사용하여 답변하세요. "
        "이전 대화 내용이나 다른 출처의 정보는 절대 사용하지 마세요.\n"
        "도구 결과에 데이터가 없거나 빈 배열이면 "
        '"해당 기간에 해당하는 건이 없습니다"라고 명확히 안내하세요.\n'
        "위 결과를 한국어로 간결하게 정리하세요. "
        "고객사별 그룹핑, 담당자 표시, UUID 숨김."
    )

    try:
        fp_response = client.chat.completions.create(
            model=FAST_MODEL,
            messages=[
                {"role": "system", "content": FAST_SYSTEM_PROMPT},
                {"role": "user", "content": fp_prompt},
            ],
            temperature=0.3,
            max_tokens=OPENAI_MAX_TOKENS,
        )
        final_response = fp_response.choices[0].message.content or ""
        log(
            f"[fast_executor] 응답 생성 완료 "
            f"(len={len(final_response)}, model={FAST_MODEL})"
        )
    except Exception as e:
        log(f"[fast_executor] 응답 생성 실패 → planner fallback: {e}")
        return {
            "fast_path_tool": None,
            "fast_path_args": None,
        }

    # ── 5. 응답 품질 검사 ──
    if len(final_response) < 20:
        log("[fast_executor] 응답 너무 짧음 → planner fallback")
        return {
            "fast_path_tool": None,
            "fast_path_args": None,
        }

    # ── 6. 성공 — Reflection 스킵 ──
    return {
        "final_response": final_response,
        "reflection_verdict": "skip",
        "tool_results": [
            {
                "tool_name": fast_path_tool,
                "args": fast_path_args,
                "result": fp_result_str[:500],
                "has_data": True,
                "error": None,
            }
        ],
    }
