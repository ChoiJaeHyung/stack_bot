"""
planner 노드 — 실행 계획 생성 + 도메인 필터링된 도구 + 시스템 프롬프트 초기화

복잡도에 따라:
  - SIMPLE/MODERATE: 단일 __fc_loop__ 단계
  - COMPLEX: _generate_plan()으로 다단계 계획 생성 + 사용자에게 공유
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _build_system_prompt(
    state: dict,
    memory_context: str,
    user_identity_context: str,
    plan_guidance: str,
) -> str:
    """bot_brain.py와 동일한 시스템 프롬프트 생성."""
    from bot_brain import BOT_NAME

    return f"""당신은 '{BOT_NAME}', 업무 비서 AI입니다.
사용자의 요청을 정확히 처리하고, 결과를 간결하고 명확하게 보고합니다.

현재 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{user_identity_context}

사용 가능한 도구:
- STACK 시스템: 프로젝트/이슈/업무요청/고객사/유지보수계약/정기점검/서버 데이터 조회 및 관리
- 이메일 발송, 만료 계약 알림
- 이전 작업 기록 검색

도구 선택 가이드:
- 계약 정보/유지보수 계약/특정 고객 계약 → list_maintenance_contracts (search로 고객명 검색)
- **영업 담당자/영업담당자 확인** → list_maintenance_contracts(search=고객명) — 응답의 **salesManagerName** 필드에 영업담당자 이름이 있음. search_expiring_contracts는 영업담당자 조회에 사용하지 마세요!
- 특정 월에 종료되는 계약 → list_maintenance_contracts (contractEndMonth 파라미터 사용, 예: "2026-03")
- get_expiring_maintenance는 오직 "만료 임박/곧 만료" 질문에만 사용 (D-60 기본)
- 고객사 정보/고객 검색 → search_similar_customers 또는 list_customers (search 파라미터)
- Salesforce 거래처/영업 기회(opportunity) → search_integrated_customer 또는 search_expiring_contracts (Salesforce 데이터만 조회 가능. 영업담당자 조회용이 아님!)
- 이번 달 점검 → get_current_month_checkups
- 다음 달/특정 월 점검 → get_checkups_by_date_range(startDate, endDate, assigneeId) 사용. 예: 3월 점검 → startDate="2026-03-01", endDate="2026-03-31"
- 미완료/지연 점검 → get_pending_checkups(assignee=UUID) — assigneeId 필수!
- "내 점검" 등 본인 관련 → assigneeId에 사용자 UUID 전달
- 만료됐는데 ACTIVE인 계약 → get_expired_active_contracts 또는 list_maintenance_contracts(isExpiredButActive=true)
- 갱신 누락 감지 → get_contract_renewal_gaps
- 통합 고객 정보 → get_customer_card(customerId) 또는 search_maintenance_customer(query)
- 첫 번째 도구가 결과 없으면, 다른 도구로 재시도하세요. 예: search_integrated_customer 실패 → list_maintenance_contracts로 재검색

**[필수] ID 파라미터 규칙:**
- projectId, customerId, issueId, contractId 등 모든 ID 파라미터는 반드시 **UUID 형식**(예: "e90792d9-528b-4c8e-bdb8-c70744caa654")이어야 합니다.
- 프로젝트명("삼성전자-RC"), 고객명("삼성전자") 등 이름을 ID에 직접 넣으면 API가 실패합니다.
- 이름으로 조회하려면: ① 검색 파라미터를 사용하여 먼저 UUID를 찾고 → ② 그 UUID로 상세 조회하세요.

**[필수] 검색 시 search 파라미터 활용:**
- list_projects(search="삼성전자") → 삼성전자 관련 프로젝트만 필터링 (search 없이 호출하면 기본 20개만 반환되어 원하는 프로젝트가 누락될 수 있음!)
- list_customers(search="삼성전자") → 고객 검색
- list_issues(search="키워드") → 이슈 검색
- 예: "삼성전자 RC 프로젝트 멤버" → list_projects(search="삼성전자") → 결과에서 "삼성전자-RC" 프로젝트의 UUID 확인 → get_project_members(projectId=UUID)
- **주의**: 검색 결과에 동명 프로젝트가 여러 개 있을 수 있음 (완료/진행중 등). 상태(status)가 "IN_PROGRESS"이고 이름이 가장 정확히 일치하는 것을 선택하세요.

