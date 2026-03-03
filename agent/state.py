"""
AgentState — LangGraph 상태 정의

그래프의 모든 노드가 읽고 쓰는 공유 상태.
TypedDict 기반으로 정적 타입 검사 + LangGraph 호환.
"""

from __future__ import annotations

from typing import Any, Optional
from typing_extensions import TypedDict


class AgentState(TypedDict, total=False):
    # ── 입력 ──
    instruction: str                    # 사용자 지시사항 (합산된)
    chat_id: str                        # Google Chat space name
    message_ids: list[str]              # 처리 대상 메시지 ID 리스트
    context_24h: str                    # 최근 24시간 대화 컨텍스트
    memory_context: str                 # 이전 작업 기록 (참고용)
    user_identity: Optional[dict]       # {"uuid", "name", "email"} or None
    files: list[dict]                   # 첨부 파일 정보
    sender_email: str                   # 사용자 이메일
    user_name: str                      # 사용자 표시 이름
    all_timestamps: list[str]           # 메시지 타임스탬프 리스트

    # ── 라우팅 ──
    intent: str                         # lookup / analysis / action / report
    active_domains: list[str]           # ["checkup", "maintenance_contract", ...]
    complexity_score: int               # 0~10
    complexity_level: str               # SIMPLE / MODERATE / COMPLEX
    fast_path_tool: Optional[str]       # Fast Path 매칭된 도구 이름
    fast_path_args: Optional[dict]      # Fast Path 도구 인자
    is_write_operation: bool            # 쓰기 작업 여부

    # ── 계획 ──
    plan: list[dict]                    # [{"step", "tool", "purpose", "status"}]
    plan_revision_count: int            # 계획 수정 횟수 (max 2)
    current_step_index: int             # 현재 실행 중인 단계 인덱스

    # ── 실행 축적 ──
    tool_results: list[dict]            # [{"tool_name", "args", "result", "has_data", "error"}]
    oai_messages: list[dict]            # OpenAI FC 메시지 히스토리
    fc_turn_count: int                  # FC 루프 턴 수 (max MAX_TOOL_TURNS)

    # ── 평가 / 합성 / 검증 ──
    evaluation: str                     # sufficient / need_more / replan
    final_response: str                 # 최종 생성된 응답
    reflection_verdict: str             # pass / fail / skip
    reflection_count: int               # Reflection 재시도 횟수 (max 2)
    reflection_retry_tool: Optional[str]   # Reflector가 제안한 재시도 도구
    reflection_retry_args: Optional[dict]  # Reflector가 제안한 재시도 인자

    # ── 제어 ──
    error: Optional[str]                # 오류 메시지
    should_abort: bool                  # 그래프 강제 종료 플래그


def create_initial_state(**kwargs) -> AgentState:
    """초기 상태 생성. 기본값 설정."""
    defaults: dict[str, Any] = {
        "instruction": "",
        "chat_id": "",
        "message_ids": [],
        "context_24h": "",
        "memory_context": "",
        "user_identity": None,
        "files": [],
        "sender_email": "",
        "user_name": "",
        "all_timestamps": [],
        # 라우팅
        "intent": "",
        "active_domains": [],
        "complexity_score": 0,
        "complexity_level": "SIMPLE",
        "fast_path_tool": None,
        "fast_path_args": None,
        "is_write_operation": False,
        # 계획
        "plan": [],
        "plan_revision_count": 0,
        "current_step_index": 0,
        # 실행
        "tool_results": [],
        "oai_messages": [],
        "fc_turn_count": 0,
        # 평가
        "evaluation": "",
        "final_response": "",
        "reflection_verdict": "",
        "reflection_count": 0,
        "reflection_retry_tool": None,
        "reflection_retry_args": None,
        # 제어
        "error": None,
        "should_abort": False,
    }
    defaults.update(kwargs)
    return defaults  # type: ignore
