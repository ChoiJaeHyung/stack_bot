# 비서최재형 AI Agent 전환 시 위험성 분석 보고서

**작성일**: 2026-02-19
**대상**: Google Chat 기반 자율 처리 봇 → OpenAI Function Calling 기반 AI Agent 전환
**범위**: 현재 코드 기반 (bot_brain.py, chat_bot.py, daemon_wrapper.ps1)

---

## 1. 자율 행동 위험성 (Risk Level: 높음)

### 1.1 계약 수정/삭제 오판단 리스크

**발생 확률**: 높음 (GPT-4o도 hallucination 가능)
**영향도**: 매우 높음 (계약 데이터 손상)

**현황**:
- `update_maintenance_contract`: contractStartDate, contractEndDate, checkupCycle, salesManagerId, remarks 수정 가능
- `renew_maintenance_contract`: 자동 갱신 (new_end_date 파라미터)
- OpenAI Function Calling에 이 도구들이 노출됨 (bot_brain.py L130)

**세부 위험**:
- User: "3월에 끝나는 계약 갱신해줘" → Agent가 잘못된 계약 조회 후 갱신
  - 예: 검색 결과 10개 중 첫 번째 계약을 임의로 갱신
  - `list_maintenance_contracts(contractEndMonth="2026-03")` 결과 다중이면, Agent가 "최우선 이슈"를 선택해서 갱신
- "계약기간 1년 추가" → Agent가 `contractEndDate` 를 1년 늘렸는데, 실제로는 "2026-12-31"이어야 하는데 "2025-03-31" 계산 오류
- **근본 원인**: GPT-4o가 계약 정보의 "정확성"을 자체적으로 검증하지 않음. 도구 결과가 있으면 그대로 사용.

**대응 방안**:
- ✅ 쓰기 도구 앞에 "확인 단계" 추가: 수정 전 대상 계약을 명확히 출력 + 사용자 확인 요청
- ✅ `update_maintenance_contract`, `renew_maintenance_contract` 호출 전 검증 로직
  - 예: 특정 ID로 다시 조회 → 결과 출력 → "이 계약을 수정하시겠습니까? (Yes/No)"
- ⚠️ 현재 코드에는 이런 확인 메커니즘이 **없음**

---

### 1.2 이메일 발송 오판단

**발생 확률**: 중간 (다중 담당자 조회 시)
**영향도**: 높음 (오메일 발송 돌이킬 수 없음)

**현황**:
- `send_email`: to, subject, body 자유 형식 (bot_brain.py L158)
- Agent가 이메일 주소를 추측하거나 오타로 이메일 발송
- 예: "영업담당자에게 알려줘" → Agent가 `list_sales_managers()` 조회 → email 없음 → Agent가 "{name}@rsupport.com" 형식으로 추측

**세부 위험**:
- User: "최고경영진에게 보고 메일 보내줘" → Agent가 임의로 CEO 이메일 선택 후 기밀 정보 발송
- CC/BCC 필드 부재 → 대량 메일 발송 불가능하지만, 단일 잘못된 이메일은 발송됨

**대응 방안**:
- ✅ 이메일 발송 전 "수신자/제목/내용" 명시 출력 + 사용자 승인 요청
- ✅ `send_email` 도구 제거 또는 사전에 승인된 이메일 주소만 화이트리스트
- ✅ 현재 시스템: 메모리에 기반한 이메일 발송만 허용

---

### 1.3 이슈 대량 생성 위험

**발생 확률**: 중간
**영향도**: 중간 (작업 시스템 스팸화)

**현황**:
- `create_issue`: 반복문 없이 단일 호출만 지원하지만, Agent가 여러 프로젝트에 유사한 이슈 반복 생성 가능
- 예: "모든 프로젝트에 버그 리포트 만들어줘" → Agent가 `list_projects()` → 10개 프로젝트 순회 → 10개 이슈 생성

**세부 위험**:
- 중복 이슈 대량 생성으로 관리자 업무 부담 증대
- OpenAI 비용 증가 (API 호출 반복)

**대응 방안**:
- ✅ 반복 이슈 생성 전 "생성할 이슈 목록" 명시 출력 + 수량 확인
- ⚠️ 현재 코드에서 이런 가드레일이 없음

