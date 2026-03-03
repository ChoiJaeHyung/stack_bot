# CLAUDE.md

## 프로젝트 개요

**비서최재형** - Google Chat 기반 AI 업무 비서 봇

- **플랫폼**: Google Chat (Pub/Sub)
- **LLM**: OpenAI GPT-4o (Function Calling)
- **Agent 기능**: Reflection (결과 검증) + Proactive Agent (자율 행동)
- **사용자**: jhchoi@rsupport.com
- **GCP 프로젝트**: assistant-jh

---

## 보안 정책

- Google Cloud Service Account 키와 허용 사용자 이메일은 `.env` 파일로만 관리한다.
- `assistant-jh-*.json` (서비스 계정 키)은 Git에 커밋하지 않는다.
- `.env` 파일은 이 프로젝트 루트에 유일하게 관리되며, 코드 본문에 직접 적지 않는다.
- `.env`는 Git에 커밋하지 않는다 (`.gitignore`에 추가).
- Credentials는 dotenv 라이브러리를 통해 런타임에 로드한다.

---

## 아키텍처

```
사용자 → Google Chat → Pub/Sub Topic → Subscription
                                            ↓
                                    bot_brain_daemon.py (상시 실행, 5초 폴링)
                                    메시지 없으면 → Proactive Agent 체크
                                    메시지 있으면 ↓
                                    bot_brain.py
                                            ↓
                                    Fast Path 매칭 → hit → STACK API + gpt-4o-mini
                                            ↓ miss
                                    OpenAI gpt-4o Function Calling + STACK API (75개 도구)
                                            ↓
                                    Reflection (gpt-4o-mini 검증 + 자동 재시도)
                                            ↓
                                    gchat_sender.py → Google Chat → 사용자
```

### 파일 구조

| 파일 | 역할 |
|------|------|
| `bot_brain.py` | OpenAI API 기반 메인 처리 엔진 (Function Calling + STACK API) |
| `gchat_listener.py` | Pub/Sub 메시지 수신 → `gchat_messages.json` 저장 |
| `gchat_sender.py` | Chat API 메시지/파일 전송 (`send_message_sync`, `send_files_sync`) |
| `chat_bot.py` | 통합 봇 로직 (check_chat, combine_tasks, report_chat 등) |
| `quick_check.py` | 빠른 메시지 확인 (bot_brain 실행 전 게이트) |
| `mybot_autoexecutor.bat` | 자동 실행 배치 (스케줄러 → quick_check → bot_brain) |
| `bot_brain_daemon.py` | 데몬 래퍼 (크래시 시 자동 재시작) |
| `start_daemon.bat` | 데몬 시작 스크립트 |
| `stop_daemon.bat` | 데몬 중지 스크립트 |
| `proactive_agent.py` | 자율 행동 엔진 (브리핑, 계약 알림, 점검 리마인더, 정합성 점검) |
| `proactive_config.py` | Proactive Agent 환경변수 설정 |
| `proactive_tracker.py` | 알림 중복 방지 + 사용자-Space 매핑 관리 |
| `_test_proactive.py` | Proactive/Reflection 테스트 도구 |
| `gchat_messages.json` | 메시지 내역 저장 (자동 생성) |

### 환경 변수 (.env)

```env
GOOGLE_APPLICATION_CREDENTIALS=./assistant-jh-b622d7ddac7e.json
GCP_PROJECT_ID=assistant-jh
PUBSUB_SUBSCRIPTION_ID=jaehyung-bot-sub
GCHAT_ALLOWED_DOMAIN=rsupport.com
BOT_NAME=비서최재형
GCHAT_POLLING_INTERVAL=10
STACK_API_URL=https://stacknew.rsup.at
STACK_API_KEY=<STACK API 키>
OPENAI_API_KEY=<OpenAI API 키>
OPENAI_MODEL=gpt-4o
OPENAI_TIMEOUT=60
STACK_API_TIMEOUT=15
MAX_TOOL_TURNS=10
TRUNCATE_MAX_LEN=8000
WORKING_LOCK_TIMEOUT=180
GCHAT_MESSAGE_LIMIT=4096
BOT_IDLE_TIMEOUT=600

# Fast Path + 경량 모델
FAST_MODEL=gpt-4o-mini
REFLECTION_MODEL=gpt-4o-mini

# Reflection (결과 검증)
REFLECTION_ENABLED=true
MAX_REFLECTION_RETRIES=2

# Agent Planning (자율 사고)
AGENT_PLANNING_ENABLED=true
COMPLEXITY_THRESHOLD_COMPLEX=7
AGENT_MODEL=gpt-4o-mini

# Proactive Agent (자율 행동)
PROACTIVE_ENABLED=true
PROACTIVE_BRIEFING_HOUR=9
PROACTIVE_BRIEFING_MINUTE=0
PROACTIVE_WEEKLY_DAY=0
PROACTIVE_WEEKLY_HOUR=9
PROACTIVE_WEEKLY_MINUTE=30
PROACTIVE_TOLERANCE_MINUTES=15
PROACTIVE_DRY_RUN=false
```

