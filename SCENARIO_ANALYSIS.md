# STACK API Agent (비서최재형) 시나리오 분석
## AI 자동화 능동 수행 시나리오 & API 시퀀스

**작성일**: 2026-02-19
**분석 대상**: bot_brain.py (63개 도구), STACK API, Google Chat
**프로젝트**: 비서최재형 - Google Chat 기반 AI 업무 비서 봇

---

## 0. 현황 요약

### 보유 도구 (63개)
- **프로젝트/이슈**: list_projects, get_project, list_issues, get_issue, create_issue, update_issue, change_issue_status, assign_issue (8개)
- **업무요청**: list_request_jobs, get_request_job, get_request_job_stats, create_request_job, assign_request_job (5개)
- **고객사**: list_customers, get_customer, search_similar_customers, get_customer_projects (4개)
- **Salesforce/영업**: search_expiring_contracts, get_salesforce_sync_status, search_integrated_customer, get_salesforce_account (4개)
- **유지보수계약**: list_maintenance_contracts, get_maintenance_contract, get_expiring_maintenance, get_maintenance_plan, renew_maintenance_contract, update_maintenance_contract (6개)
- **정기점검**: list_maintenance_issues, get_current_month_checkups, get_upcoming_checkups, get_pending_checkups, get_maintenance_status, get_contract_issues, complete_maintenance_checkup, get_server_checkup_data, save_server_checkup_data (9개)
- **서버**: list_servers, get_server, get_customer_servers, search_servers, get_server_count (5개)
- **제품**: list_products, get_product, list_product_versions (3개)
- **고객담당자**: list_customer_contacts, get_customer_contact (2개)
- **법인**: get_corporation, get_customer_corporation (2개)
- **에픽**: list_epics, get_epic (2개)
- **사용자/엔지니어**: list_engineers, list_user_names (2개)
- **댓글**: list_comments, create_comment (2개)
- **라벨**: list_labels, get_label (2개)
- **라이선스**: list_licenses, get_license, get_license_stats (3개)
- **영업담당자**: list_sales_managers (1개)
- **알림/이메일**: notify_expiring_contracts, send_email (2개)
- **타임라인**: get_customer_timeline (1개)
- **메모리**: search_memory (1개)

---

## 1. 일일 자동 브리핑 시나리오

### 목표
매일 아침 9시, 영업담당자/엔지니어 팀장에게 당일 주요 업무 현황을 자동 브리핑

### 브리핑 구성
```
📊 [비서최재형 Daily Brief - 2026-02-19 09:00]

1️⃣ 오늘의 점검 (금일 예정)
   - 진행 중 점검: X건
   - 예정 점검: Y건
   - 미완료 점검: Z건

2️⃣ 만료 임박 계약
   - D-30: A개
   - D-7: B개
   - 담당자별 요약

3️⃣ 미완료 업무요청
   - 신규: X건
   - 진행중: Y건
   - 지연: Z건

4️⃣ 서버/제품 현황
   - 활성 고객사: X개
   - 서버: Y대
   - 라이선스 만료 임박: Z개

5️⃣ 데이터 이상
   - 계약 없는 점검
   - 점검 없는 계약
   - 미배정 업무요청
```

### API 호출 시퀀스 (순차 실행)

#### 1단계: 점검 현황 수집 (병렬 가능)
```
[Turn 1 - 병렬]
├─ get_current_month_checkups()
│  └─ 반환: {issues: [{id, status, assignee, dueDate, contract},...]}
├─ get_upcoming_checkups()
│  └─ 반환: {issues: [{id, status, dueDate, contract},...]}
└─ get_pending_checkups()
   └─ 반환: {pending_by_assignee: {engineer_name: [issue1, issue2]}}
```

#### 2단계: 계약 현황 수집
```
[Turn 2 - 순차]
get_expiring_maintenance()
└─ 반환: {contracts: [{id, customerId, customerName, endDate, status, checkupCycle, salesManager},...]}
   ├─ 데이터 분석: D-30/D-7 기준 분류
   └─ 각 계약별 영업담당자 추출
```

#### 3단계: 업무요청 현황
```
[Turn 3]
├─ get_request_job_stats()
│  └─ 반환: {total, byStatus: {NEW, IN_PROGRESS, DELAYED, COMPLETED}}
└─ list_request_jobs(status='NEW,IN_PROGRESS', size=50)
   └─ 반환: {jobs: [{id, title, status, priority, assignee},...]}
```

#### 4단계: 고객사/서버 규모
```
[Turn 4 - 병렬]
├─ list_customers(size=200)
│  └─ 반환: {customers: [{id, name, status},...]}
├─ list_servers(size=200)
│  └─ 반환: {servers: [{id, customerId, name, environment},...]}
└─ get_license_stats()
   └─ 반환: {total, byStatus: {ACTIVE, EXPIRING_SOON, EXPIRED}}
```

