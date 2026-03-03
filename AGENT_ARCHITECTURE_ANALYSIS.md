# 비서최재형 AI Agent 아키텍처 분석 & 설계 가이드

**작성일**: 2026-02-19
**분석 대상**: `D:\mybot_ver2` - OpenAI Function Calling 기반 업무 비서 봇
**현재 상태**: 반응형 단일 턴 처리 → Agent 패턴 전환 필요

---

## Executive Summary

현재 시스템은 **사용자 요청 → OpenAI Function Calling (10턴) → 결과 반환** 의 기본적인 도구 사용 봇입니다. 이를 **자율적 의사결정**, **계획 수립**, **목표 지향적 행동**을 수행하는 **진정한 AI Agent**로 전환하려면 아래의 전략적 변화가 필요합니다.

---

## 1. Agent 패턴 비교 분석

### 1.1 현재 구조 분석

```
사용자 메시지 (Google Chat)
    ↓
bot_brain.py (OpenAI API)
    ├─ for turn in range(10):  ← Function Calling Loop
    │  ├─ OpenAI 호출
    │  ├─ 도구 선택 & 실행
    │  └─ 결과 피드백 (도구 이용 가능 시)
    ↓
최종 응답 생성 및 전송
    ↓
chat_bot.py (메모리 저장)
```

**특징**:
- **반응형(Reactive)**: 사용자 요청에만 반응
- **도구 호출(Function Calling)**: 즉시적 문제 해결
- **메모리 축약**: 24시간 대화만 보존
- **단순 루프**: 10턴 제한, 도구 없으면 종료

**한계**:
- ❌ 사용자 부재 시 스스로 작업 불가
- ❌ 복잡한 목표를 하위 작업으로 분해 불가
- ❌ 데이터 변화 감지 및 능동적 대응 불가
- ❌ 작업 우선순위 판단 불가
- ❌ 학습된 패턴 또는 사용자 선호도 활용 불가

---

### 1.2 Agent 패턴 비교표

| 패턴 | 구조 | 적합성 | 구현 난도 | 프레임워크 |
|------|------|--------|---------|---------|
| **ReAct** (Reason + Act) | 생각 → 행동 → 관찰 반복 | ★★★★★ | 중간 | LangGraph, AutoGen |
| **Plan-and-Execute** | 계획 수립 → 단계별 실행 | ★★★★☆ | 중상 | LangGraph, AutoGen |
| **Observe-Think-Act (OTA)** | 상황 관찰 → 분석 → 행동 | ★★★★★ | 중상 | 직접 구현 가능 |
| **Hierarchical Goal** | 목표 분해 → 트리 구조 실행 | ★★★☆☆ | 상 | CrewAI |
| **Multi-Agent** (팀) | 여러 전문가 Agent 협력 | ★★★☆☆ | 상 | CrewAI, AutoGen |

---

### 1.3 **현재 프로젝트에 최적 패턴: ReAct + Observe-Think-Act (OTA) 하이브리드**

#### 왜 ReAct?
- **장점**: 단순하고 우아함, 각 턴마다 명확한 의사결정 포인트
- **코드양**: OpenAI Function Calling 기반으로 최소한의 변경만 필요
- **확장성**: Proactive 기능 추가 용이

#### 왜 OTA?
- **현재 시스템과 자연스러운 통합**: 이미 도구 기반 루프 존재
- **스케줄 기반 실행**: Windows 스케줄러와 호환성 높음
- **메모리 활용**: 과거 패턴 학습 가능

#### 제안 구조
```
╔═══════════════════════════════════════╗
║    OBSERVE PHASE (10초)               ║
║  - Pub/Sub 메시지 확인                 ║
║  - STACK API 이상 감지                 ║
║  - 사용자 선호도 업데이트              ║
║  - 스케줄 기반 자동 작업 체크           ║
╚═══════════════════════════════════════╝
              ↓
╔═══════════════════════════════════════╗
║    THINK PHASE (즉시)                 ║
║  - 현재 상황 분석 (메모리 검색)        ║
║  - 목표 설정 (지시사항 또는 자동)      ║
║  - 필요 도구 판단                      ║
║  - 계획 수립 (단계별)                  ║
╚═══════════════════════════════════════╝
              ↓
╔═══════════════════════════════════════╗
║    ACT PHASE (반복)                   ║
║  for each_subtask:                    ║
║    ├─ 도구 호출 (Function Calling)    ║
║    ├─ 결과 처리                        ║
║    └─ 진행 상황 업데이트               ║
╚═══════════════════════════════════════╝
              ↓
╔═══════════════════════════════════════╗
║    REPORT PHASE (완료)                ║
║  - 최종 결과 정리                      ║
║  - 메모리에 기록                       ║
║  - Google Chat 전송                    ║
╚═══════════════════════════════════════╝
```

---

## 2. 프레임워크 비교 분석

### 2.1 프레임워크 선택지

| 프레임워크 | 학습곡선 | OpenAI 통합 | 커스터마이징 | 프로덕션 준비도 | 권장도 |
|-----------|---------|-----------|-----------|-------------|------|
| **LangGraph** | 중상 | ★★★★★ | ★★★★★ | ★★★★★ | ⭐⭐⭐⭐⭐ |
| **AutoGen** | 중상 | ★★★★☆ | ★★★★☆ | ★★★★☆ | ⭐⭐⭐⭐☆ |
| **CrewAI** | 상 | ★★★★☆ | ★★★☆☆ | ★★★☆☆ | ⭐⭐⭐☆☆ |
| **직접 구현** | 하 | ★★★★★ | ★★★★★ | ★★★★☆ | ⭐⭐☆☆☆ |

### 2.2 현재 스택과의 호환성