---

## 2. 비용 폭발 위험성 (Risk Level: 높음)

### 2.1 OpenAI API 비용 급증 메커니즘

**발생 확률**: 높음 (능동적 행동 = 상시 API 호출)
**영향도**: 높음 (월 수백만원→수천만원 가능)

**현황**:
- `bot_brain.py` L570: `client.chat.completions.create()` 호출
  - model: gpt-4o (가격: $0.075/1K tokens + $0.3/1K output tokens)
  - max_tokens: 4096 (고정)
  - Function calling loop: 최대 10 턴 (L565)

**비용 폭발 시나리오**:

1. **Polling 기반 에서 Autonomous 전환**
   - 현재: User가 메시지 보냄 → 5분 폴링 → bot_brain 실행 → 응답
   - 변경: Agent가 상시 구동 → 정기적으로 STACK API 조회 (예: 매시간 계약 검사) → GPT 비용 누적
   - 예: "매일 오전 9시에 만료임박 계약 확인해줘" → 365일 × 1회 × 50,000 tokens ≈ 월 30만 tokens ≈ 약 $600/월

2. **Function Calling Loop 반복**
   - 현재: 최대 10턴 제한, 실제 평균 2~3턴
   - 만약 복잡한 작업이면 10턴 모두 소비 가능
   - 예: "지난 3개월 미완료 점검 현황을 프로젝트별로 정리해줘"
     - Turn 1: list_maintenance_issues() → 50개 반환
     - Turn 2: 각 50개에 대해 get_maintenance_contract() 호출 불가능 (병렬화 없음) → 여러 턴 소비
     - 최악: 10턴 모두 소비 → 약 40,000 tokens ≈ $3~5 **1회 요청당**

3. **오류 재시도 무한 루프**
   - STACK API 503 에러 → Agent가 자동 재시도 (retry 로직 없음)
   - 예: STACK API 장애 1시간 동안 Agent가 5분마다 조회 시도 → 12회 × $3 = $36 낭비

**대응 방안**:
- ✅ **비용 한도 설정**: OpenAI API에 월 한도 설정 ($2,000/월 제안)
- ✅ **토큰 사용량 로깅**: 매 API 호출마다 tokens 기록 → 월말 리포트
- ✅ **Autonomous 태스크에 시간 제한**: "점검 현황 확인" = 월 1회만 허용
- ✅ **Batch API 검토**: 정기적 배치 작업은 OpenAI Batch API 사용 ($0.005/1K = 50% 할인)
- ⚠️ **현재 코드**: 비용 제어 메커니즘 전무

---

### 2.2 API 호출 비용 구조

| 시나리오 | 평균 Tokens | 비용 | 월 200회 기준 |
|---------|-----------|------|------------|
| 간단한 조회 (1~2턴) | 2,000 | $0.15 | $30 |
| 중간 복잡도 (3~5턴) | 5,000 | $0.38 | $76 |
| 복잡한 분석 (8~10턴) | 10,000 | $0.75 | $150 |
| 최악 (오류 반복) | 40,000+ | $3.00+ | $600+ |

**현재 실비용 추정**: 월 200회 사용 × 평균 4,000 tokens ≈ 약 **월 50,000 tokens ≈ $375/월**

---

## 3. Rate Limit 위험성 (Risk Level: 중간)

### 3.1 STACK API Rate Limit

**한도**: 일반적으로 분당 100~300회 (정확한 정보는 STACK 문서 참조)
**발생 확률**: 중간 (대량 데이터 조회 시)

**위험 시나리오**:
- User: "모든 고객사의 계약 현황을 엑셀로 정리해줘"
  - Agent: `list_customers()` → 200개 고객
  - Agent: 200개 각각에 대해 `get_customer_projects()` 호출 → 200 API calls
  - STACK API: 1분 내 300회 한도 → **과초과**
  - 결과: 429 Too Many Requests → 재시도 → 더 많은 요청

**현재 코드**:
- bot_brain.py L68-94: `stack_api()` 함수
  - retry 로직 **없음**
  - rate limit 체크 **없음**
  - timeout: 15초 (합리적)