#### 5단계: 데이터 무결성 검사
```
[Turn 5 - 순차]
1. list_maintenance_contracts(size=200)
   └─ 계약 ID 목록 추출

2. 각 계약별 check:
   ├─ get_contract_issues(contract_id)
   │  └─ 점검 이슈 존재 여부 확인
   └─ 결과: "점검 없는 계약" 리스트 생성

3. list_maintenance_issues()
   └─ 점검 이슈 목록

4. 각 점검별 check:
   └─ 결과: "계약 없는 점검" 리스트 생성

5. list_request_jobs(status='NEW')
   └─ 미배정 업무 확인
```

### 결과 생성 및 전송
```python
# 최종 응답은 OpenAI가 위 데이터를 종합하여 한국어로 정리
# → send_message_sync(BRIEFING_CHAT_ID, formatted_brief)
```

### 스케줄 설정
```powershell
# Windows 작업 스케줄러
schtasks /Create /TN "DailyBriefing_9am" /TR "python bot_brain.py" /SC DAILY /ST 09:00 /F
```

### 자동화 조건
- **READ 작업**: 자동 실행 OK (조회/분석만)
- **필요 권한**: 공개 데이터만 사용
- **알림 채널**: Google Chat (gchat_sender.send_message_sync)

---

## 2. 만료 계약 자동 알림 시나리오

### 목표
만료 D-30, D-7, D-0 시점에 영업담당자/고객담당자에게 자동 알림

### 알림 대상 결정 로직
```
만료 D-30 이상 → 영업담당자 (prepare)
만료 D-7      → 영업담당자 + 엔지니어팀장 (final check)
만료 D-0      → 영업담당자 + CEO (critical alert)
```

### API 호출 시퀀스

#### 1단계: 만료 임박 계약 조회
```
[Turn 1]
get_expiring_maintenance()
└─ 반환: {contracts: [{
    id, contractId,
    customerName, customerId,
    contractEndDate,
    checkupCycle, status,
    salesManagerName, salesManagerId,
    projects: [{productCode, engineerName}]
  },...]}
```

#### 2단계: 계약 상세 정보 수집 (병렬)
```
[Turn 2 - 병렬]
각 계약 ID마다:
├─ get_maintenance_contract(id)
│  └─ 반환: {contract, customer, products, projects}
└─ get_contract_issues(contract_id)
   └─ 반환: {issues: [{id, status, dueDate},...]}
```

#### 3단계: 고객담당자 조회 (병렬)
```
[Turn 3 - 병렬]
각 고객사 ID마다:
└─ list_customer_contacts(customerId)
   └─ 반환: {contacts: [{id, name, role, email, phone},...]}
```

#### 4단계: 알림 생성 및 발송
```
[Turn 4 - 순차]
각 만료 계약마다:

if daysUntilExpiry >= 30:  # D-30
  ├─ 수신자: salesManager (영업담당자)
  ├─ 제목: "[알림] 고객사 계약 갱신 예정: {customername} (D-{daysUntil})"
  ├─ 본문:
  │  └─ 계약명, 현재 상태, 점검 현황 요약
  └─ 채널: send_email(to=salesManager.email) or Google Chat

elif daysUntilExpiry == 7:  # D-7
  ├─ 수신자: [salesManager, engineerLead, gchatBroadcast]
  ├─ 심각도: 높음 (🔴 마크)
  └─ 내용: 갱신 여부 최종 확인 요청

elif daysUntilExpiry == 0:  # D-0 (만료일)
  ├─ 수신자: [salesManager, engineerLead, CEO]
  ├─ 심각도: 긴급 (🚨 마크)
  └─ 내용: 긴급 갱신 처리 또는 계약 종료 알림
```

#### 5단계: 알림 발송 구현
```
[Turn 5]
notify_expiring_contracts()
└─ 반환: {notified_count, failed_count, details: [{contractId, to, status}]}

또는 수동:
send_email(
  to="{salesManager.email},{engineer.email}",
  subject="[긴급] 계약 갱신: {customerName}",
  body="..."
)

또는 Google Chat:
send_message_sync(
  chat_id=MANAGER_CHAT_ID,
  message=f"🔔 D-{days}: {customerName} 계약 갱신 예정"
)
```

### 자동화 스케줄
```powershell
# 매일 09:00, 12:00, 16:00 실행
schtasks /Create /TN "ExpiringContractAlert" /TR "python bot_brain.py" /SC DAILY /ST 09:00,12:00,16:00 /F
```