#### LangGraph (최강 추천)
```python
# 최소 변경으로 통합 가능
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolExecutor

# 기존 TOOLS, execute_tool() 그대로 사용 가능
tool_executor = ToolExecutor(TOOLS)

# 기존 bot_brain 루프를 StateGraph로 래핑
graph = StateGraph(AgentState)
graph.add_node("plan", plan_step)
graph.add_node("act", act_step)
graph.add_node("observe", observe_step)
# ...
```

**장점**:
- ✅ 기존 `bot_brain.py` 90% 재사용 가능
- ✅ OpenAI와 native 통합 (tool_choice 지원)
- ✅ StateGraph로 명확한 상태 관리
- ✅ 메모리 및 대화 컨텍스트 구조화 용이
- ✅ 비동기 지원 (Google Chat Pub/Sub와 친화적)

**단점**:
- 새로운 개념 학습 필요 (Graph, State, Node)
- 문서 부족 (2025년 활발히 개선 중)

#### AutoGen
**장점**:
- 다중 Agent 협력 (팀 구성) 가능
- 사람-Agent 상호작용 (Human-in-the-Loop)

**단점**:
- OpenAI 이외 LLM 지원이 번거로움
- 구성이 다소 복잡함
- STACK API 기반 단일 Agent에는 오버킬

#### CrewAI
**장점**:
- 가장 선언적 문법 (쉬움)
- Role-based Agent 정의

**단점**:
- 커스터마이징 어려움
- Function Calling 세밀 제어 불가
- Windows 스케줄러와의 통합 약함

#### 직접 구현
**장점**:
- 완전한 제어

**단점**:
- 개발 시간 소모 (2-3주)
- 엣지 케이스 처리 복잡
- 유지보수 어려움

### 2.3 **최종 권장: LangGraph + 기존 코드 점진적 통합**

```
Phase 1 (1주): OpenAI Function Calling 루프 → LangGraph StateGraph로 마이그레이션
Phase 2 (2주): Observation/Planning 노드 추가
Phase 3 (3주): Proactive Agent 기능 (스케줄, 이상 감지)
Phase 4 (2주): 메모리 및 학습 시스템
```

---

## 3. Agent Loop 설계 (현재 → 개선)

### 3.1 현재 Loop (bot_brain.py)

```python
# ← L565-591
for turn in range(10):
    tc = "required" if turn == 0 else "auto"
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=oai_messages,
        tools=TOOLS,
        tool_choice=tc,
        temperature=0.3,
        max_tokens=4096,
    )
    choice = response.choices[0]
    msg = choice.message

    if not msg.tool_calls:
        final_response = msg.content
        break

    # Tool 처리
    for tool_call in msg.tool_calls:
        result = execute_tool(fn_name, fn_args)
        oai_messages.append({"role": "tool", ...})
```

**문제점**:
- 도구 기반만 반복 (pure Function Calling)
- 계획 단계 없음
- 관찰(Observation) 단계 분리 안 됨
- 메모리 재검색 안 함

### 3.2 제안: LangGraph + ReAct Loop

```python
from langgraph.graph import StateGraph, START, END
from typing import TypedDict, Annotated
import operator

class AgentState(TypedDict):
    # 기존
    messages: Annotated[list, operator.add]  # 메시지 누적
    chat_id: str
    instruction: str

    # 신규
    plan: str  # 계획 수립
    current_step: int
    completed_steps: list
    observation: str  # 관찰 결과
    thought: str  # 사고
    action: str  # 행동 예정
    next_action: str  # 다음 단계

def observe_node(state: AgentState) -> AgentState:
    """OBSERVE: 메시지/메모리/STACK 상태 조사"""
    # 1. 새 메시지 확인
    pending = check_chat()

    # 2. 관련 메모리 검색
    memories = search_memory(extract_keywords(state['instruction']))

    # 3. STACK API로 관련 데이터 조회 (예: 고객사 정보)
    context_data = {}

    return {
        **state,
        "observation": json.dumps({
            "messages": pending,
            "memories": memories,
            "context": context_data
        })
    }

def plan_node(state: AgentState) -> AgentState:
    """THINK: 계획 수립"""
    # OpenAI로 지시사항을 단계별 계획으로 분해
    plan_prompt = f"""
    사용자 요청: {state['instruction']}
    관찰 결과: {state['observation']}

    다음을 순서대로 실행할 계획을 세워주세요:
    1. (단계 1)
    2. (단계 2)
    ...

    JSON 형식으로 반환:
    {{
        "total_steps": 3,
        "steps": [
            {{"number": 1, "action": "list_maintenance_contracts", "args": {{}}}},
            ...
        ]
    }}
    """

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": "당신은 업무 계획 수립 AI입니다."},
            {"role": "user", "content": plan_prompt}
        ],
        temperature=0.3,
    )

    plan = response.choices[0].message.content

    return {
        **state,
        "plan": plan,
        "thought": f"계획 수립 완료: {len(json.loads(plan)['steps'])}단계"
    }

def act_node(state: AgentState) -> AgentState:
    """ACT: 계획 실행 (Function Calling)"""
    plan_data = json.loads(state['plan'])
    current_step = state['current_step']

    if current_step >= len(plan_data['steps']):
        return {**state, "next_action": "report"}

    step = plan_data['steps'][current_step]

    # Tool 호출
    result = execute_tool(step['action'], step['args'])

    # 진행 상황 Google Chat에 보고
    send_message_sync(
        state['chat_id'],
        f"📊 [{current_step+1}/{plan_data['total_steps']}] {step['action']} 실행 중..."
    )

    return {
        **state,
        "messages": [...],  # tool result 추가
        "current_step": current_step + 1,
        "completed_steps": state['completed_steps'] + [step]
    }

def should_continue(state: AgentState) -> str:
    """다음 노드 결정"""
    if state['current_step'] >= len(json.loads(state['plan'])['steps']):
        return "report"
    return "act"  # 다시 act 반복

def report_node(state: AgentState) -> AgentState:
    """REPORT: 최종 결과 정리 및 전송"""
    # 최종 응답 생성
    final_response = generate_final_response(state)

    # chat_bot.py의 report_chat() 호출
    report_chat(
        instruction=state['instruction'],
        result_text=final_response,
        chat_id=state['chat_id'],
        timestamp=state['timestamp'],
        files=state.get('files', [])
    )

    return {
        **state,
        "messages": [...],
        "next_action": END
    }

# Graph 구성
graph = StateGraph(AgentState)

graph.add_node("observe", observe_node)
graph.add_node("plan", plan_node)
graph.add_node("act", act_node)
graph.add_node("report", report_node)

graph.add_edge(START, "observe")
graph.add_edge("observe", "plan")
graph.add_edge("plan", "act")
graph.add_conditional_edges(
    "act",
    should_continue,
    {"act": "act", "report": "report"}
)
graph.add_edge("report", END)

agent = graph.compile()

# 실행
result = agent.invoke({
    "messages": [...],
    "chat_id": "spaces/XXX",
    "instruction": "...",
    "plan": "",
    "current_step": 0,
    "completed_steps": [],
    "observation": "",
    "thought": "",
    "action": "",
    "next_action": ""
})
```