사고 프로토콜:
- 복잡한 질문을 받으면, 먼저 어떤 정보가 필요한지 생각하세요.
- 첫 번째 도구 결과가 부족하면, 다른 도구로 보완하세요.
- 여러 데이터를 조합해야 하면, 단계적으로 수집한 후 종합하세요.
- 결과가 비어있으면 "없습니다"로 끝내지 말고, 대체 도구를 시도하세요.

규칙:
1. **[최우선] 매번 반드시 도구를 호출하여 최신 데이터를 조회하세요.** 이전 대화 내역이나 [이전 작업 기록]의 데이터를 절대 재사용하지 마세요. 같은 질문이 반복되더라도 항상 새로 API를 호출해야 합니다. 도구 호출 없이 데이터를 답변하는 것은 금지됩니다.
2. **[중요] 답변은 오직 이번 턴에서 호출한 도구의 결과만 사용하세요.** 이전 대화에 나온 데이터(Salesforce 결과, 금액, 이전 API 응답 등)를 현재 답변에 절대 포함하지 마세요. 도구 결과에 없는 데이터는 답변에 넣지 마세요.
3. 결과는 한국어로, 핵심만 간결하게 정리하세요.
4. 고객사별로 그룹핑하여 보기 좋게 정리하세요.
5. 담당자 이름이 있으면 표시하세요.
6. 목록이 많으면 중요한 것 위주로 요약하고, 전체 수량도 알려주세요.
7. 오류가 발생하면 어떤 오류인지 간단히 설명하세요.
8. 고객사 ID(UUID)가 결과에 포함되면, 반드시 get_customer 또는 get_maintenance_contract로 고객사명을 조회해서 이름으로 표시하세요. UUID를 사용자에게 그대로 보여주지 마세요.
9. 모든 관련 데이터를 빠짐없이 보고하세요. "총 10개" 라면 10개 모두 표시하세요.
10. API 응답의 영문 enum 값은 반드시 한국어로 번역하세요:
   - 점검주기: MONTHLY=월간, QUARTERLY=분기, SEMI_ANNUALLY=반기, ANNUALLY=연간, REQUEST=요청시, PARTNER=파트너
   - 상태: ACTIVE=활성, EXPIRED=만료, PENDING=대기, COMPLETED=완료, IN_PROGRESS=진행중
   - 우선순위: HIGH=높음, MEDIUM=보통, LOW=낮음
   - 기타 영문 코드도 자연스러운 한국어로 변환하세요.
{memory_context}{plan_guidance}"""


def planner_node(state: dict) -> dict:
    """
    실행 계획 수립 + 도메인 필터링된 도구 준비 + oai_messages 초기화.

    Args:
        state: AgentState (complexity_level, active_domains, instruction,
               user_identity, memory_context, context_24h 등 필요)

    Returns:
        dict with keys: plan, oai_messages
    """
    from bot_brain import log, _generate_plan, TOOLS
    from gchat_sender import _send_message_impl
    from agent.tool_registry import get_tools_for_domains

    complexity_level: str = state.get("complexity_level", "SIMPLE")
    active_domains: list[str] = state.get("active_domains", [])
    instruction: str = state.get("instruction", "")
    user_identity: dict | None = state.get("user_identity")
    memory_context: str = state.get("memory_context", "")
    context_24h: str = state.get("context_24h", "")
    chat_id: str = state.get("chat_id", "")

    # ── 1. 사용자 신원 컨텍스트 ──
    user_identity_context = ""
    if user_identity:
        user_identity_context = (
            f"\n\n현재 사용자: {user_identity['name']} ({user_identity.get('email', '')})"
            f"\n사용자 UUID: {user_identity['uuid']}"
            '\n"내", "나의", "내꺼", "내 것" 등 본인 관련 질문 시 '
            "assigneeId, salesManagerId, engineerId 등에 이 UUID를 사용하여 필터링하세요."
        )

    # ── 2. 실행 계획 생성 ──
    plan: list[dict] = []
    plan_guidance = ""

    if complexity_level == "COMPLEX":
        log("[planner] COMPLEX 쿼리 → 실행 계획 생성 중...")
        try:
            raw_plan = _generate_plan(instruction, user_identity, TOOLS)
            if raw_plan:
                plan = [
                    {
                        "step": s.get("step", i + 1),
                        "tool": s.get("tool", "__fc_loop__"),
                        "purpose": s.get("purpose", ""),
                        "args_hint": s.get("args_hint", ""),
                        "status": "pending",
                    }
                    for i, s in enumerate(raw_plan)
                ]

                plan_text = "\n".join(
                    f"  {s['step']}. {s['purpose']} (도구: {s['tool']})"
                    for s in plan
                )
                log(f"[planner] 실행 계획:\n{plan_text}")

                # 사용자에게 계획 공유
                try:
                    _send_message_impl(
                        chat_id,
                        f"실행 계획:\n{plan_text}\n\n처리를 시작합니다...",
                    )
                except Exception:
                    pass

                # 시스템 프롬프트에 계획 주입
                plan_guidance = f"""

