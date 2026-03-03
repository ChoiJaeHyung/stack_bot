"""
LangGraph StateGraph 구성 + 컴파일

그래프 흐름:
  INGEST → ROUTER →
    (SIMPLE+hit) → FAST_EXECUTOR ─────────────────────────────────┐
    (MODERATE/COMPLEX) → PLANNER → EXECUTOR ←─────┐              │
                                       ↓           │ need_more    │
                                   EVALUATOR ──────┘              │
                                   ↓ sufficient  ↓ replan         │
                                   │         RE_PLANNER → EXECUTOR│
                                   ↓                              │
                               SYNTHESIZER ←──────────────────────┘
                                   ↓
                               REFLECTOR
                               ↓ pass/skip  ↓ fail
                               │      RETRY_EXECUTOR → SYNTHESIZER
                               ↓
                             DELIVER
"""

from __future__ import annotations

from langgraph.graph import StateGraph, END

from agent.state import AgentState


# ── 노드 이름 상수 ──
INGEST = "ingest"
ROUTER = "router"
FAST_EXECUTOR = "fast_executor"
PLANNER = "planner"
EXECUTOR = "executor"
EVALUATOR = "evaluator"
RE_PLANNER = "re_planner"
SYNTHESIZER = "synthesizer"
REFLECTOR = "reflector"
RETRY_EXECUTOR = "retry_executor"
DELIVER = "deliver"


# ── 라우팅 함수 ──

def route_after_router(state: AgentState) -> str:
    """
    Router 이후 분기:
    - SIMPLE + Fast Path 매칭 → FAST_EXECUTOR (70% 요청)
    - 그 외 → PLANNER
    """
    if (state.get("fast_path_tool")
            and state.get("complexity_level") == "SIMPLE"):
        return FAST_EXECUTOR
    return PLANNER


def route_after_fast_executor(state: AgentState) -> str:
    """
    Fast Executor 이후 분기:
    - 응답 생성 성공 → SYNTHESIZER (이미 final_response 설정됨)
    - 응답 실패 (너무 짧음) → PLANNER로 fallback
    """
    if state.get("fast_path_tool") is None:
        # fast_executor가 실패하여 fast_path_tool을 None으로 리셋한 경우
        return PLANNER
    # reflection_verdict="skip"이면 바로 DELIVER로
    if state.get("reflection_verdict") == "skip":
        return DELIVER
    return REFLECTOR


def route_after_evaluator(state: AgentState) -> str:
    """
    Evaluator 이후 분기 (AI Agent의 핵심!):
    - sufficient → SYNTHESIZER
    - replan (max 2회) → RE_PLANNER
    - need_more (FC 턴 예산 내) → EXECUTOR
    - 예산 초과 → SYNTHESIZER
    """
    evaluation = state.get("evaluation", "sufficient")

    if evaluation == "sufficient":
        return SYNTHESIZER

    if evaluation == "replan":
        if state.get("plan_revision_count", 0) < 2:
            return RE_PLANNER
        # 재계획 한도 초과 → 수집된 데이터로 합성
        return SYNTHESIZER

    if evaluation == "need_more":
        from bot_brain import MAX_TOOL_TURNS
        if state.get("fc_turn_count", 0) < MAX_TOOL_TURNS:
            return EXECUTOR
        # FC 턴 예산 초과 → 합성
        return SYNTHESIZER

    return SYNTHESIZER


def route_after_reflector(state: AgentState) -> str:
    """
    Reflector 이후 분기:
    - pass/skip → DELIVER
    - fail (max 2회) → RETRY_EXECUTOR
    - 재시도 한도 초과 → DELIVER
    """
    verdict = state.get("reflection_verdict", "pass")

    if verdict in ("pass", "skip"):
        return DELIVER

    if verdict == "fail":
        if state.get("reflection_count", 0) < 2:
            return RETRY_EXECUTOR
        # 재시도 한도 초과
        return DELIVER

    return DELIVER


