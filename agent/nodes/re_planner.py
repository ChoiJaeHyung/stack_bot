"""
re_planner_node -- 실패한 도구에 대해 Fallback 대체 계획을 수립

TOOL_FALLBACK_MAP 기반으로 실패한 도구의 대안을 찾아 새 계획 단계를 생성한다.
LLM 호출 없이 규칙 기반으로 동작 (비용 0, 지연 0).
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.state import AgentState


def re_planner_node(state: AgentState) -> dict:
    """
    실패한 도구를 분석하고 Fallback 계획을 수립한다.

    Returns:
        {
            "plan": updated_plan,
            "plan_revision_count": N+1,
            "current_step_index": 0,
            "active_domains": possibly_expanded,
            "evaluation": "",
        }
    """
    from bot_brain import log
    from agent.constants import (
        TOOL_FALLBACK_MAP as CONST_FALLBACK_MAP,
        DOMAIN_GROUPS,
    )

    plan = list(state.get("plan", []))
    tool_results = list(state.get("tool_results", []))
    plan_revision_count = state.get("plan_revision_count", 0)
    active_domains = list(state.get("active_domains", []))

    log(f"[re_planner] 재계획 시작 (revision #{plan_revision_count + 1})")

    # ── 실패한 도구 수집 ──
    failed_tools: list[dict] = []

    # 1) plan 기반 실패 수집
    for step in plan:
        if step.get("status") == "failed":
            failed_tools.append({
                "tool_name": step.get("tool", ""),
                "args": step.get("args", {}),
                "purpose": step.get("purpose", ""),
            })

    # 2) tool_results 기반 실패 수집 (plan이 없는 경우)
    if not failed_tools:
        for r in tool_results:
            if not r.get("has_data") and not r.get("error"):
                failed_tools.append({
                    "tool_name": r.get("tool_name", ""),
                    "args": r.get("args", {}),
                    "purpose": "",
                })
            elif r.get("error"):
                failed_tools.append({
                    "tool_name": r.get("tool_name", ""),
                    "args": r.get("args", {}),
                    "purpose": "",
                })

    if not failed_tools:
        log("[re_planner] 실패한 도구 없음 → 변경 없이 반환")
        return {
            "plan": plan,
            "plan_revision_count": plan_revision_count + 1,
            "current_step_index": 0,
            "active_domains": active_domains,
            "evaluation": "",
        }

    # ── 이미 실행된 도구 이름 수집 (중복 방지) ──
    already_tried: set[str] = set()
    for r in tool_results:
        already_tried.add(r.get("tool_name", ""))
    for step in plan:
        if step.get("status") in ("done", "failed"):
            already_tried.add(step.get("tool", ""))

    # ── Fallback 계획 생성 ──
    new_steps: list[dict] = []
    domains_to_add: set[str] = set()

    for failed in failed_tools:
        tool_name = failed["tool_name"]
        original_args = failed.get("args", {})
        purpose = failed.get("purpose", "") or f"{tool_name} 대체 조회"

        fallbacks = CONST_FALLBACK_MAP.get(tool_name, [])
        if not fallbacks:
            log(f"[re_planner] {tool_name}: Fallback 없음 → 스킵")
            continue

        for fb_tool in fallbacks:
            if fb_tool in already_tried:
                continue

            # 원래 인자 기반으로 Fallback 도구 인자 추론
            fb_args = _infer_fallback_args(tool_name, fb_tool, original_args)

            new_step = {
                "step": f"[재시도] {purpose}",
                "tool": fb_tool,
                "args": fb_args,
                "purpose": f"{tool_name} 실패 → {fb_tool} 대체",
                "status": "pending",
            }
            new_steps.append(new_step)
            already_tried.add(fb_tool)

            # 필요한 도메인 확인
            domain = _find_domain_for_tool(fb_tool, DOMAIN_GROUPS)
            if domain and domain not in active_domains:
                domains_to_add.add(domain)

            # 첫 번째 Fallback만 시도 (효율성)
            break

    if not new_steps:
        log("[re_planner] Fallback 대안 없음 (모두 시도됨)")
        return {
            "plan": plan,
            "plan_revision_count": plan_revision_count + 1,
            "current_step_index": 0,
            "active_domains": active_domains,
            "evaluation": "sufficient",  # 더 시도할 것 없음 → 합성으로
        }

    # ── 기존 plan에 새 단계 추가 ──
    # 기존 실패/완료 단계는 유지하고, 새 단계만 추가
    updated_plan = plan + new_steps
    updated_domains = active_domains + list(domains_to_add)

    log(
        f"[re_planner] 재계획 완료: "
        f"새 단계 {len(new_steps)}개 추가, "
        f"도메인 추가: {domains_to_add or '없음'}"
    )

    # current_step_index를 새 단계의 시작점으로 설정
    new_start_index = len(plan)  # 기존 plan 뒤부터 실행

    return {
        "plan": updated_plan,
        "plan_revision_count": plan_revision_count + 1,
        "current_step_index": new_start_index,
        "active_domains": updated_domains,
        "evaluation": "",
    }


def _infer_fallback_args(
    original_tool: str,
    fallback_tool: str,
    original_args: dict,
) -> dict:
    """
    원래 도구의 인자를 기반으로 Fallback 도구의 인자를 추론.

    대부분의 경우 인자를 그대로 전달하되,
    도구별 특수 매핑이 필요한 경우 변환한다.
    """
    if not original_args:
        return {}

    args = dict(original_args)

    # search_integrated_customer → list_customers: keyword → search
    if original_tool == "search_integrated_customer" and fallback_tool == "list_customers":
        if "keyword" in args:
            args["search"] = args.pop("keyword")
        # 불필요한 인자 제거
        args.pop("includeNas", None)
        args.pop("includeSalesforce", None)

    # get_current_month_checkups → get_checkups_by_date_range
    if original_tool == "get_current_month_checkups" and fallback_tool == "get_checkups_by_date_range":
        import datetime
        today = datetime.date.today()
        first_day = today.replace(day=1)
        if today.month == 12:
            last_day = today.replace(year=today.year + 1, month=1, day=1)
        else:
            last_day = today.replace(month=today.month + 1, day=1)
        args["startDate"] = first_day.isoformat()
        args["endDate"] = last_day.isoformat()

    # get_customer_servers → search_servers: customerId → keyword
    if original_tool == "get_customer_servers" and fallback_tool == "search_servers":
        if "customerId" in args and "keyword" not in args:
            # customerId로는 검색 불가 → 인자 유지하되 search_servers에 맞게
            args.pop("customerId", None)

    return args


def _find_domain_for_tool(
    tool_name: str,
    domain_groups: dict[str, list[str]],
) -> str | None:
    """도구가 속한 도메인을 찾는다."""
    for domain, tools in domain_groups.items():
        if tool_name in tools:
            return domain
    return None
