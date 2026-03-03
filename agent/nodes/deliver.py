"""
deliver_node -- 최종 응답을 Google Chat으로 전송하고 작업을 완료 처리

Terminal 노드: report_chat → mark_done_chat → remove_working_lock → 에피소드 로그.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.state import AgentState


def deliver_node(state: AgentState) -> dict:
    """
    최종 응답을 전송하고 작업을 완료 처리한다.

    Returns:
        {} (terminal node, 상태 변경 없음)
    """
    from bot_brain import log, BOT_NAME

    final_response = state.get("final_response", "")
    instruction = state.get("instruction", "")
    chat_id = state.get("chat_id", "")
    message_ids = state.get("message_ids", [])
    all_timestamps = state.get("all_timestamps", [])

    if not final_response:
        log("[deliver] final_response 없음 → 기본 메시지 전송")
        final_response = "요청을 처리했으나 결과를 생성하지 못했습니다."

    if not chat_id:
        log("[deliver] chat_id 없음 → 전송 스킵")
        return {}

    # ── 1. report_chat → Google Chat 전송 + 메모리 저장 ──
    try:
        from chat_bot import report_chat

        report_chat(
            instruction=instruction,
            result_text=final_response,
            chat_id=chat_id,
            timestamp=all_timestamps if len(all_timestamps) > 1 else (all_timestamps[0] if all_timestamps else ""),
            message_id=message_ids if len(message_ids) > 1 else (message_ids[0] if message_ids else ""),
            files=None,
        )
        log("[deliver] report_chat 완료")
    except Exception as e:
        log(f"[deliver] report_chat 실패: {e}")
        # Fallback: 직접 전송 시도
        _fallback_send(chat_id, final_response)

    # ── 2. mark_done_chat → 메시지 처리 완료 표시 ──
    if message_ids:
        try:
            from chat_bot import mark_done_chat
            mark_done_chat(message_ids if len(message_ids) > 1 else message_ids[0])
            log("[deliver] mark_done_chat 완료")
        except Exception as e:
            log(f"[deliver] mark_done_chat 실패: {e}")

    # ── 3. remove_working_lock → 작업 잠금 해제 ──
    try:
        from chat_bot import remove_working_lock
        remove_working_lock()
        log("[deliver] remove_working_lock 완료")
    except Exception as e:
        log(f"[deliver] remove_working_lock 실패: {e}")

    # ── 4. 에피소드 로그 ──
    _log_episode(state)

    log("[deliver] 전달 완료 (terminal)")
    return {}


def _fallback_send(chat_id: str, message: str) -> None:
    """report_chat 실패 시 직접 메시지 전송."""
    try:
        from bot_brain import _send_message_impl
        _send_message_impl(chat_id, message)
    except Exception:
        pass


def _log_episode(state: AgentState) -> None:
    """
    에피소드 정보를 로그에 기록한다.
    향후 학습/분석을 위한 데이터 수집.
    """
    from bot_brain import log

    try:
        instruction = state.get("instruction", "")[:200]
        complexity = state.get("complexity_level", "?")
        score = state.get("complexity_score", 0)
        intent = state.get("intent", "?")
        domains = state.get("active_domains", [])
        tool_results = state.get("tool_results", [])
        plan_revisions = state.get("plan_revision_count", 0)
        reflection_count = state.get("reflection_count", 0)
        reflection_verdict = state.get("reflection_verdict", "")
        fc_turns = state.get("fc_turn_count", 0)
        final_len = len(state.get("final_response", ""))

        tools_used = [r.get("tool_name", "?") for r in tool_results]
        tools_with_data = sum(1 for r in tool_results if r.get("has_data"))

        episode = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "instruction": instruction,
            "complexity": f"{complexity}({score})",
            "intent": intent,
            "domains": domains,
            "tools_used": tools_used,
            "tools_with_data": f"{tools_with_data}/{len(tool_results)}",
            "fc_turns": fc_turns,
            "plan_revisions": plan_revisions,
            "reflection": f"{reflection_verdict}(x{reflection_count})",
            "response_len": final_len,
        }

        log(f"[episode] {json.dumps(episode, ensure_ascii=False)}")

        # 에피소드 저장소에도 기록
        try:
            from agent.memory.episode_store import save_episode
            save_episode({
                "message_id": state.get("message_ids", [""])[0] if state.get("message_ids") else "",
                "instruction": instruction,
                "tools_used": tools_used,
                "plan_revisions": plan_revisions,
                "complexity": complexity,
                "fast_path_hit": state.get("fast_path_tool") is not None,
                "success": bool(final_len > 20),
                "result_summary": state.get("final_response", "")[:200],
            })
        except Exception:
            pass  # 에피소드 저장 실패는 무시

    except Exception as e:
        log(f"[episode] 로그 기록 실패: {e}")