### 자동화 조건
- **READ 작업**: get_expiring_maintenance, get_maintenance_contract (자동)
- **WRITE 작업**: send_email, notify_expiring_contracts
  - **기준**: D-30 이전은 자동, D-7 이후는 조회만 제공하고 사용자 확인 권장

---

## 3. 미완료 점검 리마인드 시나리오

### 목표
점검 기한 초과 시 담당 엔지니어에게 자동 상기 알림

### 알림 조건
```
1. 점검 상태: PENDING, IN_PROGRESS
2. 현재일 > 예정일 (overdue)
3. 연속 3일 미완료 시 → 상위 관리자에게도 알림
```

### API 호출 시퀀스

#### 1단계: 미완료 점검 조회
```
[Turn 1 - 병렬]
├─ get_pending_checkups()
│  └─ 반환: {pending_by_assignee: {
│     engineer_name: [{id, dueDate, customerId, contractId}]
│  }}
├─ get_current_month_checkups()
│  └─ 반환: {issues: [{id, status, dueDate, assignee}]}
└─ list_maintenance_issues(status='PENDING,IN_PROGRESS')
   └─ 반환: {issues: [...]}
```

#### 2단계: 각 미완료 점검별 기한 검사 (병렬)
```
[Turn 2]
for each issue in pending_issues:
  days_overdue = (today - dueDate).days
  if days_overdue > 0:
    → overdue_issues.append({issue, days_overdue})
```

#### 3단계: 담당자 정보 수집 (병렬)
```
[Turn 3 - 병렬]
각 담당 엔지니어마다:
└─ list_engineers() 또는 list_user_names()
   └─ 반환: {users: [{id, name, email, department}]}
```

#### 4단계: 알림 생성 및 발송
```
[Turn 4 - 순차]

for overdue_issue in overdue_issues:
  engineer = overdue_issue.assignee
  days = overdue_issue.days_overdue

  if days == 1:  # 기한 초과 1일차
    수신: engineer (담당자)
    제목: "[리마인드] 점검 기한 초과: {customerName} (기한 초과 1일)"
    내용:
      └─ 점검 ID, 고객명, 예정일, 서버 목록 요약

  elif days == 3:  # 3일 경과
    수신: [engineer, teamLead, manager]
    제목: "[경고] 점검 3일 미완료: {customerName}"
    내용:
      └─ 위와 동일 + 상위 관리자 참조

  elif days >= 7:  # 1주 경과
    수신: [engineer, teamLead, CEO]
    제목: "[긴급] 점검 {days}일 미완료: {customerName}"
    심각도: 🚨 (빨강)
```

#### 5단계: 알림 발송 구현
```
[Turn 5]
send_email(
  to=engineer.email,
  subject="[리마인드] 점검 기한 초과",
  body=formatted_message
)

또는 Google Chat:
send_message_sync(
  chat_id=ENGINEER_PERSONAL_CHAT,
  message=f"🟡 기한 초과: {customerName} 점검"
)
```

### 스케줄
```powershell
# 매일 08:30, 14:00, 17:00 실행
schtasks /Create /TN "PendingCheckupReminder" /TR "python bot_brain.py" /SC DAILY /ST 08:30,14:00,17:00 /F
```

### 자동화 조건
- **READ**: 점검 조회, 담당자 정보 → 자동
- **WRITE**: 이메일/채팅 알림 → 자동 (단, 7일 이상 미완료는 선택적)

---

## 4. 이상 감지 시나리오 (데이터 무결성 검사)

### 목표
시스템 데이터 불일치 자동 탐지 및 보고

### 탐지 대상
1. **계약-점검 불일치**
   - 계약은 있는데 점검이 없음
   - 점검은 있는데 계약이 없음
   - 점검 주기와 실제 점검 간격 미매칭

2. **담당자 할당 오류**
   - 미배정 업무요청
   - 미배정 점검
   - 엔지니어 이동/퇴사에 따른 미배정 이슈

3. **시간 초과**
   - 계약 종료일이 지났는데 활성 상태
   - 점검 예정일이 지났는데 미완료

4. **중복/누락**
   - 동일 고객사의 중복 계약
   - 서버 미할당 계약

### API 호출 시퀀스

#### 1단계: 전체 데이터 수집 (병렬)
```
[Turn 1 - 병렬]
├─ list_maintenance_contracts(size=500)
│  └─ contracts_list = [...]
├─ list_maintenance_issues(size=500)
│  └─ issues_list = [...]
├─ list_request_jobs(status='NEW,IN_PROGRESS,DELAYED', size=500)
│  └─ jobs_list = [...]
└─ list_servers(size=500)
   └─ servers_list = [...]
```

