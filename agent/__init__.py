"""
agent 패키지 — LangGraph 기반 AI Agent

비서최재형의 핵심 처리 엔진을 LangGraph StateGraph로 구현.
기존 bot_brain.py의 단방향 파이프라인을 피드백 루프(계획→실행→평가→재계획)로 전환.

Usage:
    from agent import compile_graph
    from agent.state import create_initial_state

    graph = compile_graph()
    state = create_initial_state(instruction="이번 달 점검", ...)
    final_state = graph.invoke(state)
"""

from agent.graph import compile_graph

__all__ = ["compile_graph"]