**대응 방안**:
- ✅ **재시도 로직**: Exponential backoff (1s → 2s → 4s → 8s)
- ✅ **Rate limit 모니터링**: 429 응답 감지 → 1분 sleep
- ✅ **대량 조회 제한**: 100개 이상 항목은 "전체 조회"가 아닌 "필터링된 조회"만 허용
- ✅ **배치 처리 최적화**: `list_maintenance_contracts(size=200)` 활용

---

### 3.2 OpenAI API Rate Limit

**한도**: Gpt-4o는 일반적으로 500 RPM (Requests Per Minute)
**발생 확률**: 낮음 (단일 사용자)

**위험 시나리오**:
- 스케줄러가 5분마다 bot_brain 실행 × 12회/시간
- 만약 각 실행이 2개 OpenAI API 호출이면 → 24 calls/hour ≈ 1.6% 한도 사용
- 현실적으로는 위험 낮음

**대응 방안**:
- ✅ 모니터링만 필요

---

### 3.3 Google Chat API Rate Limit

**한도**: 프로젝트당 일반적으로 1,000 RPS (Requests Per Second)
**발생 확률**: 낮음 (단일 사용자)

**대응 방안**:
- ✅ 현재 코드: Pub/Sub 기반으로 Rate Limit 위험 거의 없음

---

## 4. 동시성 충돌 위험성 (Risk Level: 높음)

### 4.1 사용자 요청과 Autonomous 작업 동시 발생

**시나리오**:
```
08:00 - Scheduler가 자동 "계약 만료 알림" 시작 (Agent 자율 행동)
08:02 - User가 Google Chat에서 "새 프로젝트 만들어줘" 메시지 발송
        → 동시에 2개 작업 진행
        → working.json 잠금이 이미 있음 → User 요청 반려 또는 기다림
```

**현황**:
- chat_bot.py L99-159: `check_working_lock()` - 한 번에 1개 작업만 허용
- bot_brain.py L702-798: `run_loop()` - idle_timeout=300초 (5분)
- daemon_wrapper.ps1 L14: Interval=10초 (폴링)

**문제점**:
1. **자율 행동과 사용자 요청 우선순위 없음**
   - 자율 행동이 진행 중이면 User 요청 **대기**
   - 대기 시간: 최대 3분 (WORKING_LOCK_TIMEOUT, chat_bot.py L37)
   - User 경험 악화

2. **Race condition 가능성**
   - `check_working_lock()` 체크 → Lock 생성 사이에 다른 프로세스가 Lock 생성
   - `create_working_lock()` 사용 `open(..., "x")` (exclusive create) → 파일시스템 레벨 원자성 제공
   - ✅ 현재 코드는 안전함

3. **새 메시지 손실 가능성**
   - bot_brain.py L759-763: `check_new_messages_during_work()` 호출
   - 작업 중 새 메시지 감지 → `new_instructions.json` 저장
   - 그런데 **응답은 하지 않음** → User는 봇이 반응 없다고 생각

**대응 방안**:
- ✅ **비동기 큐 도입**: 자율 행동 vs 사용자 요청 분리
  - Queue A: 사용자 요청 (우선순위 높음)
  - Queue B: 자율 행동 (우선순위 낮음)
  - 스케줄러: Queue A가 비어 있을 때만 Queue B 실행

- ✅ **자율 행동 일정 고정**: "매일 08:00 GMT+9에만 계약 알림" → 사용자 활동 시간 외 설정

- ✅ **현재 코드**: 단순하지만 동시성 처리는 가능 (1개 작업씩 순차)

---

## 5. 다단계 작업 실패 복구 위험성 (Risk Level: 높음)

### 5.1 중간 단계 실패 시 상태 불일치

**시나리오**:
```
Step 1: 계약 조회 (OK) → ID: C-123
Step 2: 계약 갱신 (OK) → contractEndDate = 2027-03-31
Step 3: 이메일 발송 (FAIL) → Network error
Step 4: 메모리 저장 (OK) → "완료" 기록
Step 5: mark_done_chat() (OK) → User 메시지 "처리 완료"
```