**개선 효과**:
- ✅ 명확한 4단계 (Observe → Plan → Act → Report)
- ✅ 계획 수립 단계로 복잡한 요청 분해 가능
- ✅ 각 단계 결과 명시적 저장 (State)
- ✅ 진행 상황 실시간 보고
- ✅ 추후 기능 (메모리 활용, 적응학습) 추가 용이

---

## 4. Proactive Agent 설계

### 4.1 현재 상태: 순수 반응형

```
사용자 메시지 → 봇 반응
5분 폴링 (메시지 없으면 아무것도 안 함)
```

### 4.2 제안: 4가지 Proactive 행동

#### A. 일일 브리핑 (08:00)

```python
# 매일 8시에 자동 실행
@scheduled_task(time="08:00")
async def daily_briefing():
    """
    1. 미완료 점검 현황
    2. 만료 임박 계약 (D-30)
    3. 어제 완료된 업무요청
    4. 오늘 예정 점검
    """
    observation = {
        "pending_checkups": get_pending_checkups(),
        "expiring_contracts": get_expiring_maintenance(),
        "completed_jobs_yesterday": list_request_jobs(status="COMPLETED", created_after=yesterday()),
        "upcoming_checkups_today": get_upcoming_checkups(),
    }

    # THINK: 중요도 판단
    priority_items = prioritize(observation)

    # ACT: Google Chat 전송
    send_message_sync(CHAT_ID, format_briefing(priority_items))

# 구현 위치: bot_daemon.py (새로운 파일)
```

#### B. 이상 감지 (실시간)

```python
# bot_brain.py 시작 시마다 호출
def detect_anomalies():
    """
    STACK API 데이터 변화 감지
    - 긴급 이슈 생성 (우선도 높음)
    - 점검 미완료 (D-3 이상 경과)
    - 계약 갱신 미처리
    """
    # 마지막 체크 타임스탬프 (메모리)
    last_check = load_memory()['last_anomaly_check']

    # 새로운 긴급 이슈
    urgent_issues = stack_api("GET", "/api/issues",
                             params={"priority": "HIGH", "created_after": last_check})

    # 점검 미완료 (DUE 기한 통과)
    overdue_checkups = stack_api("GET", "/api/maintenance/issues/pending")

    # 분석 및 경고
    if urgent_issues or overdue_checkups:
        alert_message = f"""
        ⚠️ 긴급 이슈 감지:
        - 새 긴급 이슈: {len(urgent_issues)}개
        - 미완료 점검: {len(overdue_checkups)}개
        """
        send_message_sync(CHAT_ID, alert_message)

        # 메모리 업데이트
        update_memory('last_anomaly_check', datetime.now())
```

#### C. 점검 리마인드 (정기)

```python
# 매일 10:00, 14:00, 16:00
@scheduled_task(times=["10:00", "14:00", "16:00"])
async def checkup_reminder():
    """
    오늘/내일 예정 점검 중 미완료 항목 리마인드
    """
    pending = stack_api("GET", "/api/maintenance/issues/upcoming")

    # 담당자별 그룹핑
    by_assignee = group_by(pending, 'assignee')

    for assignee, items in by_assignee.items():
        message = f"📋 점검 리마인드 ({assignee})\n"
        for item in items:
            message += f"- [{item['contractName']}] {item['description']}\n"

        send_message_sync(CHAT_ID, message)
```

#### D. 계약 갱신 제안 (자동)

```python
# 매주 월요일 09:00
@scheduled_task(day_of_week="Monday", time="09:00")
async def renewal_suggestion():
    """
    D-60 이내 만료 계약 자동 조회 및 갱신 제안
    """
    expiring = get_expiring_maintenance()

    for contract in expiring:
        # 이전 갱신 기록 검사 (중복 방지)
        past_renewals = search_memory(f"갱신 제안: {contract['id']}")
        if past_renewals and past_renewals[0]['created_at'] > 1_week_ago:
            continue  # 최근 1주일 내 제안했으면 스킵

        # 자동 갱신 제안
        renewal_prompt = f"""
        계약: {contract['customerName']} - {contract['productCode']}
        현재 종료일: {contract['contractEndDate']}

        갱신을 제안하시겠습니까?
        [예] - 갱신 진행
        [아니오] - 스킵
        """

        send_message_sync(CHAT_ID, renewal_prompt)

        # 메모리에 제안 기록
        reserve_memory_chat(f"갱신 제안: {contract['id']}", CHAT_ID)
```