#### 2단계: 계약 점검 불일치 감지 (순차)
```
[Turn 2]
# 경우 1: 계약이 있는데 점검 없음
for contract in contracts_list:
  if contract.status == 'ACTIVE':
    issues = get_contract_issues(contract.id)
    if not issues or len(issues) == 0:
      anomalies.append({
        type: 'NO_CHECKUP_FOR_CONTRACT',
        contractId: contract.id,
        customerName: contract.customerName,
        checkupCycle: contract.checkupCycle,
        lastCheckup: null
      })

# 경우 2: 점검이 있는데 계약 없음
for issue in issues_list:
  contract = find_in(contracts_list, contractId=issue.contractId)
  if not contract:
    anomalies.append({
      type: 'ORPHAN_CHECKUP',
      issueId: issue.id,
      contractId: issue.contractId
    })

# 경우 3: 점검 주기 미스매칭
for contract in contracts_list:
  issues = get_contract_issues(contract.id)
  if issues:
    expected_interval = cycleToDays(contract.checkupCycle)
    actual_gaps = calculate_gaps(issues.dates)
    if max(actual_gaps) > expected_interval * 1.5:  # 예정보다 50% 이상 늦음
      anomalies.append({
        type: 'CHECKUP_INTERVAL_MISMATCH',
        contractId: contract.id,
        expectedDays: expected_interval,
        actualMaxGap: max(actual_gaps)
      })
```

#### 3단계: 담당자 할당 오류 감지 (순차)
```
[Turn 3]
# 경우 1: 미배정 업무요청
unassigned_jobs = [j for j in jobs_list if not j.assignee]
if unassigned_jobs:
  anomalies.append({
    type: 'UNASSIGNED_REQUEST_JOBS',
    count: len(unassigned_jobs),
    jobIds: [j.id for j in unassigned_jobs[:10]]
  })

# 경우 2: 미배정 점검
unassigned_issues = [i for i in issues_list if not i.assignee and i.status != 'COMPLETED']
if unassigned_issues:
  anomalies.append({
    type: 'UNASSIGNED_CHECKUPS',
    count: len(unassigned_issues),
    issueIds: [i.id for i in unassigned_issues[:10]]
  })

# 경우 3: 엔지니어 검증
engineers = list_engineers()
engineer_names = {e.name for e in engineers}
for issue in issues_list:
  if issue.assignee and issue.assignee not in engineer_names:
    anomalies.append({
      type: 'INVALID_ASSIGNEE',
      issueId: issue.id,
      assigneeName: issue.assignee,
      note: 'Engineer not found in system'
    })
```

#### 4단계: 시간 초과 감지 (순차)
```
[Turn 4]
today = datetime.now().date()

# 경우 1: 종료된 활성 계약
for contract in contracts_list:
  if contract.status == 'ACTIVE' and contract.contractEndDate < today:
    anomalies.append({
      type: 'EXPIRED_ACTIVE_CONTRACT',
      contractId: contract.id,
      customerName: contract.customerName,
      endDate: contract.contractEndDate,
      daysExpired: (today - contract.contractEndDate).days
    })

# 경우 2: 과거 예정일 미완료 점검
for issue in issues_list:
  if issue.status != 'COMPLETED' and issue.dueDate < today:
    anomalies.append({
      type: 'OVERDUE_CHECKUP',
      issueId: issue.id,
      dueDate: issue.dueDate,
      daysOverdue: (today - issue.dueDate).days
    })
```

#### 5단계: 중복/누락 감지 (순차)
```
[Turn 5]
# 경우 1: 중복 계약
customer_contracts = {}
for contract in contracts_list:
  key = contract.customerId
  if key not in customer_contracts:
    customer_contracts[key] = []
  customer_contracts[key].append(contract)

for customerId, contracts in customer_contracts.items():
  active_contracts = [c for c in contracts if c.status == 'ACTIVE']
  if len(active_contracts) > 1:
    anomalies.append({
      type: 'DUPLICATE_ACTIVE_CONTRACTS',
      customerId: customerId,
      customerName: contracts[0].customerName,
      contractIds: [c.id for c in active_contracts],
      count: len(active_contracts)
    })

# 경우 2: 서버 미할당 계약
for contract in contracts_list:
  if contract.status == 'ACTIVE':
    servers = list_servers() # or get_customer_servers(customerId)
    relevant_servers = [s for s in servers if s.customerId == contract.customerId]
    if not relevant_servers:
      anomalies.append({
        type: 'NO_SERVERS_FOR_ACTIVE_CONTRACT',
        contractId: contract.id,
        customerId: contract.customerId,
        customerName: contract.customerName
      })
```