**결과**: User는 "완료"라고 봤는데, 실제로는 이메일이 발송되지 않음

**현황** (bot_brain.py):
- L631-648: `report_chat()` 호출 → try/except로 감싸지 않음
- 만약 `send_files_sync()` 실패 → 예외 발생 → `mark_done_chat()` 미실행
- chat_bot.py L875: `send_files_sync()` 실패 → `success=False` → `result_text` 변경
- L887: "전송 실패" 기록만 함

**문제점**:
1. **부분 실패 처리 정책 없음**
   - 계약 갱신 + 이메일 발송 작업에서 이메일만 실패
   - User는 "작업 완료" 메시지를 받음 → 실제로는 이메일 못 받음
   - 재시도 메커니즘 없음

2. **트랜잭션 개념 없음**
   - 각 API 호출이 독립적 → Rollback 불가능
   - 예: 계약 갱신 후 이메일 발송 실패 → "계약만 수정됨"

3. **타임아웃 처리 미흡**
   - bot_brain.py L570-577: OpenAI timeout=60초 고정
   - STACK API timeout=15초 고정
   - 네트워크 지연 시 타임아웃 → "오류" 처리 → User 메시지 됨

**대응 방안**:
- ✅ **부분 실패 감지**: 각 주요 단계를 try/except/else로 나누어 "성공/실패" 명시 기록
- ✅ **재시도 로직**: 실패한 단계만 재시도 (지수 백오프)
- ✅ **사용자 알림**: "작업 완료 (부분 실패)" 메시지 → 어느 부분이 실패했는지 명확히
- ✅ **롤백 불가 메시지**: "계약이 이미 갱신되었으나, 이메일 발송 실패. 수동 발송 필요"

---

## 6. 보안 통제 위험성 (Risk Level: 높음)

### 6.1 권한 범위 제한 부재

**현황**:
- bot_brain.py L337-338: `send_email` 도구 제공 → 누구나 이메일 발송 가능
- L290-293: `update_maintenance_contract` → 계약 수정 가능
- L288-289: `renew_maintenance_contract` → 계약 갱신 가능

**위험 시나리오**:
1. **모든 도구가 동일 권한으로 노출**
   - 단일 사용자(jhchoi@rsupport.com)만 접근 가능하지만, Agent의 판단 오류 가능
   - Agent가 "영업담당자 메일 발송" → 기밀 정보 누출

2. **CRUD 도구 모두 노출**
   - Create: `create_issue`, `create_request_job`
   - Read: `list_projects`, `list_customers` 등 모두
   - Update: `update_issue`, `update_maintenance_contract` 등
   - Delete: `delete_issue` (bot_brain.py L106)
   - **Delete 도구는 위험함** → 복구 불가능

3. **민감한 정보 조회 제한 없음**
   - `get_customer` → 고객사 정보 (계약금액, 담당자 등) 모두 노출
   - Agent가 임의로 고객 정보 외부 메일로 발송 가능

**대응 방안**:
- ✅ **쓰기 도구 제한**: Create, Update, Delete 도구는 사전 승인 필요
  - 예: `update_maintenance_contract` 호출 전 User 승인 요청

- ✅ **민감한 정보 마스킹**:
  - 고객 이메일, 전화번호는 조회만 가능 (발송은 불가)
  - 계약금액은 조회만 가능 (수정 불가)

- ✅ **도구 화이트리스트/블랙리스트**:
  - 화이트리스트: 읽기 도구만 기본 제공
  - 블랙리스트: delete_issue, send_email 등 위험 도구 제거

---

### 6.2 STACK API 키 노출

**현황**:
- bot_brain.py L62: `STACK_API_KEY = os.getenv("STACK_API_KEY", "")`
- .env 파일에 저장 (CLAUDE.md에서 권장)
- ✅ .gitignore에 포함되어야 함

**위험 시나리오**:
- .env 파일 실수로 Git 커밋
- 코드 리뷰 시 .env 노출
- 로그에 API 키 기록

**현재 상태**:
- bot_brain.py L605: 로그에 `fn_args` 기록 → API 키는 포함되지 않음 (✅ 안전)
- chat_bot.py L40-48: devnull 리다이렉트 → stdout 누수 없음 (✅ 안전)