### 4.3 구현 파일 구조

```
D:\mybot_ver2\
├── bot_brain.py (현재 - 반응형)
├── bot_daemon.py (신규 - Proactive)
│   ├─ ScheduleManager
│   │  ├─ register_task(schedule, function)
│   │  └─ run_scheduled_tasks()
│   ├─ AnomalyDetector
│   │  └─ detect_and_alert()
│   └─ ProactiveAgent
│      ├─ daily_briefing()
│      ├─ checkup_reminder()
│      ├─ renewal_suggestion()
│      └─ ...
├── mybot_autoexecutor.bat (수정 - 주기 조정)
└── schedule_config.json (신규)
    {
      "schedules": [
        {"type": "daily", "time": "08:00", "action": "daily_briefing"},
        {"type": "interval", "interval": 300, "action": "detect_anomalies"},
        ...
      ]
    }
```

---

## 5. Planning System 설계

### 5.1 문제: 복잡한 요청의 분해

**사용자**: "2월 말 만료되는 계약들을 정리하고, 각 고객사의 담당자 이메일로 갱신 의사를 문의해줘"

**현재 동작** (10턴 내에 해결):
- ❌ 계획 없이 단계별 도구 호출
- ❌ 중간 실패 시 복구 불가능
- ❌ 결과 종합이 어려움

### 5.2 제안: Task Decomposition Engine

```python
class PlanningEngine:
    def decompose(instruction: str) -> Plan:
        """
        사용자 지시사항 → 실행 가능한 서브태스크로 분해
        """
        prompt = f"""
        다음 지시사항을 실행 가능한 단계로 분해하세요:
        "{instruction}"

        각 단계는:
        1. 명확한 목표
        2. 필요한 도구 (또는 도구 조합)
        3. 입력 파라미터
        4. 예상 결과

        JSON 형식:
        {{
          "total_steps": 3,
          "tasks": [
            {{
              "id": "task_1",
              "description": "2월 말 만료 계약 조회",
              "tools": ["list_maintenance_contracts"],
              "params": {{"contractEndMonth": "2026-02"}},
              "depends_on": []
            }},
            {{
              "id": "task_2",
              "description": "각 계약의 고객사 담당자 조회",
              "tools": ["list_customer_contacts"],
              "params_template": {{"customerId": "$task_1.customer_id"}},
              "depends_on": ["task_1"]
            }},
            {{
              "id": "task_3",
              "description": "담당자에게 갱신 의사 문의 이메일",
              "tools": ["send_email"],
              "params_template": {{
                "to": "$task_2.email",
                "subject": "계약 갱신 안내",
                "body": "..."
              }},
              "depends_on": ["task_2"]
            }}
          ]
        }}
        """

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )

        return Plan.from_json(response.choices[0].message.content)

class Plan:
    tasks: list[Task]

    def execute(self) -> dict:
        """
        DAG(방향성 비순환 그래프) 순서로 실행
        """
        results = {}

        for task in self.tasks:
            # 의존성 확인
            deps = [results[dep_id] for dep_id in task.depends_on]

            # 파라미터 템플릿 치환
            params = self.substitute_params(task.params_template, results)

            # 도구 실행
            result = execute_tool(task.tools[0], params)
            results[task.id] = result

            # 실시간 보고
            send_message_sync(
                self.chat_id,
                f"✅ [{task.id}] {task.description} 완료"
            )

        return results

# 사용 예시
engine = PlanningEngine()
plan = engine.decompose(instruction)
results = plan.execute()
```

### 5.3 동적 재계획 (Replanning)

```python
def execute_with_replanning(plan: Plan, chat_id: str, max_attempts=3):
    """
    실패 시 자동 재계획
    """
    for attempt in range(max_attempts):
        try:
            results = plan.execute()
            return results
        except ToolExecutionError as e:
            if attempt < max_attempts - 1:
                send_message_sync(chat_id, f"⚠️ {e}... 재계획 중...")

                # 실패 원인을 포함한 새 계획 생성
                failure_context = f"""
                이전 계획 실패:
                - 실패한 도구: {e.tool_name}
                - 오류: {e.message}

                다른 방법으로 다시 계획을 세워주세요.
                """

                new_plan = engine.decompose(
                    original_instruction + "\n" + failure_context
                )
                plan = new_plan
            else:
                raise
```

---

## 6. 장기 메모리 시스템 설계

### 6.1 현재 메모리 구조

```
tasks/
├── msg_abc123/
│   ├── task_info.txt       # 작업 정보
│   └── result.html         # 결과물
└── msg_def456/
    └── task_info.txt

gchat_messages.json         # 24시간 대화만
```

**한계**:
- ❌ 24시간 이상 이전 대화 불가
- ❌ 사용자 선호도 기록 없음
- ❌ 패턴 학습 불가

### 6.2 제안: 계층화 메모리 아키텍처