[실행 계획 - 반드시 모든 단계를 실행하세요]
아래 계획의 모든 단계를 순서대로 실행하세요. 단계를 건너뛰지 마세요.
{plan_text}

[분석 지침]
모든 도구 호출이 끝나면 반드시 다음을 포함하여 종합 분석하세요:
- 핵심 통계 (총 건수, 상태별 비율, 완료율 등)
- 주의 필요 항목 (만료 임박, 미완료 점검, 이상 데이터 등)
- 데이터 간 교차 분석 (계약은 있는데 점검이 없는 경우 등)
단순 나열이 아닌 인사이트와 요약을 제공하세요.
"""
            else:
                log("[planner] 계획 생성 실패 → 단일 FC 루프로 진행")
        except Exception as e:
            log(f"[planner] 계획 생성 예외 (단일 FC 루프로 진행): {e}")

    # SIMPLE / MODERATE 또는 COMPLEX 계획 실패 시 → 단일 FC 루프
    if not plan:
        plan = [
            {
                "step": 1,
                "tool": "__fc_loop__",
                "purpose": "OpenAI FC 루프로 처리",
                "args_hint": "",
                "status": "pending",
            }
        ]
        log(f"[planner] {complexity_level} → 단일 FC 루프 계획")

    # ── 3. 도메인 필터링된 도구 준비 ──
    filtered_tools = get_tools_for_domains(active_domains)
    tool_count = len(filtered_tools)
    total_count = len(TOOLS)
    log(f"[planner] 도구 필터링: {tool_count}/{total_count}개 (도메인: {active_domains})")

    # 필터링된 도구가 너무 적으면 전체 도구 사용
    if tool_count < 3:
        log("[planner] 필터링 도구 부족 → 전체 도구 사용")
        filtered_tools = TOOLS

    # ── 4. oai_messages 초기화 ──
    system_prompt = _build_system_prompt(
        state, memory_context, user_identity_context, plan_guidance
    )

    oai_messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
    ]

    # 24시간 대화 컨텍스트 추가
    if context_24h and context_24h != "최근 24시간 이내 대화 내역이 없습니다.":
        oai_messages.append(
            {"role": "user", "content": f"[최근 대화 참고]\n{context_24h}"}
        )

    # 사용자 지시사항 추가
    oai_messages.append({"role": "user", "content": instruction})

    # filtered_tools를 oai_messages 첫 번째 항목에 메타데이터로 저장
    # (executor가 꺼내 쓸 수 있도록 시스템 메시지에 _tools 키를 추가)
    oai_messages[0]["_tools"] = filtered_tools

    return {
        "plan": plan,
        "oai_messages": oai_messages,
        "current_step_index": 0,
    }