**대응 방안**:
- ✅ 현재 코드는 보안 처리 잘됨
- ⚠️ 단: .env 파일 외부 노출 주의

---

## 7. 사용자 신뢰 위험성 (Risk Level: 높음)

### 7.1 잘못된 정보 제공

**시나리오**:
```
User: "올해 3월에 끝나는 계약 몇 개야?"
Agent: "2개입니다: A사(갱신), B사(미갱신)"
실제: 3개 (C사 빠짐)

Agent가 API 조회 오류를 감지하지 못했거나,
truncation으로 인해 일부 결과가 잘렸을 수 있음
```

**현황** (bot_brain.py):
- L612: `truncate_json(result, max_len=8000)` - 결과 자르기
- L545-550: System prompt에 "모든 관련 데이터를 빠짐없이 보고" 명시
- 그런데 truncation은 강제로 일어남

**문제점**:
1. **Truncation으로 인한 정보 손실**
   - API 결과가 8000자를 초과하면 "... (truncated)" 표시
   - Agent가 불완전한 데이터로 응답
   - System prompt는 "모두 보여주라"인데, 데이터 자체가 잘려있음

2. **API 오류를 "데이터 없음"으로 잘못 해석**
   - bot_brain.py L86-87: HTTP 400+ → `{"error": "..."}`
   - Agent가 이를 "요청한 항목이 없다"로 해석 가능
   - 실제로는 API 오류 (네트워크, 서버 장애)

3. **데이터 유효성 검증 없음**
   - API 응답이 이상하더라도 Agent는 그대로 사용
   - 예: `list_maintenance_contracts()` 응답에 일부 필드 누락 → Agent가 부분적으로 보고

**대응 방안**:
- ✅ **데이터 검증**: API 응답 후 필드 검증
  - 예: `get_maintenance_contract()` 응답에 contractEndDate 없으면 → 오류로 처리

- ✅ **Truncation 경고**: 결과가 잘렸으면 "전체 결과는 파일로 전송" + 파일 첨부

- ✅ **API 오류 구분**:
  - 네트워크 오류 (timeout) → "재시도 권고"
  - 데이터 없음 (204) → "조회 결과 없음"
  - 서버 오류 (500+) → "시스템 장애, 나중에 다시"

---

### 7.2 확인 절차 부재

**시나리오**:
```
User: "계약 A를 갱신해줘"
Agent: (자동으로 갱신 실행)
        새 종료일: 2028-03-31 → 완료

User: (나중에 실수로 갱신됨을 알면) "아, 이건 아니었는데..."
      → 복구 불가능 (STACK API에 기록됨)
```

**현황**:
- bot_brain.py에서 쓰기 도구 (update, create, delete) 호출 전 User 확인 **없음**
- 즉시 실행 후 결과 보고

**대응 방안**:
- ✅ **쓰기 작업 확인 절차**:
  1. Agent: "다음 작업을 수행하려고 합니다:\n[상세 내용 출력]"
  2. User: "예"/"아니오" 응답 기다림
  3. Agent: 확인 후 실행

- ✅ **기본값 설정**:
  - 중요한 작업은 기본값 = "거부" (User가 명시적으로 승인해야 함)

---

## 8. 테스트/디버깅 위험성 (Risk Level: 중간)

### 8.1 재현성 낮음

**문제**:
- Agent의 행동이 비결정적 (OpenAI 응답이 매번 다름)
- 예: A사 계약 조회 요청
  - 1차: Agent가 `search_similar_customers("A사")` → 정확히 찾음
  - 2차: Agent가 `list_customers(page=1)` → 스크롤 후 찾음
  - 3차: Agent가 `search_integrated_customer("A사")` → 다른 방식 찾음
  - → 같은 결과이지만 경로가 다름

**현황**:
- bot_brain.py L568: `tool_choice="required"` (첫 턴), `tool_choice="auto"` (이후)
- 도구 호출 순서는 Agent가 결정
- 로그에는 호출된 도구와 결과만 기록 (bot_brain.py L605)