```
╔══════════════════════════════════════════════════════╗
║         AGENT LONG-TERM MEMORY SYSTEM                ║
╚══════════════════════════════════════════════════════╝

┌─ Short-term Memory (1시간)
│  └─ 현재 대화 컨텍스트 (RAM)
│     • 메시지 히스토리 (20개)
│     • 현재 작업 상태
│
├─ Medium-term Memory (24시간 - 7일)
│  └─ gchat_messages.json (확장)
│     • 사용자 메시지 + 봇 응답
│     • 작업 결과 요약
│     • 시간별 인덱싱
│
├─ Long-term Memory (만료까지)
│  └─ memory_index.json (신규)
│     {
│       "memories": [
│         {
│           "id": "mem_001",
│           "created_at": "2026-02-19 14:30:00",
│           "category": "customer",  # customer/task/pattern/preference
│           "keyword": ["삼성", "계약", "갱신"],
│           "summary": "삼성 유지보수 계약 2년 연장",
│           "task_dir": "tasks/msg_abc123/",
│           "embeddings": [...],  # 유사도 검색용 벡터
│           "usage_count": 5
│         },
│         ...
│       ]
│     }
│
├─ User Preference Memory (지속)
│  └─ user_preferences.json (신규)
│     {
│       "preferred_report_format": "table",
│       "preferred_contact_method": "email",
│       "important_customers": ["삼성", "LG"],
│       "frequent_tasks": ["점검현황", "계약갱신"],
│       "learned_patterns": [
│         {
│           "pattern": "매월 1일에 점검 현황 요청",
│           "confidence": 0.87
│         }
│       ]
│     }
│
└─ Knowledge Base (학습)
   └─ kb_entries.json (신규)
      {
        "entries": [
          {
            "question": "삼성 계약 ID가 뭐야?",
            "answer": "contract_uuid_123",
            "frequency": 3,
            "learned_from_context": "mem_001"
          }
        ]
      }
```

### 6.3 메모리 검색 개선 (의미 기반)

```python
from sentence_transformers import SentenceTransformer
import numpy as np

class SemanticMemorySearch:
    def __init__(self):
        self.model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
        self.memories = load_memory_index()

    def search(self, query: str, top_k=5) -> list[Memory]:
        """
        의미 기반 검색 (키워드가 정확하지 않아도 검색 가능)
        """
        # 쿼리 임베딩
        query_embedding = self.model.encode(query)

        # 저장된 메모리와 유사도 계산
        scores = []
        for mem in self.memories:
            mem_embedding = np.array(mem['embeddings'])
            score = np.dot(query_embedding, mem_embedding)
            scores.append((mem, score))

        # 상위 K개 반환
        return sorted(scores, key=lambda x: x[1], reverse=True)[:top_k]

    def save_memory(self, category: str, text: str, metadata: dict):
        """
        새로운 메모리 저장 + 임베딩 자동 생성
        """
        embedding = self.model.encode(text)

        memory = {
            "id": f"mem_{int(time.time())}",
            "created_at": datetime.now().isoformat(),
            "category": category,
            "text": text,
            "embeddings": embedding.tolist(),
            "metadata": metadata,
            "usage_count": 0
        }

        self.memories.append(memory)
        save_memory_index(self.memories)

# 사용 예시
memory_search = SemanticMemorySearch()

# 1. 메모리에서 관련 정보 검색
matches = memory_search.search("삼성의 유지보수 계약 상황")
# → "mem_001: 삼성 유지보수 계약 2년 연장"
# → "mem_045: 삼성 Q1 점검 계획"
# → ...

# 2. bot_brain.py의 system_prompt에 포함
context = "\n".join([m[0]['text'] for m in matches])
system_prompt = f"... [관련 과거 작업] {context}"
```

### 6.4 패턴 학습 (Preference Learning)

```python
class UserPreferenceLearner:
    def learn_from_interaction(self, chat_history: list, result: str):
        """
        사용자의 반응으로부터 선호도 학습
        """
        # 1. 보고서 포맷 선호도
        if "표로 정리해줘" in chat_history[-2].get('text', ''):
            self.update_pref('preferred_report_format', 'table')

        # 2. 중요 고객사 파악
        mentioned_customers = extract_entities(chat_history, type='customer')
        for cust in mentioned_customers:
            freq = self.count_mentions(chat_history, cust)
            if freq >= 3:
                self.mark_important_customer(cust)

        # 3. 반복되는 패턴 인식
        patterns = self.extract_temporal_patterns(chat_history)
        # 예: "매주 월요일에 점검 현황 요청"
        for pattern in patterns:
            if pattern['confidence'] > 0.8:
                self.register_pattern(pattern)

    def suggest_proactive_action(self) -> Optional[str]:
        """
        학습된 패턴 기반으로 능동적 행동 제안
        """
        today = datetime.now()

        for pattern in self.preferences['learned_patterns']:
            if pattern['trigger_matches'](today):
                # 예: "월요일 오전 9시 → 점검 현황 자동 조회"
                return pattern['action']

        return None
```

---

## 7. Observation System 설계 (이상 감지)

### 7.1 감시 대상

```
┌─ 긴급 이슈 감지
│  └─ 새로운 HIGH/CRITICAL 우선순위 이슈
│     → 사용자에게 즉시 알림
│
├─ 점검 오버헤드
│  └─ DUE date 경과한 미완료 점검
│     → 담당자에게 리마인드
│
├─ 계약 만료 임박
│  └─ D-30, D-14, D-7 지점
│     → 자동 갱신 제안
│
├─ 이상 데이터 감지
│  └─ API 응답 구조 변경
│  └─ 비정상적인 값 범위
│     → 로그 기록 + 관리자 알림
│
└─ 성능 저하
   └─ API 응답 시간 > 10초
   └─ 도구 호출 실패율 > 10%
      → 성능 리포트
```

### 7.2 구현