#### 6단계: 결과 보고 (순차)
```
[Turn 6]
# 이상 현황 그룹화
anomaly_summary = {
  'NO_CHECKUP_FOR_CONTRACT': [...],
  'ORPHAN_CHECKUP': [...],
  'UNASSIGNED_REQUEST_JOBS': [...],
  'EXPIRED_ACTIVE_CONTRACT': [...],
  'OVERDUE_CHECKUP': [...],
  'DUPLICATE_ACTIVE_CONTRACTS': [...]
}

# 심각도별 분류
CRITICAL = [
  'EXPIRED_ACTIVE_CONTRACT',
  'DUPLICATE_ACTIVE_CONTRACTS',
  'ORPHAN_CHECKUP'
]

# 리포트 생성
report = f"""
📋 [데이터 무결성 검사 결과] {today}

🔴 심각 (Critical):
{critical_anomalies_formatted}

🟡 경고 (Warning):
{warning_anomalies_formatted}

🔵 정보 (Info):
{info_anomalies_formatted}

총 {len(anomalies)} 개 이상 탐지
"""

send_message_sync(ADMIN_CHAT_ID, report)
```

### 스케줄
```powershell
# 주 1회 (월요일 09:00)
schtasks /Create /TN "DataIntegrityCheck" /TR "python bot_brain.py" /SC WEEKLY /D MON /ST 09:00 /F
```

### 자동화 조건
- **READ**: 모든 조회 작업 → 자동
- **WRITE**: 보고만 (수정/삭제 없음) → 자동
- **수정 필요**: 자동화 아님 (담당자 수동 확인 후 처리)

---

## 5. 복합 작업 시나리오 (Planning 필요)

### 시나리오 5-1: 분기별 점검 계획 수립

#### 사용자 요청
```
"2026년 Q2(4월-6월) 점검 계획 세워줘.
고객사별, 엔지니어별로 정리하고
점검 날짜를 제안해줘."
```

#### Planning 단계
```
1. 입력 파싱
   ├─ 기간: Q2 2026 (2026-04-01 ~ 2026-06-30)
   └─ 출력: 고객사별, 엔지니어별 테이블

2. 필요 데이터 조사
   ├─ 현재 활성 계약 목록
   ├─ 각 계약의 점검 주기
   ├─ 각 엔지니어의 용량(현재 할당 점검 수)
   └─ 서버 위치/환경별 배포

3. 계획 수립 알고리즘
   ├─ 월별 점검 개수 계산 (주기별)
   ├─ 엔지니어 할당 (순환 배치)
   ├─ 휴가/사건 고려
   └─ 날짜 제안

4. 결과 생성
   ├─ Excel/CSV 출력
   └─ Markdown 보고
```

#### API 호출 시퀀스

**[Turn 1] 계약 및 점검 주기 조회**
```
list_maintenance_contracts(status='ACTIVE', size=200)
└─ {contracts: [{id, customerId, customerName, checkupCycle, salesManagerName}]}

for contract in contracts:
  get_contract_issues(contract.id)
  └─ {issues: [{id, dueDate, completedDate}]}
```

**[Turn 2] 현재 점검 현황 (기준: 2026-04-01)**
```
get_maintenance_status(year=2026, month=4)  # April
get_maintenance_status(year=2026, month=5)  # May
get_maintenance_status(year=2026, month=6)  # June
└─ {completed, pending, scheduled by month}
```

**[Turn 3] 엔지니어 리스트 및 역량**
```
list_engineers()
└─ {engineers: [{id, name, department, skillSet}]}

list_maintenance_issues(status='IN_PROGRESS')
└─ {issues: [...]} # 현재 할당량 계산
```

**[Turn 4] 고객사/서버 분포**
```
list_customers(size=200)
└─ {customers: [{id, name, location}]}

get_customer_servers(customerId)
└─ {servers: [{id, name, environment, location}]}
```

**[Turn 5] 최종 계획 생성 (OpenAI)**
```
OpenAI가 위 데이터를 분석하여:
1. 월별 점검 스케줄 테이블
   ├─ 4월: 15건 (월간 10 + 분기 5)
   ├─ 5월: 12건
   └─ 6월: 18건

2. 엔지니어별 할당표
   ├─ 엔지니어A: 15건
   ├─ 엔지니어B: 15건
   └─ 엔지니어C: 15건

3. 점검 날짜 제안
   └─ 고객사별 추천 날짜

4. 위험 요소
   ├─ 엔지니어 부족
   ├─ 특정 월 과부하
   └─ 미할당 고객사
```

#### 결과 저장 및 전송
```
1. Markdown 포맷 보고
   └─ gchat_sender.send_message_sync()

2. CSV/Excel 생성
   └─ task_dir/quarterly_plan_q2_2026.csv
   └─ report_chat(files=[...])

3. 승인 대기
   └─ 사용자 확인 후 점검 자동 생성
```

---

### 시나리오 5-2: 당월 점검 현황 분석 리포트