**대응 방안**:
- ✅ **로깅 강화**:
  - System prompt 전체 로깅
  - 각 tool_call 입력/출력 로깅
  - OpenAI 응답 전체 로깅 (tokens 포함)

- ✅ **재현 테스트**:
  - 중요한 작업은 User 확인 후 기록 → 재현 테스트 가능
  - 예: "계약 갱신" 작업은 message_id + instruction 저장 → 나중에 replay 가능

---

### 8.2 디버깅 어려움

**문제**:
- bot_brain.py L23-24: stdout/stderr를 devnull로 리다이렉트
- 스택 트레이스 추적 어려움
- 원격 환경(Windows 스케줄러)에서 실행되므로 콘솔 접근 불가

**현황**:
- bot_brain.log에만 기록 (L34)
- 에러 발생 시 로그 파일 확인해야 함

**대응 방안**:
- ✅ **구조화된 로깅**: JSON 형식 로깅 → 후처리 용이
- ✅ **원격 로깅**: 로컬 파일 대신 클라우드 로깅 서비스 (Google Cloud Logging)
- ✅ **에러 알림**: 중요한 오류 발생 시 User에게 Google Chat으로 알림

---

## 9. 감사 추적 위험성 (Risk Level: 중간)

### 9.1 Agent 행동 기록 부재

**문제**:
- Agent가 어떤 결정을 내렸고, 왜 그 도구를 선택했는지 기록 **없음**
- 감사(Audit)이 어려움

**현황**:
- bot_brain.log에 도구 호출과 결과는 기록 (L605)
- 하지만 Agent의 "의사결정 로직"은 기록 안 됨

**예시**:
```
[2026-02-19 10:00:00] Tool call: list_customers(search="A사")
[2026-02-19 10:00:01] Result: 3 customers found
← 그런데 Agent가 왜 list_customers를 선택했는가?
  다른 방법은 왜 안 썼는가? 기록 없음
```

**대응 방안**:
- ✅ **Agent의 "생각(chain-of-thought)" 기록**:
  - OpenAI response의 `finish_reason`, `content` 저장
  - System prompt 변경: 매 단계마다 "왜 이 도구를 선택했는지" 로깅하도록 유도

- ✅ **메타데이터 기록**:
  - message_id, instruction, agent_response, tools_used, duration, tokens_used, cost
  - 이를 기반으로 감사 리포트 생성 가능

- ✅ **변조 방지**:
  - 로그 파일에 타임스탬프 + 서명 추가 (향후)

---

## 10. Windows 환경 제약 위험성 (Risk Level: 중간)

### 10.1 프로세스 관리 문제

**시나리오**:
```
08:00 - 스케줄러가 bot_brain.py 실행 (PID: 1234)
08:05 - bot_brain.py가 여전히 실행 중 (긴 작업)
08:05:30 - 스케줄러가 다시 bot_brain.py 실행 시도 (PID: 5678)
→ 동시에 2개 process 실행 (잠금 파일로는 차단되지만)
```

**현황**:
- daemon_wrapper.ps1 L29-53: 무한 루프로 bot_brain 재실행
- 각 실행은 독립적인 프로세스
- chat_bot.py의 `create_working_lock()` (L162-204)로만 동시성 제어

**문제점**:
1. **Process Zombie 가능성**
   - bot_brain 크래시 → 프로세스 종료 안 됨 → 좀비 프로세스
   - Windows 작업 스케줄러는 좀비 감지 불가
   - 10초 마다 반복 실행 → 누적됨

2. **메모리 누수**
   - daemon_wrapper.ps1에서 무한 루프 + bot_brain 반복 호출
   - Python 프로세스 메모리 누수 → 시간 지나면서 메모리 증가
   - daemon_wrapper 예외 처리 (L47-49)에만 의존

3. **로그 파일 무한 증가**
   - bot_brain.log (L34) + bot_daemon.log (daemon_wrapper.ps1 L13)
   - 매 10초마다 로그 기록 → 월 수십 MB
   - 디스크 가득 가능

**대응 방안**:
- ✅ **Process Health Check**:
  - daemon_wrapper.ps1 실행 전 이전 bot_brain 프로세스 확인
  - 좀비 프로세스 kill: `Get-Process python | Where-Object {...} | Stop-Process`