---

## Agent 기능

### 1. Reflection (결과 검증)

OpenAI Function Calling 루프 종료 후, 최종 응답을 검증하고 필요 시 자동 재시도한다.

```
[사용자 질문] → [도구 호출 루프] → [최종 응답] → [검증] → pass → [전송]
                                                    ↓ fail
                                            [대체 도구 실행] → [응답 재생성] → [전송]
```

**Quick-Pass 규칙** (70% 요청은 추가 API 호출 없이 통과):
1. 쓰기 작업 → 즉시 통과
2. 모든 도구가 데이터 반환 + 응답 200자 이상 → 통과
3. 빈 결과 없음 + 응답 100자 이상 → 통과

**도구 Fallback 맵** (`TOOL_FALLBACK_MAP`):
- `search_integrated_customer` → `list_maintenance_contracts`, `list_customers`, `search_similar_customers`
- `get_expiring_maintenance` → `list_maintenance_contracts`
- `get_current_month_checkups` → `list_maintenance_issues`

**설정**: `REFLECTION_ENABLED=true`, `MAX_REFLECTION_RETRIES=2`, `REFLECTION_MODEL=gpt-4o-mini`

### 2. Fast Path (빠른 응답)

자주 사용하는 질문 패턴을 로컬 정규식으로 매칭하여 OpenAI 1단계를 건너뛰고 직접 STACK API 호출 후 gpt-4o-mini로 응답 생성한다.

```
[사용자 질문] → [패턴 매칭] → hit → [STACK API 직접 호출] → [gpt-4o-mini 응답] → [전송]
                              ↓ miss
                       [기존 OpenAI Function Calling 흐름]
```

**지원 패턴**:
- 이번 달 점검 → `get_current_month_checkups`
- 다음 달/특정 월 점검 → `get_checkups_by_date_range`
- 미완료/지연 점검 → `get_pending_checkups`
- 만료 임박 계약 → `get_expiring_maintenance`
- X월 만료 계약 → `list_maintenance_contracts`

**개인화**: "내 점검", "나의 계약" 등 개인 키워드 감지 → assigneeId 자동 주입

**설정**: `FAST_MODEL=gpt-4o-mini`

### 3. Proactive Agent (자율 행동)

메시지가 없을 때 자율적으로 알림/브리핑을 전송한다.

| 기능 | 스케줄 | 파일 |
|------|--------|------|
| 아침 브리핑 | 매일 09:00 | `proactive_agent.py` |
| 계약 만료 알림 | 상시 (D-30, D-7, D-1) | `proactive_agent.py` |
| 미완료 점검 리마인더 | 상시 (Day+1, +3, +7) | `proactive_agent.py` |
| 주간 데이터 정합성 점검 | 매주 월요일 09:30 | `proactive_agent.py` |

**SSO 개인화**: 사용자 이메일 → STACK username 매칭 → 본인에게 해당하는 데이터만 필터링

**알림 중복 방지**: `proactive_alerts.json`에 날짜/계약/이슈별 발송 기록

**사용자-Space 매핑**: `user_spaces.json`에 이메일 → Google Chat space 매핑 (gchat_listener.py에서 자동 등록)