#### 사용자 요청
```
"이번 달(2월) 점검 현황을 분석해줘.
완료율, 기한 미스, 엔지니어별 성과를 정리해줘."
```

#### Planning 단계
```
1. 데이터 수집
   ├─ 당월 전체 예정 점검
   ├─ 완료된 점검
   ├─ 미완료 점검
   └─ 기한 초과 점검

2. 분석 항목
   ├─ 완료율 (완료/전체)
   ├─ 기한 내 완료율
   ├─ 엔지니어별 성과
   ├─ 고객사별 현황
   ├─ 서버/제품별 통계
   └─ 문제점 및 개선안

3. 시각화
   ├─ 막대 그래프 (월별 비교)
   ├─ 파이 차트 (상태별)
   ├─ 테이블 (상세)
   └─ 히트맵 (엔지니어별)
```

#### API 호출 시퀀스

**[Turn 1] 당월 점검 조회**
```
get_current_month_checkups()
└─ {issues: [{id, customerId, customerName, dueDate, status, assignee}]}

get_maintenance_status(year=2026, month=2)
└─ {completed: X, pending: Y, overdue: Z}
```

**[Turn 2] 완료된 점검 상세**
```
list_maintenance_issues(status='COMPLETED')
└─ {issues: [...]}

각 점검별:
get_server_checkup_data(issue_id)
└─ {servers: [{serverId, checkResult, grade}]}
```

**[Turn 3] 엔지니어별 성과**
```
list_engineers()
└─ {engineers: [{id, name}]}

list_maintenance_issues(assignee=engineer_name)
└─ 각 엔지니어의 점검 수 집계
```

**[Turn 4] 고객사별 현황**
```
list_customers(size=200)
└─ {customers: [{id, name}]}

각 고객사별:
list_maintenance_issues() # 필터링
└─ 당월 점검 현황
```

**[Turn 5] 최종 분석 (OpenAI)**
```
위 데이터를 종합하여:

📊 [2월 점검 현황 분석]

✅ 완료율: 85% (34/40건)
  ├─ 기한 내: 32건 (94%)
  └─ 기한 초과 완료: 2건

🔴 미완료: 6건 (15%)
  ├─ 기한 내: 2건
  └─ 기한 초과: 4건

👥 엔지니어별 성과:
  ├─ 엔지니어A: 15건 (100% 완료)
  ├─ 엔지니어B: 12건 (92% 완료)
  └─ 엔지니어C: 13건 (77% 완료)

🏢 고객사별 현황:
  ├─ 고객A: 8건 (100%)
  ├─ 고객B: 5건 (80%)
  └─ ...

⚠️ 주요 이슈:
  1. 기한 초과 4건 (고객B, C)
  2. 엔지니어C 점검 진행률 낮음
  3. 특정 제품(ProductX) 점검 집중

💡 개선안:
  1. 엔지니어C에 교육/지원
  2. 고객B, C 점검 우선순위 상향
  3. ProductX 점검 전담팀 구성
```

#### 결과 저장 및 전송
```
1. HTML 리포트 생성
   ├─ 차트 포함
   ├─ 인터랙티브 테이블
   └─ 다운로드 링크

2. Google Chat 요약
   └─ 핵심만 메시지로 전송

3. PDF 자동 생성
   └─ report_chat(files=['report.pdf'])
```

---

### 시나리오 5-3: 대량 점검 결과 입력 자동화

#### 사용자 요청
```
"엑셀 파일로 점검 결과를 줄게. 자동으로 입력해줘."
(첨부파일: checkup_results_feb2026.xlsx)
```

#### Planning 단계
```
1. 파일 파싱
   ├─ Excel 읽기
   ├─ 스키마 검증
   ├─ 오류 데이터 식별
   └─ 유효 데이터만 선별

2. 데이터 매핑
   ├─ 이슈 ID 확인
   ├─ 서버 ID 매핑
   ├─ 점검 결과 -> enum 변환
   └─ 담당자 확인

3. 대량 입력
   ├─ 배치 처리 (10건씩)
   ├─ 오류 처리 및 재시도
   ├─ 진행 상황 실시간 보고
   └─ 완료 요약
```

#### API 호출 시퀀스

**[Turn 1] 파일 처리 및 검증**
```
# gchat_sender에서 첨부파일 다운로드
downloaded_file = download_attachment()
└─ D:\mybot_ver2\tasks\msg_{id}\checkup_results_feb2026.xlsx

# Python으로 파일 파싱
import pandas as pd
df = pd.read_excel(downloaded_file)
# 컬럼: [IssueID, ServerID, CheckResult, Grade, Comment, Date]

# 검증
valid_rows = []
error_rows = []
for idx, row in df.iterrows():
  if validate(row):
    valid_rows.append(row)
  else:
    error_rows.append({index: idx, error: why})

# 오류 보고
send_message_sync(chat_id, f"✅ {len(valid_rows)}건 유효, ⚠️ {len(error_rows)}건 오류")
```

