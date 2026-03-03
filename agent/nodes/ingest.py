"""
ingest 노드 — 메모리 예약 + 이전 작업 로드 + 사용자 신원 확인

그래프 진입 직후 실행되어 state에 memory_context와 user_identity를 세팅한다.
"""

from __future__ import annotations

from typing import Any


def ingest_node(state: dict) -> dict:
    """
    메모리 예약, 기존 작업 기록 로드, 사용자 UUID 조회.

    Args:
        state: AgentState (instruction, chat_id, message_ids, sender_email,
               user_name, all_timestamps 등이 채워진 상태)

    Returns:
        dict with keys: memory_context, user_identity
    """
    from bot_brain import log, _lookup_user_identity
    from chat_bot import reserve_memory_chat, search_memory

    instruction: str = state.get("instruction", "")
    chat_id: str = state.get("chat_id", "")
    message_ids: list[str] = state.get("message_ids", [])
    all_timestamps: list[str] = state.get("all_timestamps", [])
    sender_email: str = state.get("sender_email", "")
    user_name: str = state.get("user_name", "")

    # ── 1. 메모리 예약 (tasks/msg_{id}/ 폴더 생성 + 지시사항 기록) ──
    try:
        reserve_memory_chat(instruction, chat_id, all_timestamps, message_ids)
        log("[ingest] 메모리 예약 완료")
    except Exception as e:
        log(f"[ingest] 메모리 예약 실패 (계속 진행): {e}")

    # ── 2. 기존 작업 기록 로드 (최근 10건, 합산 제외) ──
    memory_context = ""
    try:
        all_tasks = search_memory()  # 인수 없이 → 전체 목록 (역순)
        if all_tasks:
            recent = all_tasks[:10]
            lines: list[str] = []
            for m in recent:
                inst = m.get("instruction", "")[:80]
                if "(합산됨)" not in inst and inst:
                    lines.append(f"- {inst}")
            if lines:
                memory_context = (
                    "\n\n[이전 작업 기록 - 참고용, 데이터는 반드시 도구로 재조회할 것]\n"
                    + "\n".join(lines)
                )
        log(f"[ingest] 메모리 로드 완료 ({len(all_tasks) if all_tasks else 0}건)")
    except Exception as e:
        log(f"[ingest] 메모리 로드 실패 (계속 진행): {e}")

    # ── 3. 사용자 신원 확인 (UUID 매핑) ──
    user_identity: dict[str, Any] | None = None
    try:
        user_identity = _lookup_user_identity(sender_email, user_name)
        if user_identity:
            log(
                f"[ingest] 사용자 확인: {user_identity['name']} "
                f"({user_identity['uuid'][:8]}...)"
            )
        else:
            log(f"[ingest] 사용자 UUID 매핑 없음: email={sender_email}, name={user_name}")
    except Exception as e:
        log(f"[ingest] UUID 조회 실패 (계속 진행): {e}")

    return {
        "memory_context": memory_context,
        "user_identity": user_identity,
    }