# ── 그래프 빌드 ──

def build_graph() -> StateGraph:
    """StateGraph를 빌드하고 반환한다 (아직 컴파일하지 않음)."""

    # 노드 함수 임포트 (lazy — 빌드 시점에만 로드)
    from agent.nodes.ingest import ingest_node
    from agent.nodes.router import router_node
    from agent.nodes.fast_executor import fast_executor_node
    from agent.nodes.planner import planner_node
    from agent.nodes.executor import executor_node
    from agent.nodes.evaluator import evaluator_node
    from agent.nodes.re_planner import re_planner_node
    from agent.nodes.synthesizer import synthesizer_node
    from agent.nodes.reflector import reflector_node
    from agent.nodes.retry_executor import retry_executor_node
    from agent.nodes.deliver import deliver_node

    # 그래프 생성
    graph = StateGraph(AgentState)

    # 노드 등록
    graph.add_node(INGEST, ingest_node)
    graph.add_node(ROUTER, router_node)
    graph.add_node(FAST_EXECUTOR, fast_executor_node)
    graph.add_node(PLANNER, planner_node)
    graph.add_node(EXECUTOR, executor_node)
    graph.add_node(EVALUATOR, evaluator_node)
    graph.add_node(RE_PLANNER, re_planner_node)
    graph.add_node(SYNTHESIZER, synthesizer_node)
    graph.add_node(REFLECTOR, reflector_node)
    graph.add_node(RETRY_EXECUTOR, retry_executor_node)
    graph.add_node(DELIVER, deliver_node)

    # 엣지 설정
    # 시작점
    graph.set_entry_point(INGEST)

    # INGEST → ROUTER (무조건)
    graph.add_edge(INGEST, ROUTER)

    # ROUTER → 조건부 분기
    graph.add_conditional_edges(
        ROUTER,
        route_after_router,
        {
            FAST_EXECUTOR: FAST_EXECUTOR,
            PLANNER: PLANNER,
        },
    )

    # FAST_EXECUTOR → 조건부 분기
    graph.add_conditional_edges(
        FAST_EXECUTOR,
        route_after_fast_executor,
        {
            PLANNER: PLANNER,
            REFLECTOR: REFLECTOR,
            DELIVER: DELIVER,
        },
    )

    # PLANNER → EXECUTOR (무조건)
    graph.add_edge(PLANNER, EXECUTOR)

    # EXECUTOR → EVALUATOR (무조건)
    graph.add_edge(EXECUTOR, EVALUATOR)

    # EVALUATOR → 조건부 분기 (핵심 피드백 루프)
    graph.add_conditional_edges(
        EVALUATOR,
        route_after_evaluator,
        {
            SYNTHESIZER: SYNTHESIZER,
            RE_PLANNER: RE_PLANNER,
            EXECUTOR: EXECUTOR,
        },
    )

    # RE_PLANNER → EXECUTOR (무조건)
    graph.add_edge(RE_PLANNER, EXECUTOR)

    # SYNTHESIZER → REFLECTOR (무조건)
    graph.add_edge(SYNTHESIZER, REFLECTOR)

    # REFLECTOR → 조건부 분기
    graph.add_conditional_edges(
        REFLECTOR,
        route_after_reflector,
        {
            DELIVER: DELIVER,
            RETRY_EXECUTOR: RETRY_EXECUTOR,
        },
    )

    # RETRY_EXECUTOR → SYNTHESIZER (재합성)
    graph.add_edge(RETRY_EXECUTOR, SYNTHESIZER)

    # DELIVER → END
    graph.add_edge(DELIVER, END)

    return graph


def compile_graph():
    """
    StateGraph를 빌드하고 컴파일하여 실행 가능한 그래프를 반환.

    Returns:
        CompiledGraph: graph.invoke(state)로 실행 가능
    """
    graph = build_graph()
    return graph.compile()
