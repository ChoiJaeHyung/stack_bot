"""
router 노드 — Fast Path 매칭 + 복잡도 평가 + 의도/도메인 분류

instruction을 분석하여 라우팅 결정을 내린다:
  - Fast Path 매칭 (SIMPLE + 패턴 히트) → fast_path_tool/fast_path_args 세팅
  - 복잡도 평가 → SIMPLE / MODERATE / COMPLEX
  - 의도 분류 + 활성 도메인 결정
"""

from __future__ import annotations

import re
from typing import Any, Optional


def _infer_domains_by_keywords(instruction: str) -> list[str]:
    """
    DOMAIN_KEYWORDS를 이용해 키워드 기반 도메인 추론.

    Returns:
        매칭된 도메인 리스트 (빈 리스트 = 추론 실패)
    """
    from agent.constants import DOMAIN_KEYWORDS

    text = instruction.strip()
    matched: list[str] = []
    for domain, keywords in DOMAIN_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                matched.append(domain)
                break  # 같은 도메인 중복 추가 방지
    return matched


def _classify_with_llm(instruction: str) -> dict[str, Any]:
    """
    gpt-4o-mini로 의도 + 도메인 분류.

    Returns:
        {"intent": str, "domains": list[str]}
    """
    import json
    from bot_brain import client, AGENT_MODEL, log

    prompt = f"""사용자 요청을 분석하세요.

[요청]
{instruction[:500]}

[분류 기준]
intent (하나 선택):
  - lookup: 데이터 조회/검색
  - analysis: 분석/비교/통계
  - action: 생성/수정/삭제/실행
  - report: 보고서/리포트 생성

domains (해당하는 것 모두 선택):
  - maintenance_contract: 유지보수 계약, 영업담당자, 계약 담당자 (salesManagerName 포함)
  - checkup: 정기점검
  - customer: 고객사
  - server: 서버
  - salesforce: Salesforce 거래처/영업기회(opportunity) 데이터 조회 (영업담당자 조회는 maintenance_contract!)
  - project_issue: 프로젝트/이슈
  - request_job: 업무요청
  - product_license: 제품/라이선스
  - notification: 알림/메일
  - epic_label_comment: 에픽/라벨/댓글

반드시 아래 JSON만 반환하세요 (설명 없이):
{{"intent": "...", "domains": [...]}}"""

    try:
        response = client.chat.completions.create(
            model=AGENT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=200,
        )
        content = response.choices[0].message.content or ""

        # JSON 파싱 (코드 블록 처리)
        code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if code_block:
            content = code_block.group(1)
        else:
            brace_match = re.search(r"\{.*\}", content, re.DOTALL)
            if brace_match:
                content = brace_match.group()

        parsed = json.loads(content)
        return {
            "intent": parsed.get("intent", "lookup"),
            "domains": parsed.get("domains", []),
        }
    except Exception as e:
        log(f"[router] LLM 분류 실패: {e}")
        return {"intent": "lookup", "domains": []}


def _detect_write_operation(instruction: str, fast_path_tool: Optional[str]) -> bool:
    """쓰기 작업 여부 판별."""
    from agent.constants import WRITE_TOOLS as CONST_WRITE_TOOLS

    # Fast Path 도구가 쓰기 도구인 경우
    if fast_path_tool and fast_path_tool in CONST_WRITE_TOOLS:
        return True

    # 키워드 기반 판별
    write_keywords = re.compile(
        r"생성|만들|작성|수정|변경|삭제|제거|완료\s*처리|갱신|연장|배정|할당|보내|발송|전송"
    )
    return bool(write_keywords.search(instruction))


def router_node(state: dict) -> dict:
    """
    라우팅 결정: Fast Path / 복잡도 / 의도 / 도메인 / 쓰기 여부.

    Args:
        state: AgentState (instruction, user_identity 필요)

    Returns:
        dict with keys: intent, active_domains, complexity_score,
                        complexity_level, fast_path_tool, fast_path_args,
                        is_write_operation
    """
    from bot_brain import log, _fast_path_match, _assess_complexity

    instruction: str = state.get("instruction", "")
    user_identity: dict | None = state.get("user_identity")

    # ── Step 1: Fast Path 매칭 시도 ──
    fast_path_tool: Optional[str] = None
    fast_path_args: Optional[dict] = None

    # ── Step 2: 복잡도 평가 ──
    complexity_score, complexity_level = _assess_complexity(instruction)
    log(f"[router] 복잡도: {complexity_score}점 ({complexity_level})")

    # Fast Path는 SIMPLE 일 때만 시도
    if complexity_level == "SIMPLE":
        match = _fast_path_match(instruction, user_identity)
        if match:
            fast_path_tool, fast_path_args = match
            log(f"[router] Fast Path 매칭: {fast_path_tool}({fast_path_args})")

    # ── Step 3: 의도 + 도메인 분류 ──
    intent = "lookup"
    active_domains: list[str] = []

    if not fast_path_tool:
        # 3-a: 키워드 기반 도메인 추론
        active_domains = _infer_domains_by_keywords(instruction)

        if active_domains:
            # 키워드로 도메인을 찾았으면 의도만 간단히 판별
            if _detect_write_operation(instruction, None):
                intent = "action"
            elif re.search(r"비교|분석|통계|요약|종합|현황|추이|리포트|보고서", instruction):
                intent = "analysis"
            else:
                intent = "lookup"
            log(f"[router] 키워드 기반 도메인: {active_domains}, 의도: {intent}")
        else:
            # 3-b: 키워드로 부족하면 LLM 분류
            llm_result = _classify_with_llm(instruction)
            intent = llm_result["intent"]
            active_domains = llm_result["domains"]
            log(f"[router] LLM 분류 도메인: {active_domains}, 의도: {intent}")

        # 3-c: 도메인이 여전히 비어있으면 공통 도메인 전체 사용
        if not active_domains:
            active_domains = [
                "maintenance_contract", "checkup", "customer",
                "server", "project_issue", "request_job",
            ]
            log("[router] 도메인 미확인 → 공통 도메인 전체 사용")
    else:
        # Fast Path 매칭 시에는 해당 도구의 도메인만 설정
        from agent.constants import DOMAIN_GROUPS
        for domain, tools in DOMAIN_GROUPS.items():
            if fast_path_tool in tools:
                active_domains = [domain]
                break
        if not active_domains:
            active_domains = ["checkup", "maintenance_contract"]

    # ── Step 4: 쓰기 작업 여부 ──
    is_write_operation = _detect_write_operation(instruction, fast_path_tool)

    return {
        "intent": intent,
        "active_domains": active_domains,
        "complexity_score": complexity_score,
        "complexity_level": complexity_level,
        "fast_path_tool": fast_path_tool,
        "fast_path_args": fast_path_args,
        "is_write_operation": is_write_operation,
    }