```python
class AnomalyDetector:
    def __init__(self):
        self.baseline_metrics = load_baseline_metrics()
        self.last_check = datetime.now()

    def detect_all(self) -> list[Anomaly]:
        """
        모든 이상 감지
        """
        anomalies = []

        # 1. 긴급 이슈
        urgent = self._check_urgent_issues()
        if urgent:
            anomalies.append(Anomaly(
                type="urgent_issue",
                severity="HIGH",
                message=f"긴급 이슈 {len(urgent)}개 발생",
                data=urgent
            ))

        # 2. 점검 오버헤드
        overdue = self._check_overdue_checkups()
        if overdue:
            anomalies.append(Anomaly(
                type="overdue_checkup",
                severity="MEDIUM",
                message=f"미완료 점검 {len(overdue)}개",
                data=overdue
            ))

        # 3. 계약 만료
        expiring = self._check_contract_expiry()
        if expiring:
            anomalies.append(Anomaly(
                type="contract_expiring",
                severity="MEDIUM",
                message=f"만료 임박 계약 {len(expiring)}개",
                data=expiring
            ))

        # 4. 성능 저하
        perf = self._check_performance()
        if perf['api_latency'] > 10.0:
            anomalies.append(Anomaly(
                type="performance_degradation",
                severity="LOW",
                message=f"API 응답시간 {perf['api_latency']:.1f}초",
                data=perf
            ))

        self.last_check = datetime.now()
        return anomalies

    def alert(self, anomalies: list[Anomaly]):
        """
        감지된 이상을 사용자에게 보고
        """
        by_severity = group_by(anomalies, 'severity')

        message = "🔔 이상 감지 리포트\n"
        for severity in ['HIGH', 'MEDIUM', 'LOW']:
            items = by_severity.get(severity, [])
            if items:
                message += f"\n[{severity}]\n"
                for item in items:
                    message += f"- {item.message}\n"

        send_message_sync(CHAT_ID, message)

        # 심각한 이상은 로그 기록
        for anom in by_severity.get('HIGH', []):
            log_anomaly(anom)

# 실행
detector = AnomalyDetector()
anomalies = detector.detect_all()
if anomalies:
    detector.alert(anomalies)
```

---

## 8. 현실적 구현 로드맵

### 단계 1: Agent Loop 기초화 (1주)

**목표**: 현재 Function Calling 루프 → LangGraph StateGraph로 전환

```
┌─ Task: bot_brain.py → bot_brain_langgraph.py
│  ├─ LangGraph 의존성 추가
│  ├─ AgentState 정의 (messages, instruction, ...)
│  ├─ observe_node 구현 (메모리 로드)
│  ├─ plan_node 구현 (계획 생성)
│  ├─ act_node 구현 (도구 호출)
│  └─ report_node 구현 (결과 정리)
│
├─ Task: 동작 테스트
│  ├─ 기존 테스트 케이스로 검증
│  ├─ 결과물 비교 (기존 vs 신규)
│  └─ 성능 측정
│
└─ Task: 기존 코드 통합
   ├─ bot_brain_langgraph.py → bot_brain.py (교체)
   └─ mybot_autoexecutor.bat 수정 불필요
```

**산출물**:
- `bot_brain_langgraph.py` (또는 기존 파일 수정)
- `test_langgraph_integration.py`
- 성능 리포트

**시간**: 5일

---

### 단계 2: Planning System (2주)

**목표**: 단순 도구 호출 → 계획 기반 실행

```
┌─ Task: PlanningEngine 구현
│  ├─ decompose() - 지시사항 → 단계별 계획
│  ├─ Plan 클래스 정의
│  └─ Task DAG 순서 실행
│
├─ Task: 재계획 로직
│  ├─ 실패 감지 및 재시도
│  ├─ 대체 경로 탐색
│  └─ 사용자 개입 옵션
│
└─ Task: 테스트
   ├─ 복합 지시사항 (3단계 이상)
   ├─ 실패 시나리오
   └─ 성공률 측정
```

**산출물**:
- `planning_engine.py`
- `test_planning.py`
- 사용 가이드

**시간**: 10일

---

### 단계 3: Proactive Agent (3주)

**목표**: 스케줄 기반 자동 행동

```
┌─ Task: ScheduleManager 구현
│  ├─ schedule_config.json 형식 정의
│  ├─ APScheduler 또는 직접 구현
│  └─ 스케줄 등록/해제 API
│
├─ Task: Proactive 행동 구현
│  ├─ daily_briefing()
│  ├─ checkup_reminder()
│  ├─ renewal_suggestion()
│  └─ anomaly_detection()
│
├─ Task: bot_daemon.py (백그라운드 프로세스)
│  ├─ 상시 실행 (별도 프로세스)
│  ├─ CPU/메모리 최적화
│  └─ 로그 관리
│
└─ Task: Windows 스케줄러 통합
   ├─ mybot_autoexecutor.bat 수정
   ├─ daemon 실행 여부 확인
   └─ 자동 재시작 설정
```

**산출물**:
- `bot_daemon.py`
- `schedule_config.json`
- `anomaly_detector.py`
- 설치/운영 가이드

**시간**: 15일

---

### 단계 4: 메모리 & 학습 시스템 (2주)

**목표**: 장기 메모리 + 의미 기반 검색 + 패턴 학습

```
┌─ Task: 메모리 아키텍처 확장
│  ├─ memory_index.json 구조 정의
│  ├─ user_preferences.json 구조
│  ├─ 메모리 마이그레이션 스크립트
│  └─ 백업/정리 정책
│
├─ Task: 의미 기반 검색
│  ├─ SentenceTransformer 통합
│  ├─ 임베딩 생성 및 저장
│  ├─ 유사도 검색 구현
│  └─ 성능 측정
│
├─ Task: 패턴 학습
│  ├─ UserPreferenceLearner 구현
│  ├─ 반복 패턴 인식
│  ├─ 능동적 제안 생성
│  └─ 테스트
│
└─ Task: 통합 테스트
   ├─ 메모리 로드/저장/검색
   ├─ 장기 실행 안정성
   └─ 문서화
```

**산출물**:
- `memory_system.py`
- `semantic_search.py`
- `preference_learner.py`
- 마이그레이션 가이드

**시간**: 10일

---