**[Turn 2] 점검 결과 조회 (검증 용)**
```
for issue_id in unique(valid_rows.IssueID):
  get_maintenance_issues(issue_id)  # 없으면 오류 추가
```

**[Turn 3] 대량 입력 - 배치 1**
```
for idx in range(0, len(valid_rows), 10):
  batch = valid_rows[idx:idx+10]

  for row in batch:
    complete_maintenance_checkup(
      issue_id=row.IssueID,
      grade=row.Grade,
      comment=row.Comment
    )

    save_server_checkup_data(
      issue_id=row.IssueID,
      server_id=row.ServerID,
      data={
        result: row.CheckResult,
        timestamp: row.Date
      }
    )

  # 진행 보고
  send_message_sync(chat_id, f"📊 {idx+10}/{len(valid_rows)} 처리 중...")
```

**[Turn 4] 완료 요약**
```
summary = {
  total: len(valid_rows),
  completed: completed_count,
  failed: failed_count,
  errors: [...]
}

send_message_sync(chat_id, f"""
✅ 완료!
- 입력됨: {completed_count}건
- 실패: {failed_count}건
- 에러: {len(error_rows)}건

상세: {task_dir}/import_summary.txt
""")
```

---

## 6. 자동화 vs 수동 확인 기준

### 자동 실행 가능 (READ 작업)

| 작업 | 도구 | 자동화 | 근거 |
|------|------|--------|------|
| 일일 브리핑 생성 | get_current_month_checkups + 기타 | ✅ | 조회만, 데이터 손실 없음 |
| 만료 임박 알림 | get_expiring_maintenance | ✅ | 조회만, 정보 공유 |
| 점검 기한 리마인드 | get_pending_checkups | ✅ | 조회만, 알림 기능 |
| 데이터 무결성 검사 | list_maintenance_contracts + 기타 | ✅ | 읽기 기반 분석 |
| 기존 작업 조회 | search_memory | ✅ | 내부 메모리 조회 |

### 자동화 권장 (WRITE 작업 중 검증 불필요)

| 작업 | 도구 | 자동화 | 근거 |
|------|------|--------|------|
| 점검 완료 입력 | complete_maintenance_checkup + save_server_checkup_data | ⚠️ | 파일 업로드 시에만 |
| 담당자 배정 | assign_issue, assign_request_job | ⚠️ | 자동 배치 알고리즘 필요 |
| 이메일 발송 | send_email | ⚠️ | D-30 이전은 자동, D-7 이후는 확인 |
| 만료 알림 | notify_expiring_contracts | ⚠️ | D-30 이전은 자동, D-7 이후는 확인 |

### 수동 확인 필요 (WRITE 작업)

| 작업 | 도구 | 자동화 | 근거 |
|------|------|--------|------|
| 계약 신규 생성 | create_project, create_issue | ❌ | 고객 맞춤형, 담당자 선정 필요 |
| 계약 갱신 | renew_maintenance_contract | ❌ | 재계약 조건, 금액 협상 필요 |
| 계약 수정 | update_maintenance_contract | ❌ | 비즈니스 로직 변경 |
| 점검 상태 변경 | change_issue_status | ❌ | 엔지니어 확인 후 |
| 점검 삭제 | delete_issue | ❌ | 감사 추적 필요 |
| 업무요청 생성 | create_request_job | ❌ | 업무 우선순위, 배정 필요 |

### 조건부 자동화

```python
# 예: 만료 D-30 ~ D-7 구간
if days_until_expiry >= 30:
    notify_expiring_contracts()  # ✅ 자동
    send_email()  # ✅ 자동
elif days_until_expiry < 7:
    notify_expiring_contracts()  # ⚠️ 조회만, 사용자 최종 확인
    send_message_sync(APPROVAL_REQUIRED=True)  # 사용자 승인 대기

# 예: 기한 초과 점검
if days_overdue == 1:
    send_email(engineer)  # ✅ 자동 리마인드
elif days_overdue >= 7:
    escalate_to_manager()  # ⚠️ 관리자 개입 필요
    send_message_sync(URGENT=True)
```

---

## 7. 구현 우선순위 (Roadmap)

### Phase 1: 기본 브리핑 (1주)
```
✅ 일일 아침 브리핑 (당일 점검 + 만료 임박 계약)
✅ 스케줄 설정 (Windows 작업 스케줄러)
✅ Google Chat 자동 전송
```