**중요 설계 결정**:
- `_send_message_impl()` 직접 사용 (working lock 부수효과 방지)
- `working.json` 존재 시 proactive 스킵 (사용자 요청 처리 우선)
- 데이터 1회 조회 → N명 필터링 (API 호출 최소화)
- `PROACTIVE_DRY_RUN=true`로 테스트 가능

### 4. Agent Planning (자율 사고 + 계획)

복잡한 쿼리에 대해 자동으로 실행 계획을 수립하고, 단계별로 검증하며 진행한다.

```
질문 → 복잡도 평가 →
  SIMPLE(0-3): Fast Path (기존 동일)
  MODERATE(4-6): FC 루프 (기존 동일)
  COMPLEX(7+):
    → 실행 계획 생성 (gpt-4o-mini)
    → 사용자에게 계획 공유
    → 계획 기반 FC 루프 (각 단계마다 검증 + 적응)
    → 진행 경과 보고
    → Reflection → 전송
```

**복잡도 평가 기준** (`_assess_complexity()`):
- 복합 키워드 (비교/분석/통계/요약/종합/현황/추이) → +3
- 다중 도메인 (계약+점검, 고객+서버 등) → +2 per extra
- 날짜 비교 (대비/추이/변화/전월/전년) → +2
- 다중 요청 (하고/또한/그리고) → +1 each (max 3)
- 긴 질문 (100자 이상) → +1

**단계별 검증** (`_verify_step_result()`): API 호출 없이 규칙 기반으로 판별 → 추가 비용 0
- 빈 결과 감지 → TOOL_FALLBACK_MAP에서 대체 도구 힌트 자동 주입
- 쓰기 작업 / 데이터 있음 → 즉시 통과

**설정**: `AGENT_PLANNING_ENABLED=true`, `COMPLEXITY_THRESHOLD_COMPLEX=7`, `AGENT_MODEL=gpt-4o-mini`

### 테스트

```bash
# Reflection 테스트
python _test_proactive.py --test-reflection

# Proactive DRY-RUN 테스트
python _test_proactive.py --force --briefing
python _test_proactive.py --force --contract
python _test_proactive.py --force --overdue
python _test_proactive.py --force --weekly

# 사용자-Space 매핑 동기화
python _test_proactive.py --sync-spaces

# 알림 기록 확인
python _test_proactive.py --show-alerts
```

---

## 작업 처리 원칙 (중요!)

Google Chat으로 새로운 명령을 받으면 **반드시** 다음 순서로 처리해야 한다:

### 1. 즉시 답장 (작업 시작 알림)
```python
from gchat_sender import send_message_sync
send_message_sync(task['chat_id'], "✅ 작업을 시작했습니다!")
```

### 2. 진행 중 경과 보고 (실시간 피드백)
작업이 여러 단계이거나 오래 걸리는 경우, **각 주요 단계마다** 경과를 보고한다.
```python
send_message_sync(chat_id, "📊 50% - 데이터 처리 중...")
```
- 세부적인 진행 방법과 중요 이슈를 함께 알릴 것 (하지만 길지 않게 최대한 요약)

### 3. 최종 결과 보고 (작업 완료)
```python
report_chat(
    instruction=task['instruction'],
    result_text="작업 완료!",
    chat_id=task['chat_id'],
    timestamp=task['timestamp'],
    files=["결과파일.pdf"]
)
```

### 4. 처리 완료 표시
```python
mark_done_chat(task['message_id'])
```

### 주의사항
- **즉시 답장 없이 작업만 하면 안 된다** - 사용자가 봇이 응답하는지 모를 수 있음
- **진행 경과 없이 오래 걸리면 안 된다** - 사용자가 작업이 멈춘 것으로 오해할 수 있음
- **최종 결과 없이 끝내면 안 된다** - 메모리에 기록되지 않고 파일도 전송되지 않음

---

## chat_bot.py API