### 단계 5: 모니터링 & 최적화 (1주)

**목표**: 성능 측정, 에러 추적, 지속적 개선

```
┌─ Task: 모니터링 시스템
│  ├─ 메트릭 수집 (응답시간, 성공률, ...)
│  ├─ 이상 감지 대시보드
│  └─ 일일 리포트
│
├─ Task: 에러 처리 개선
│  ├─ 재시도 로직
│  ├─ Fallback 전략
│  └─ 에러 분류 & 로깅
│
└─ Task: 문서화
   ├─ Architecture Overview
   ├─ 운영 가이드
   └─ 트러블슈팅
```

**산출물**:
- `monitoring.py`
- `error_tracker.py`
- 종합 문서

**시간**: 5일

---

### 전체 타임라인

```
Week 1     │ ████ Stage 1 (LangGraph)
Week 2-3   │ ████████ Stage 2 (Planning)
Week 4-6   │ ██████████████ Stage 3 (Proactive)
Week 7-8   │ ██████████ Stage 4 (Memory/Learning)
Week 9     │ ████ Stage 5 (Monitoring)
           └─ 총 9주 (약 2개월)
```

**병렬 처리 가능 부분**:
- Stage 1과 Stage 2의 일부를 병렬 진행 가능 (1주 단축)
- → **총 8주 (약 7-8주)**

---

## 9. 구현 우선순위 & ROI 분석

### 9.1 각 기능별 구현 비용 vs 효과

| 기능 | 구현 비용 | 사용자 효과 | 수익성 | 우선순위 |
|------|---------|----------|-------|---------|
| **LangGraph 마이그레이션** | 낮음 | 중간 | ⭐⭐⭐ | 1순위 |
| **Planning System** | 중간 | 높음 | ⭐⭐⭐⭐ | 2순위 |
| **Daily Briefing** | 낮음 | 높음 | ⭐⭐⭐⭐ | 3순위 |
| **Anomaly Detection** | 낮음 | 높음 | ⭐⭐⭐⭐ | 4순위 |
| **Semantic Memory** | 높음 | 중간 | ⭐⭐⭐ | 5순위 |
| **Pattern Learning** | 높음 | 낮음 | ⭐⭐ | 6순위 |

### 9.2 단계별 달성 목표

```
┌─ Phase 1 (Week 1-2): MVP
│  └─ LangGraph 기반 안정적 구동
│     사용자 체감: "변화 없지만 안정적"
│
├─ Phase 2 (Week 3-4): 우수 기능
│  └─ Planning + Daily Briefing
│     사용자 체감: "복잡한 작업이 쉬워졌어"
│
├─ Phase 3 (Week 5-6): 능동성
│  └─ Proactive Agent + Anomaly Detection
│     사용자 체감: "봇이 혼자 일해!"
│
└─ Phase 4 (Week 7+): 지능형
   └─ Memory + Learning
      사용자 체감: "나를 아는 개인 비서"
```

---

## 10. 마이그레이션 체크리스트

### Phase 1: LangGraph 전환

- [ ] LangGraph 설치 (`pip install langgraph`)
- [ ] `AgentState` 정의
- [ ] `observe_node`, `plan_node`, `act_node`, `report_node` 구현
- [ ] 기존 `bot_brain.py`와 동작 비교 테스트
- [ ] 성능 측정 (응답시간, 메모리)
- [ ] 5명 이상 사용자 테스트
- [ ] 문제 없으면 `bot_brain.py` 교체
- [ ] 모니터링 강화 (1주)

### Phase 2: Planning System

- [ ] `PlanningEngine` 구현
- [ ] `decompose()` 함수 테스트
- [ ] DAG 실행 로직 검증
- [ ] 재계획 로직 추가
- [ ] 복합 지시사항 테스트 (3가지 이상)
- [ ] 가이드 작성

### Phase 3: Proactive Agent

- [ ] `bot_daemon.py` 구현
- [ ] `ScheduleManager` 구현
- [ ] 각 Proactive 기능 구현 (Daily Briefing, Reminder, Renewal, Anomaly)
- [ ] 스케줄 설정 파일 작성
- [ ] 백그라운드 프로세스 테스트
- [ ] Windows 스케줄러 통합
- [ ] 1주일 안정성 테스트

### Phase 4: Memory & Learning

- [ ] 메모리 구조 확장
- [ ] SentenceTransformer 통합
- [ ] 의미 기반 검색 구현
- [ ] 패턴 학습 로직
- [ ] 마이그레이션 스크립트
- [ ] 성능 측정 (검색 속도, 정확도)

### Phase 5: 운영

- [ ] 모니터링 대시보드
- [ ] 에러 추적 시스템
- [ ] 일일 리포트 자동화
- [ ] 문서 완성
- [ ] 팀 교육

---

## 11. 위험 요소 & 완화 전략

### 11.1 기술적 위험

| 위험 | 영향도 | 확률 | 완화 전략 |
|------|--------|------|---------|
| **LangGraph 버전 호환성** | 높음 | 중간 | 안정 버전 고정 (0.3.x 이상) |
| **메모리 누적으로 성능 저하** | 중간 | 높음 | 정기적 아카이빙 정책 수립 |
| **OpenAI API 비용 증가** | 높음 | 중간 | 토큰 제한, Plan-execution 최적화 |
| **백그라운드 프로세스 충돌** | 중간 | 낮음 | 엄격한 잠금 관리 (PID 확인) |
| **Windows 스케줄러 안정성** | 중간 | 낮음 | 폴백: PowerShell Task Scheduler |

### 11.2 운영 위험