- ✅ **메모리 모니터링**:
  - 매 10회 실행마다 메모리 체크 → 초과 시 프로세스 restart

- ✅ **로그 로테이션**:
  - bot_brain.log 일일 로테이션 (bot_brain.20260219.log)
  - 7일 초과 로그 삭제

---

### 10.2 크래시 복구 미흡

**시나리오**:
```
08:15 - bot_brain.py 크래시 (예: Python 런타임 에러)
        - working.json은 그대로 남음
        - daemon_wrapper L40-44는 working.json 삭제 시도
        - 하지만 대기할 User에게는 응답 안 함
```

**현황**:
- bot_brain.py L800-827: try/except/finally로 감싼 메인 루프
- daemon_wrapper.ps1 L40-44: 크래시 후 working.json 삭제
- chat_bot.py L99-159: 스탈 작업 감지 (30분 타임아웃)

**문제점**:
1. **크래시 시 User 알림 없음**
   - daemon_wrapper가 .log 파일에만 기록
   - User는 봇이 반응 없다고 생각

2. **30분 타임아웃이 너무 김**
   - WORKING_LOCK_TIMEOUT = 180초 (chat_bot.py L37)
   - 하지만 실제로는 3분이 아니라 check_working_lock() 호출 시점이 중요
   - polling interval 5분 × 스케줄러 간격 → 최악 5분+ 대기

**대응 방안**:
- ✅ **크래시 감지 후 User 알림**:
  - daemon_wrapper가 bot_brain 크래시 감지 → Google Chat으로 알림 발송
  - "이전 작업이 중단됨. 처음부터 다시 시작합니다."

- ✅ **타임아웃 단축**: WORKING_LOCK_TIMEOUT = 180초 → 60초로 변경
  - 보수적으로 1분 이상 응답 없으면 재시작

---

## 11. Google Chat 폴링 주기와 실시간성 갈등 (Risk Level: 중간)

### 11.1 Pub/Sub 5분 폴링의 한계

**문제**:
- 현재: gchat_listener.py가 5분 마다 Pub/Sub 메시지 수집
- User가 08:00에 메시지 보냄 → bot_brain이 08:05에야 처리 시작
- **최대 5분 지연**

**Autonomous Agent의 변화**:
- 만약 Agent가 "정기 점검 현황 일일 리포트"를 08:00에 자동 실행
- 동시에 User 메시지도 08:00~08:05에 들어옴
- 어느 것이 먼저 처리되는가? → 불명확

**현황**:
- GCHAT_POLLING_INTERVAL = 10 (CLAUDE.md, .env)
- 하지만 실제로는 스케줄러가 5분 마다 실행 (mybot_autoexecutor.bat)
- gchat_listener.py (확인 필요)에서 최종 interval 결정

**대응 방안**:
- ✅ **우선순위 큐**: User 요청 > 자율 행동
- ✅ **자율 행동 시간 고정**: "08:00 UTC+9" 에만 실행 → 충돌 최소화
- ⚠️ **실시간성 요구**: 1분 이내 응답이 필수라면 polling → Pub/Sub Streaming으로 변경 (향후)

---

## 12. 데이터 정합성 위험성 (Risk Level: 중간)

### 12.1 동시 API 호출로 인한 Race Condition

**시나리오**:
```
Agent의 Function Calling Loop (bot_brain.py L562-626)

Turn 1: list_maintenance_contracts() → C1, C2, C3 조회
Turn 2: get_maintenance_contract(C1) → detail 조회 (시간 경과)
        [동시에 STACK에서 C1이 갱신됨]
Turn 3: get_maintenance_contract(C2) → 다른 버전의 C1 데이터 사용
```

**현황**:
- bot_brain.py L565-626: 최대 10턴, 각 턴은 sequential
- 하지만 턴 사이에 시간 경과 → 다른 프로세스가 데이터 변경 가능

**문제점**:
1. **Snapshot isolation 없음**
   - API는 매번 최신 데이터를 반환
   - 일관된 스냅샷을 보장하지 않음