```python
from chat_bot import (
    check_chat,
    combine_tasks,
    create_working_lock,
    remove_working_lock,
    reserve_memory_chat,
    report_chat,
    mark_done_chat,
    load_memory,
    get_task_dir,
    load_new_instructions,
    clear_new_instructions
)
from gchat_sender import send_message_sync

# 1. 대기 중인 지시사항 확인 (working.json 자동 확인)
pending = check_chat()

if not pending:
    exit()

# 2. 여러 메시지를 하나로 합산
combined = combine_tasks(pending)

# 3. 즉시 답장
send_message_sync(combined['chat_id'], "✅ 작업을 시작했습니다!")

# 4. 작업 잠금 생성
create_working_lock(combined['message_ids'], combined['combined_instruction'])

# 5. 메모리 예약 (tasks/msg_{id}/ 폴더 생성 + 지시사항 기록)
reserve_memory_chat(
    combined['combined_instruction'],
    combined['chat_id'],
    combined['all_timestamps'],
    combined['message_ids']
)

# 6. 기존 메모리 로드
memories = load_memory()

# 7. 작업 폴더로 이동 + 작업 수행
task_dir = get_task_dir(combined['message_ids'][0])
os.chdir(task_dir)
send_message_sync(combined['chat_id'], "📊 50% - 처리 중...")

# 8. 결과 전송 + 메모리 기록
report_chat(
    combined['combined_instruction'],
    result_text="작업 완료!",
    chat_id=combined['chat_id'],
    timestamp=combined['all_timestamps'],
    message_id=combined['message_ids'],
    files=["result.html"]
)

# 9. 처리 완료 + 잠금 해제
mark_done_chat(combined['message_ids'])
remove_working_lock()
```

---

## 작업 시작 전 메모리 조사 (필수)

지시사항을 실행하기 **앞서** 반드시 관련된 메모리를 먼저 조사해야 한다.

- `load_memory()`를 호출하여 기존 메모리 파일을 전부 읽는다.
- 지시사항의 키워드와 관련된 메모리가 있으면 해당 내용을 참고한다.
- `[보낸파일]` 섹션을 확인하여 이전에 보낸 파일이 있으면 **해당 작업 폴더 (`tasks/msg_X/`)에서 파일을 찾아** 기반으로 작업해야 한다.

### 작업 폴더 구조

```
tasks/
├── msg_abc123/
│   ├── task_info.txt       # 작업 메모리
│   ├── result.html         # 작업 결과물
│   └── preview.png
└── msg_def456/
    └── task_info.txt
```

### 메모리 검색

```python
from chat_bot import search_memory

matches = search_memory(keyword="카페")
# → [{"message_id": "abc123", "instruction": "...", "task_dir": "tasks/msg_abc123", ...}]
```

---

## 동시 작업 방지

### 1. 프로세스 레벨 (mybot_autoexecutor.bat)

```
1단계: bot_brain 프로세스 확인 → 실행 중이면 exit
2단계: Lock 파일 확인 → 프로세스 없는데 Lock 있으면 복구
3단계: quick_check.py → 메시지 없으면 즉시 종료
4단계: Lock 파일 생성 → bot_brain.py 실행
```

### 2. 메시지 레벨 (chat_bot.py)

- `working.json`으로 동일 메시지 중복 처리 방지
- 마지막 활동으로부터 30분 경과 → 스탈 작업으로 간주, 자동 재시작
- `send_message_sync()` 호출 시마다 `last_activity` 자동 갱신

### 잠금 파일 (Git 제외)
- `mybot_autoexecutor.lock` - 프로세스 잠금
- `working.json` - 메시지 잠금

---

## 핵심 기능

### 여러 메시지 합산 처리
```
사용자 (10:00): 카페 홈페이지 만들어줘
사용자 (10:01): 반응형으로 해줘
→ 봇: ✅ 작업 시작! (총 2개 요청 합산 처리)
→ 통합 지시사항: [요청 1] + [요청 2] 한번에 처리
```

### 24시간 대화 컨텍스트
- 사용자 메시지 + 봇 응답을 모두 컨텍스트에 포함
- "거기에 다크모드 추가해줘" → bot_brain이 "거기" = 이전 작업 파일임을 인식

### 작업 중 새 메시지 실시간 반영
- `send_message_sync()` 호출 시마다 자동으로 새 메시지 확인
- 새 메시지 발견 시 `new_instructions.json`에 저장 + 사용자 알림
- 작업 완료 시 새 메시지도 함께 처리 완료 표시

### 파일/이미지 첨부 지원
- Google Chat 첨부 파일 자동 다운로드 (Google Drive API)
- `tasks/msg_{id}/` 폴더에 저장
- bot_brain.py가 파일 경로를 OpenAI에 전달하여 처리