| 위험 | 영향도 | 완화 전략 |
|------|--------|---------|
| **Daemon 프로세스 좀비화** | 중간 | 주기적 상태 체크 + 자동 재시작 |
| **메모리 누수** | 중간 | 정기 메모리 프로파일링 |
| **API 할당량 초과** | 높음 | 요청 스로틀링 + 배치 처리 |

---

## 12. 성공 지표 (KPI)

### Phase별 성공 기준

```
Phase 1 (LangGraph):
  ✓ 응답 정확도 >= 99% (기존 대비)
  ✓ 평균 응답 시간 < 30초
  ✓ 메모리 사용량 < 500MB

Phase 2 (Planning):
  ✓ 3단계 이상 복합 작업 성공률 >= 95%
  ✓ 자동 재계획 성공률 >= 80%
  ✓ 사용자 만족도 >= 4.0/5.0

Phase 3 (Proactive):
  ✓ Daily Briefing 정시 배포율 100%
  ✓ 이상 감지 False Positive < 10%
  ✓ 자동 알림 정확도 >= 95%

Phase 4 (Memory):
  ✓ 의미 기반 검색 정확도 >= 85%
  ✓ 메모리 조회 속도 < 500ms
  ✓ 패턴 학습 추천 정확도 >= 75%
```

---

## 13. 결론 & 권장사항

### 13.1 최종 선택지

**권장**: **LangGraph + ReAct + OTA 하이브리드 + 점진적 구현**

```python
# Phase 1 (즉시 시작)
├─ LangGraph로 기본 구조 전환
├─ observe → plan → act → report 흐름 확립
└─ 기존 기능 100% 호환성 유지

# Phase 2-4 (월별)
├─ Planning System 추가
├─ Proactive Agent 활성화
└─ Memory & Learning 고도화
```

**이유**:
1. **최소 변경**: 기존 코드 90% 재사용
2. **최대 효과**: 복합 기능 점진적 추가
3. **위험 최소화**: 각 Phase마다 검증 후 배포
4. **확장성**: 향후 Multi-Agent로 확장 가능

### 13.2 로드맵 요약

```
지금 (2026-02-19)
    ↓
[2주] LangGraph 기본 구조 (Stage 1)
    ↓
[2주] Planning System (Stage 2) ← 여기서 이미 "Agent"
    ↓
[3주] Proactive Agent (Stage 3) ← 여기서 자율성 극대화
    ↓
[2주] Memory/Learning (Stage 4) ← 여기서 지능형으로
    ↓
약 9주 후: 완전한 AI Agent 완성
```

### 13.3 지금 바로 할 일

1. **LangGraph 학습** (2일)
   ```bash
   pip install langgraph
   # 공식 튜토리얼 진행
   ```

2. **기본 구조 설계** (1일)
   - `AgentState` 정의
   - Node 분할 계획

3. **Prototype 구현** (3-4일)
   - 간단한 test case로 verify
   - 기존과 동작 비교

4. **검증 및 배포** (3-5일)
   - 실사용자 테스트
   - 모니터링 강화
   - 안정화

**총 2주 내 Phase 1 완료 가능**

---

## 부록

### A. 참고 자료

1. LangGraph 공식 문서: https://langchain-ai.github.io/langgraph/
2. ReAct 논문: https://arxiv.org/abs/2210.03629
3. OpenAI Function Calling: https://platform.openai.com/docs/guides/function-calling

### B. 코드 템플릿

#### LangGraph 기본 템플릿

```python
from langgraph.graph import StateGraph, START, END
from typing import Annotated, TypedDict
import operator

class AgentState(TypedDict):
    messages: Annotated[list, operator.add]
    chat_id: str
    instruction: str
    observation: str
    plan: str
    current_step: int
    next_action: str

def observe_node(state: AgentState) -> dict:
    # observation 수행
    return {"observation": "..."}

def plan_node(state: AgentState) -> dict:
    # plan 수립
    return {"plan": "..."}

def act_node(state: AgentState) -> dict:
    # plan 실행
    return {"current_step": state["current_step"] + 1}

def should_continue(state: AgentState) -> str:
    if state["current_step"] >= 3:
        return "end"
    return "act"

# Graph 구성
builder = StateGraph(AgentState)
builder.add_node("observe", observe_node)
builder.add_node("plan", plan_node)
builder.add_node("act", act_node)

builder.add_edge(START, "observe")
builder.add_edge("observe", "plan")
builder.add_edge("plan", "act")
builder.add_conditional_edges("act", should_continue, {"act": "act", "end": END})

graph = builder.compile()

# 실행
result = graph.invoke({
    "messages": [...],
    "chat_id": "...",
    "instruction": "...",
    "observation": "",
    "plan": "",
    "current_step": 0,
    "next_action": ""
})
```

### C. 마이그레이션 스크립트 예시

```python
# migrate_to_langgraph.py
import os
import sys
import shutil
from datetime import datetime

def backup_original():
    """기존 bot_brain.py 백업"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f"bot_brain.py.backup_{timestamp}"
    shutil.copy("bot_brain.py", backup_file)
    print(f"✅ Backup: {backup_file}")

def test_compatibility():
    """새 bot_brain (LangGraph)와 기존 동작 비교"""
    # 테스트 케이스 집합으로 양쪽 실행
    # 결과 비교 (응답 내용, 도구 호출 수, 성공률)
    pass

def rollback():
    """이전 버전으로 복구"""
    backups = sorted([f for f in os.listdir(".") if f.startswith("bot_brain.py.backup")])
    if backups:
        latest = backups[-1]
        shutil.copy(latest, "bot_brain.py")
        print(f"✅ Rollback: {latest}")

if __name__ == "__main__":
    backup_original()
    test_compatibility()
    print("Migration complete!")
```

---

**문서 작성 완료**: 2026-02-19

이 분석을 기반으로 다음 단계를 진행하시기 바랍니다.