### Phase 2: 알림 자동화 (2주)
```
✅ 만료 D-30/D-7/D-0 자동 알림
✅ 미완료 점검 리마인드
✅ 이메일 + Google Chat 이중 채널
```

### Phase 3: 데이터 검증 (1주)
```
✅ 주간 데이터 무결성 검사
✅ 이상 탐지 및 보고
✅ 자동 수정 안내
```

### Phase 4: 복합 작업 (2주)
```
✅ 분기별 계획 수립 지원
✅ 월별 분석 리포트
✅ 대량 점검 결과 입력
```

### Phase 5: 고급 기능 (진행 중)
```
🔄 엔지니어 최적 배치 알고리즘
🔄 고객사별 예측 분석
🔄 계약 갱신 확률 모델
```

---

## 8. 주요 제약사항 및 주의점

### API 레이트 제한
```
- STACK API: 일반적으로 분당 1000 요청
- 대량 조회 시 size=500으로 최적화
- 병렬 처리 주의 (순차 실행 권장)
```

### 데이터 동기화 문제
```
- Salesforce 동기화 지연 (최대 1시간)
- 고객 담당자 정보 수동 업데이트 필요
- 서버 정보 변동 추적 어려움
```

### 에러 처리
```
- 404 (Not Found): 데이터 삭제됨, 메모리 업데이트 필요
- 403 (Forbidden): 권한 부족, 서비스 계정 확인
- 500 (Server Error): 재시도 필요, 로깅 필수
```

### 보안 주의사항
```
- 민감정보 (고객 이메일, 계약금액) 로그 제외
- Google Chat 공개 채널 금지 (비즈니스 민감정보)
- 이메일 발송 시 BCC 사용 (장님 발송 방지)
```

### 성능 최적화
```
1. 캐싱: 자주 조회되는 데이터 (엔지니어 목록 등)
2. 배치 처리: 대량 입력은 10건씩 분할
3. 병렬화: 독립적인 조회는 동시 실행
4. 진행 보고: 장시간 작업은 5분마다 업데이트
```

---

## 9. 예상 효과

### 시간 절감
- 일일 브리핑: 1시간/일 → 5분/일 (자동)
- 만료 알림: 30분/주 → 자동
- 점검 분석: 2시간/달 → 자동
- **월간 절감: 약 40시간**

### 오류 감소
- 수동 입력 오류: 3-5% → 0.1%
- 놓친 기한: 월 2-3건 → 0
- 데이터 불일치: 월 5건 → 자동 탐지

### 의사결정 개선
- 실시간 현황 파악 가능
- 데이터 기반 인사이트 제공
- 리스크 조기 탐지

---

## 10. FAQ & Troubleshooting

### Q1: 자동 알림이 너무 많아지지 않을까?
```
A: 알림 정책 수립 필요
   - 브리핑: 일 1회 (아침 9시)
   - 만료 알림: 월 N회 (D-30, D-7, D-0만)
   - 리마인드: 주 3회 (과도 시에만)
   - 필요시 구독 설정 추가
```

### Q2: 계약 갱신을 자동으로 해도 될까?
```
A: 아니오. 수동 확인 필수
   - 이유: 금액 협상, 계약 조건 변경
   - 자동화: 알림만 (갱신은 사용자 수동)
   - OpenAI가 갱신 권고안을 제시할 수는 있음
```

### Q3: 엔지니어 최적 배치를 자동으로 할 수 있을까?
```
A: 부분 자동화 가능
   - 현황: 수동 배치 (팀장 판단)
   - 개선안: AI 추천 안 생성 (확인 후 적용)
   - 미래: 머신러닝 기반 최적화
```

### Q4: 점검 결과를 음성/사진으로 입력할 수 있을까?
```
A: 미래 기능 (현재는 Excel 파일)
   - 준비: Google Vision API 연동
   - 이미지 → 텍스트 변환
   - 음성 → 텍스트 변환
```

---

## 결론

**비서최재형**은 현재 63개 도구로 다음을 **완전 자동화**할 수 있습니다:

1. ✅ **일일 브리핑** - 당일 점검 + 만료 임박 계약 조회
2. ✅ **알림 자동화** - 만료/기한초과 자동 알림
3. ✅ **데이터 검증** - 주간 무결성 검사
4. ✅ **분석 리포트** - 월별/분기별 통계 생성

그리고 다음은 **조회만 자동화하고 실행은 수동**입니다:

5. ⚠️ **대량 입력** - 파일 파싱 후 승인 대기
6. ⚠️ **계약 갱신** - 권고안 제시 후 수동 승인
7. ⚠️ **배치 배정** - 추천 안 제시 후 팀장 최종 선택

향후 단계별 확장으로 **완전 자동 의사결정 시스템**으로 진화할 가능성이 있습니다.