---

## 작업 흐름 (전체)

1. 사용자가 Google Chat `비서최재형`에게 메시지 보냄
2. `bot_brain_daemon.py`가 상시 실행 중 (5초마다 Pub/Sub 폴링)
3. 메시지 발견 시 즉시 처리 시작
4. 메시지 있으면 bot_brain.py 실행:
   - `check_chat()` → `combine_tasks()` → `send_message_sync()` (즉시 답장)
   - `create_working_lock()` → `reserve_memory_chat()` → `load_memory()`
   - 작업 수행 (진행 경과 보고)
   - `report_chat()` → `mark_done_chat()` → `remove_working_lock()`
5. 작업 끝나면, 바로 완료하지 말고 사용자에게 다음 작업 없는지 물어보기
6. 3분 후 Google Chat 새 메시지 확인, 있으면 작업 이어감
7. 사용자 응답 없거나 종료 요청 시 완전 종료

---

## 실행 모드

### 데몬 모드 (권장)

bot_brain_daemon.py가 상시 실행되며 5초마다 Pub/Sub 메시지를 폴링한다.
크래시 발생 시 30초 후 자동 재시작.

#### 시작/중지
```powershell
# 시작
start_daemon.bat

# 중지
stop_daemon.bat

# 재시작
stop_daemon.bat && start_daemon.bat

# 상태 확인
powershell -Command "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | Where-Object { $_.CommandLine -match 'bot_brain' } | Select ProcessId"
```

#### 로그 확인
```
D:\mybot_ver2\bot_brain.log
```

### 스케줄러 모드 (레거시)

Windows 작업 스케줄러를 통해 1분마다 실행하는 방식. 데몬 모드로 전환 권장.

```powershell
# 비활성화 (데몬 전환 시)
schtasks /Change /TN "Claude_AutoBot_mybot_ver2" /DISABLE

# 재활성화 (데몬에 문제 시 복원)
schtasks /Change /TN "Claude_AutoBot_mybot_ver2" /ENABLE
```

---

## STACK API 도구 (75개)

bot_brain.py가 OpenAI Function Calling으로 STACK 백엔드 API를 호출한다.

### 프로젝트/이슈 (8개)

| # | 도구명 | API | 설명 |
|---|--------|-----|------|
| 1 | `list_projects` | GET /api/projects | 프로젝트 목록 |
| 2 | `get_project` | GET /api/projects/{id} | 프로젝트 상세 |
| 3 | `get_project_members` | GET /api/projects/{id}/members | 프로젝트 멤버 목록 |
| 4 | `list_issues` | GET /api/projects/{id}/issues | 이슈 목록 |
| 5 | `get_issue` | GET /api/issues/{id} | 이슈 상세 |
| 6 | `create_issue` | POST /api/projects/{id}/issues | 이슈 생성 |
| 7 | `update_issue` | PUT /api/issues/{id} | 이슈 수정 |
| 8 | `change_issue_status` | PATCH /api/issues/{id}/status | 이슈 상태 변경 |
| 9 | `assign_issue` | PATCH /api/issues/{id}/assign | 이슈 담당자 배정 |

### 업무요청 (8개)

| # | 도구명 | API | 설명 |
|---|--------|-----|------|
| 10 | `list_request_jobs` | GET /api/requestJob | 목록 (검색/상태/작업유형 필터) |
| 11 | `get_request_job` | GET /api/requestJob/{id} | 상세 조회 |
| 12 | `get_request_job_stats` | GET /api/requestJob/stats | 통계 |
| 13 | `create_request_job` | POST /api/requestJob | 신규 생성 |
| 14 | `assign_request_job` | PATCH /api/requestJob/{id}/assign/{name} | 담당자 배정 |
| 15 | `update_request_job` | PUT /api/requestJob/{id} | 수정 |
| 16 | `change_request_job_status` | PATCH /api/requestJob/{id}/status | 상태 변경 |
| 17 | `delete_request_job` | DELETE /api/requestJob/{id} | 삭제 |
| 18 | `get_customer_request_jobs` | GET /api/customers/{id}/request-jobs | 고객사별 업무요청 |

### 고객사 (7개)