2. **Agent가 일관성을 인식하지 못함**
   - Turn 1에서 "C1, C2, C3 있음" → Turn 2에서 C1 조회 → 다른 데이터
   - System prompt에 "데이터 재조회 필수" 있지만, 이것이 일관성을 보장하진 않음

**대응 방안**:
- ✅ **조회 전 타임스탐프 기록**:
  - Turn 1: `list_maintenance_contracts(asOfTime=2026-02-19T10:00:00)`
  - Turn 2+: 동일한 asOfTime으로 조회 (STACK API가 지원해야 함)

- ✅ **변경 감지**: 턴마다 데이터 버전 체크 → 변경되었으면 재조회

- ⚠️ **현재**: STACK API 기능에 의존 (API가 지원하지 않으면 불가)

---

## 정리: 종합 리스크 지도

| 항목 | 리스크 | 영향도 | 발생확률 | 현재 상태 | 우선순위 |
|-----|--------|--------|---------|---------|---------|
| 자율 행동 오판단 | 높음 | 매우높음 | 높음 | 미처리 | **P0** |
| 비용 폭발 | 높음 | 높음 | 높음 | 미처리 | **P0** |
| Rate Limit | 중간 | 중간 | 중간 | 부분처리 | P1 |
| 동시성 충돌 | 높음 | 중간 | 낮음 | 처리됨 | P1 |
| 다단계 실패 복구 | 높음 | 높음 | 중간 | 부분처리 | **P0** |
| 권한 제어 부재 | 높음 | 높음 | 중간 | 미처리 | **P0** |
| 잘못된 정보 제공 | 높음 | 높음 | 중간 | 부분처리 | **P0** |
| 테스트/디버깅 | 중간 | 중간 | 높음 | 부분처리 | P1 |
| 감사 추적 | 중간 | 중간 | 높음 | 미처리 | P1 |
| Windows 제약 | 중간 | 중간 | 중간 | 부분처리 | P1 |
| Polling 지연 | 중간 | 낮음 | 높음 | 처리됨 | P2 |
| 데이터 정합성 | 중간 | 낮음 | 낮음 | 미처리 | P2 |

---

## 권장 사항

### 즉시 조치 (P0)

1. **자율 행동 금지** → User 요청만 처리하도록 제한
   - Autonomous 행동 (정기 리포트, 자동 알림)은 구현하지 말 것

2. **쓰기 도구 확인 절차 추가**
   - Update/Create/Delete 전 User 승인 요청

3. **비용 상한선 설정**
   - OpenAI API 월 한도: $2,000 (또는 더 낮게)

4. **Truncation 처리**
   - 결과 길이 체크 → 8000자 초과 시 파일로 전송

### 단기 개선 (P1)

1. **Rate Limit 재시도** 로직 추가
2. **Error Recovery** 메커니즘 개선
3. **로깅 강화** (구조화된 로깅)
4. **프로세스 Health Check** (daemon_wrapper 개선)

### 장기 개선 (P2)

1. **감사 추적** 시스템 구축
2. **원격 로깅** (Cloud Logging 전환)
3. **Pub/Sub Streaming** (폴링 → 스트리밍)
4. **데이터 일관성** 메커니즘 (버전 관리)

---

## 결론

**비서최재형이 AI Agent로 전환되려면:**

1. **현재는 "지시형 봇"** (User 요청 → 처리)
   - Autonomous 행동 가능하지만, **위험성이 매우 높음**

2. **따라서 권장**:
   - ✅ User 요청 처리만 허용 (읽기 중심)
   - ✅ 쓰기 작업은 User 승인 후 실행
   - ✅ 자동화 작업(정기 리포트, 알림)은 STACK API 직접 호출로 구현 (Agent 거치지 않음)

3. **만약 Autonomous 행동이 꼭 필요하다면**:
   - ✅ 별도의 "Autonomous Agent" 프로세스 분리
   - ✅ 엄격한 권한 제어 (읽기 전용 도구만)
   - ✅ 검증 및 테스트 강화
   - ✅ 비용/Rate Limit 모니터링 자동화

---

**작성자**: Claude AI
**분석 기준**: bot_brain.py, chat_bot.py, daemon_wrapper.ps1 코드 기반
**분석 일시**: 2026-02-19