| # | 도구명 | API | 설명 |
|---|--------|-----|------|
| 19 | `list_customers` | GET /api/customers | 고객 목록 (검색/페이지네이션) |
| 20 | `get_customer` | GET /api/customers/{id} | 고객 상세 |
| 21 | `search_similar_customers` | GET /api/customers/check-similar | 유사 고객 검색 |
| 22 | `get_customer_projects` | GET /api/customers/{id}/projects | 고객사 프로젝트 목록 |
| 23 | `list_customer_contacts` | GET /api/customer-contacts | 고객사 담당자 연락처 목록 |
| 24 | `get_customer_contact` | GET /api/customer-contacts/{id} | 고객사 담당자 상세 |
| 25 | `get_customer_corporation` | GET /api/corporations/customer/{id} | 고객사 법인 정보 |

### 통합고객 (4개)

| # | 도구명 | API | 설명 |
|---|--------|-----|------|
| 26 | `search_integrated_customer` | GET /api/integrated-customer/search | Salesforce+NAS+유지보수 통합 검색 |
| 27 | `get_customer_card` | GET /api/integrated-customer/customer-card/{id} | 통합 고객 카드 |
| 28 | `search_maintenance_customer` | GET /api/integrated-customer/search/maintenance | 유지보수 관점 고객 검색 |
| 29 | `get_customer_timeline` | GET /api/integrated-customer/{id}/timeline | 고객사 활동 타임라인 |

### 영업/Salesforce (3개)

| # | 도구명 | API | 설명 |
|---|--------|-----|------|
| 30 | `search_expiring_contracts` | GET /api/contract-expiration/search | 만료 예정 계약 조회 |
| 31 | `get_salesforce_sync_status` | GET /api/salesforce-sync/status | SF 동기화 상태 |
| 32 | `get_salesforce_account` | GET /api/integrated-customer/salesforce/account/{id} | Salesforce 거래처 상세 |

### 유지보수 계약 (9개)

| # | 도구명 | API | 설명 |
|---|--------|-----|------|
| 33 | `list_maintenance_contracts` | GET /api/maintenance-contracts | 계약 목록 (상태/주기/제품/isExpiredButActive 필터) |
| 34 | `get_maintenance_contract` | GET /api/maintenance-contracts/{id}/detail | 계약 상세 (고객/제품/프로젝트 포함) |
| 35 | `get_expiring_maintenance` | GET /api/maintenance-contracts/expiring | D-60 만료 임박 계약 |
| 36 | `get_maintenance_plan` | GET /api/maintenance-contracts/plan | 연간 점검 계획표 |
| 37 | `renew_maintenance_contract` | POST /api/maintenance-contracts/{id}/renew | 계약 갱신 |
| 38 | `update_maintenance_contract` | PUT /api/maintenance-contracts/{id} | 계약 수정 (기간/주기/담당자) |
| 39 | `expire_maintenance_contract` | POST /api/maintenance-contracts/{id}/expire | 만료 처리 (ACTIVE→EXPIRED) |
| 40 | `get_expired_active_contracts` | GET /api/integrated-customer/contracts/expired-active | 만료됐는데 ACTIVE인 계약 |
| 41 | `get_contract_renewal_gaps` | GET /api/integrated-customer/contract-renewal-gaps | 갱신 누락 계약 |

### 정기점검 (10개)

| # | 도구명 | API | 설명 |
|---|--------|-----|------|
| 42 | `list_maintenance_issues` | GET /api/maintenance/issues | 점검 이슈 목록 (담당자/상태 필터) |
| 43 | `get_current_month_checkups` | GET /api/maintenance/issues/current-month | 이번 달 점검 |
| 44 | `get_upcoming_checkups` | GET /api/maintenance/issues/upcoming | 7일 내 예정 점검 |
| 45 | `get_pending_checkups` | GET /api/maintenance/issues/pending | 미완료 점검 (assigneeId 필수) |
| 46 | `get_checkups_by_date_range` | GET /api/maintenance/issues/date-range | 날짜 범위 점검 조회 (startDate, endDate, assigneeId) |
| 47 | `get_maintenance_status` | GET /api/maintenance/status | 월별 점검 현황 (year, month 필수) |
| 48 | `get_contract_issues` | GET /api/maintenance-contracts/{id}/issues | 계약별 점검 이슈 |
| 49 | `complete_maintenance_checkup` | POST /api/maintenance/issues/{id}/complete | 점검 완료 처리 (등급+서버) |
| 50 | `get_server_checkup_data` | GET /api/maintenance/issues/{id}/servers | 서버별 점검 데이터 |
| 51 | `save_server_checkup_data` | POST /api/maintenance/issues/{id}/servers/{sid}/save | 서버 점검 데이터 저장 |

### 서버 (5개)

| # | 도구명 | API | 설명 |
|---|--------|-----|------|
| 52 | `list_servers` | GET /api/servers | 서버 목록 (고객사/검색 필터) |
| 53 | `get_server` | GET /api/servers/{id} | 서버 상세 정보 |
| 54 | `get_customer_servers` | GET /api/customers/{id}/servers | 고객사별 서버 목록 |
| 55 | `search_servers` | GET /api/servers/search | 서버 검색 (키워드) |
| 56 | `get_server_count` | GET /api/servers/count | 서버 수량 (환경별) |

### 제품/라이선스 (6개)

| # | 도구명 | API | 설명 |
|---|--------|-----|------|
| 57 | `list_products` | GET /api/products | 제품 목록 |
| 58 | `get_product` | GET /api/products/{id} | 제품 상세 |
| 59 | `list_product_versions` | GET /api/products/{id}/versions | 제품 버전 목록 |
| 60 | `list_licenses` | GET /api/licenses | 라이선스 목록 |
| 61 | `get_license` | GET /api/licenses/{id} | 라이선스 상세 |
| 62 | `get_license_stats` | GET /api/licenses/stats | 라이선스 통계 |

### 사용자/엔지니어 (4개)

| # | 도구명 | API | 설명 |
|---|--------|-----|------|
| 63 | `list_engineers` | GET /api/users/engineers | 엔지니어 목록 |
| 64 | `list_user_names` | GET /api/users/names | 사용자 이름 목록 |
| 65 | `list_sales_managers` | GET /api/maintenance-contracts/sales-managers | 영업 담당자 목록 |
| 66 | `get_project_members` | GET /api/projects/{id}/members | 프로젝트 멤버 |

### 에픽 (2개)

| # | 도구명 | API | 설명 |
|---|--------|-----|------|
| 67 | `list_epics` | GET /api/epics | 에픽/마일스톤 목록 |
| 68 | `get_epic` | GET /api/epics/{id} | 에픽 상세 (진행률 포함) |

### 댓글 (2개)

| # | 도구명 | API | 설명 |
|---|--------|-----|------|
| 69 | `list_comments` | GET /api/comments | 댓글 목록 |
| 70 | `create_comment` | POST /api/comments | 댓글 작성 |

### 라벨 (2개)

| # | 도구명 | API | 설명 |
|---|--------|-----|------|
| 71 | `list_labels` | GET /api/labels | 라벨 목록 |
| 72 | `get_label` | GET /api/labels/{id} | 라벨 상세 |

### 메시징+알림 (2개)

| # | 도구명 | API | 설명 |
|---|--------|-----|------|
| 73 | `notify_expiring_contracts` | POST /api/contract-expiration/notify | 만료 알림 발송 |
| 74 | `send_email` | POST /api/mail/send | 이메일 발송 |

### 기타 (2개)

| # | 도구명 | API | 설명 |
|---|--------|-----|------|
| 75 | `get_corporation` | GET /api/corporations/{id} | 법인 정보 |
| 76 | `search_memory` | (로컬) | 이전 작업 기록 검색 |

---

## GCP 설정

상세 가이드: `setup_gchat.md` 참조

### 요약
1. GCP 프로젝트: `assistant-jh`
2. 활성화 API: Google Chat API, Cloud Pub/Sub API, Google Drive API
3. Pub/Sub Topic: `jaehyung-bot-topic`
4. Pub/Sub Subscription: `jaehyung-bot-sub` (Pull)
5. Service Account: `jaehyung-bot-sa@assistant-jh.iam.gserviceaccount.com`
6. Chat API 앱: `비서최재형` (Pub/Sub 연결)
