# AGENTS.md

## 보안 정책

- 텔레그램 봇 토큰과 허용 사용자 ID는 `.env` 파일로만 관리한다.
- `.env` 파일은 이 프로젝트 루트에 유일하게 관리되며, 코드 본문에 직접 적지 않는다.
- `.env`는 Git에 커밋하지 않는다 (`.gitignore`에 추가).
- Credentials는 dotenv 라이브러리를 통해 런타임에 로드한다.

---

## 텔레그램 봇 시스템 (Telegram Bot)

**상태**: ✅ 구현 완료 (2026-02-01)

텔레그램을 통해 실시간으로 지시사항을 받고 결과를 회신하는 자율 작업 봇입니다.

### 시스템 개요
- **목적**: 텔레그램을 통해 실시간으로 지시사항 주고받기
- **상세 설계**: `TELEGRAM_BOT.md` 참조
- **구현 범위**:
  1. `telegram_listener.py` - 10초 간격으로 텔레그램 메시지 수집
  2. `telegram_sender.py` - Claude Code 작업 결과를 텔레그램으로 전송
  3. `telegram_bot.py` - 통합 봇 로직 (check_telegram, report_telegram, mark_done_telegram)
  4. `telegram_messages.json` - 메시지 내역 저장 및 처리 상태 관리

### 핵심 특징
- **🆕 완전한 대화 컨텍스트**: 새로운 명령 + 최근 24시간 대화 내역 (사용자 메시지 + 봇 응답 모두 포함)
  - **[명령]**: 실행해야 할 새로운 지시사항
  - **[참고사항]**: 최근 24시간 대화 내역 - 사용자 메시지와 봇 응답을 모두 포함하여 대화 흐름 이해
  - 예: "거기에 다크모드 추가해줘" → Claude Code가 "거기"가 이전에 만든 cafe.html임을 알 수 있음
- **폴링 주기**: 10초마다 실시간 확인 - 빠른 응답
- **키워드 필터**: 키워드 필수 없음, 모든 메시지 처리
- **사용자 검증**: `.env`의 `TELEGRAM_ALLOWED_USERS`에 등록된 사용자만 허용
- **🆕 이미지/파일/위치 지원**: 텔레그램 메시지에 첨부된 이미지, 문서, 비디오, 오디오, 위치 정보 자동 처리
  - 지원 타입: 사진(photo), 문서(document), 비디오(video), 오디오(audio), 음성(voice), **위치(location)**
  - 파일은 `tasks/msg_{message_id}/` 폴더에 자동 저장
  - 위치는 위도/경도 + Google Maps 링크로 전달
  - Claude Code는 Read 도구로 이미지/파일 읽기, 위치는 좌표 값으로 활용

### 초기 토큰 설정

첫 실행 시 `.env`에 `TELEGRAM_BOT_TOKEN`이 없으면, `telegram_listener.py`가 자동으로 사용자에게 토큰을 입력받아 `.env`에 저장합니다.

```bash
python telegram_listener.py  # 토큰 미설정 시 자동 입력 프롬프트 표시
```

### 현재 봇 정보

**텔레그램 봇**:
- 봇 이름: 소놀봇
- 봇 유저네임: @mysonol_bot
- 봇 토큰: `.env`에서 관리 (초기 설정 시 자동 요청)

**허용된 사용자**:
- 사용자 ID: `.env`에서 관리

**환경 변수 (.env) 구조**:
```env
TELEGRAM_BOT_TOKEN=<@BotFather에서 발급한 봇 토큰>
TELEGRAM_ALLOWED_USERS=<허용할 텔레그램 사용자 ID>
TELEGRAM_POLLING_INTERVAL=10
```

### 구현 완료 항목
1. ✅ 텔레그램 봇 토큰 발급 (@BotFather)
2. ✅ `.env`에 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS` 추가
3. ✅ `telegram_listener.py` - 메시지 수집기 (10초 폴링)
4. ✅ `telegram_sender.py` - 응답 전송기
5. ✅ `telegram_bot.py` - 통합 봇 로직
6. ✅ 테스트 완료 및 정상 작동 확인
7. ✅ **이미지/파일 지원** (2026-02-07) - 사진, 문서, 비디오, 오디오 자동 다운로드 및 Claude Code 전달
   - `telegram_listener.py`: 파일 다운로드 기능 (`download_file()`)
   - `telegram_bot.py`: 파일 정보 합산 및 전달 (`combine_tasks()`)
   - 파일 크기 포맷팅, 타입별 이모지, 경로 전달
   - 상세 가이드: `FILE_SUPPORT.md`
8. ✅ **봇 응답 포함 컨텍스트** (2026-02-07) - 완전한 대화 흐름 이해
   - `telegram_bot.py`: 봇 응답 저장 (`save_bot_response()`)
   - `get_24h_context()`: 사용자 메시지 + 봇 응답 모두 포함
   - telegram_messages.json에 type 필드 추가 (user/bot)
   - 대화 흐름 이해 가능: "거기에" → 이전 작업 파일 참조 인식
   - 테스트: `test_bot_response_context.py`
9. ✅ **위치 정보 지원** (2026-02-07) - GPS 좌표 기반 서비스
   - `telegram_listener.py`: 위치 정보 수신 및 저장
   - `telegram_bot.py`: 위치 정보 포맷팅 (위도/경도 + Google Maps 링크)
   - `get_24h_context()`: 위치 정보도 컨텍스트에 포함
   - 활용: 맛집 추천, 날씨 조회, 경로 안내, 부동산 시세 등
   - 테스트: `test_location_support.py`

---

## 작업 처리 원칙 (중요!)

텔레그램으로 새로운 명령을 받으면 **반드시** 다음 순서로 처리해야 한다:

### 1. 즉시 답장 (작업 시작 알림)
새 메시지 확인 즉시 작업 시작을 알리는 답장을 보낸다.
```python
from telegram_sender import send_message_sync

# 즉시 답장
send_message_sync(task['chat_id'], "✅ 작업을 시작했습니다!")
```

### 2. 진행 중 경과 보고 (실시간 피드백)
작업이 여러 단계로 나뉘거나 시간이 오래 걸리는 경우, **각 주요 단계마다** 경과를 보고한다.
```python
# 작업 진행 중간중간 보고
send_message_sync(chat_id, "📊 30% - 파일 읽기 완료")
send_message_sync(chat_id, "📊 50% - 데이터 처리 중...")
send_message_sync(chat_id, "📊 70% - 이미지 생성 중...")
send_message_sync(chat_id, "📊 90% - 최종 검토 중...")
```

### 3. 최종 결과 보고 (작업 완료)
작업이 모두 끝나면 `report_telegram()`으로 최종 결과와 파일을 전송한다.
```python
# 최종 결과 전송
report_telegram(
    instruction=task['instruction'],
    result_text="작업 완료! 총 3개 파일을 생성했습니다.",
    chat_id=task['chat_id'],
    timestamp=task['timestamp'],
    files=["결과1.pdf", "결과2.png", "결과3.html"]
)
```

### 4. 처리 완료 표시
```python
mark_done_telegram(task['message_id'])
```

### 예시: 카페 홈페이지 제작 작업
```python
# 1. 즉시 답장
send_message_sync(chat_id, "✅ 카페 홈페이지 제작을 시작합니다!")

# 2. 진행 경과 보고
send_message_sync(chat_id, "📊 관련 메모리 조사 중... (이전 시안 발견)")
send_message_sync(chat_id, "📊 HTML 구조 설계 완료")
send_message_sync(chat_id, "📊 CSS 스타일 적용 중...")
send_message_sync(chat_id, "📊 이미지 최적화 중...")

# 3. 최종 결과
report_telegram(
    instruction="카페 홈페이지 만들어줘",
    result_text="카페 홈페이지 제작 완료! 반응형 디자인으로 제작했습니다.",
    chat_id=chat_id,
    timestamp=timestamp,
    files=["cafe_homepage.html", "styles.css", "preview.png"]
)

# 4. 완료 표시
mark_done_telegram(message_id)
```

### 주의사항
- **즉시 답장 없이 작업만 하면 안 된다** - 사용자가 봇이 응답하는지 모를 수 있음
- **진행 경과 없이 오래 걸리면 안 된다** - 사용자가 작업이 멈춘 것으로 오해할 수 있음
- **최종 결과 없이 끝내면 안 된다** - 메모리에 기록되지 않고 파일도 전송되지 않음

---

## 동시 작업 방지 (이중 안전 장치)

### 1. 프로세스 레벨 중복 방지 (mybot_autoexecutor.bat) - 🆕 개선됨!

**개선된 3단계 안전 장치**로 효율성과 복구 능력을 대폭 향상:

```batch
REM 1. Claude 프로세스 먼저 확인! (실제 진행 중인지)
tasklist... find "claude" | find "append-system-prompt-file"
→ 프로세스 있으면 exit /b 98 (정상 실행 중)

REM 2. Lock 파일 확인 (프로세스 없는데 Lock 있으면 오류!)
if exist "mybot_autoexecutor.lock"
→ 프로세스 없음 + Lock 있음 = 오류 중단! Lock 삭제 후 복구

REM 3. 빠른 메시지 확인 (Claude Code 실행 전!)
python quick_check.py
→ exit code 0: 새 메시지 없음 → 즉시 종료 (Claude Code 실행 안 함!)
→ exit code 1: 새 메시지 있음 → Claude Code 실행

REM 4. Lock 파일 생성 (Claude Code 실행 직전)
echo %date% %time% > mybot_autoexecutor.lock
```

**개선 효과**:
- ✅ **즉시 복구**: 오류 중단 시 30분 기다리지 않고 바로 재시작
- ✅ **정확한 판단**: 실제 프로세스 존재 여부로 진행 중 판단
- ✅ **빠른 확인**: Python으로 메시지만 확인 (0.1초)
- ✅ **리소스 절약**: 새 메시지 없으면 Claude Code 로딩 안 함 (90% 시간 절약!)
- ✅ **배터리 절약**: 불필요한 프로세스 실행 최소화

### 2. 메시지 레벨 중복 방지 (telegram_bot.py) - 🆕 활동 기반 타임아웃

**working.json**으로 동일 메시지를 여러 에이전트가 처리하는 것을 방지:

- **잠금 파일**: `working.json` (프로젝트 루트)
- **구조**:
  ```json
  {
    "message_id": int,
    "instruction_summary": str,
    "started_at": str,
    "last_activity": str  // 🆕 마지막 활동 시각
  }
  ```
- **🆕 활동 기반 스탈네스 감지**:
  - 경과 보고(`send_message_sync()`) 시마다 `last_activity` 자동 갱신
  - **마지막 활동**으로부터 30분 경과 → 스탈 작업으로 간주
  - 긴 작업도 중간 경과 보고만 있으면 계속 진행 ✅
  - 침묵 30분 → 자동 재시작 (처음부터) ✅

- **자동 처리**:
  1. `check_telegram()`이 `working.json` 자동 확인
  2. 활동 중 (< 30분) → 빈 리스트 반환 (다른 작업 대기)
  3. 스탈 감지 (≥ 30분) → 텔레그램 알림 + 재시작
  4. 재시작 시 지시사항 앞에 컨텍스트 추가:
     ```
     ⚠️ [중단된 작업 재시작]
     이전 작업의 진행 상태를 확인한 후, 합리적으로 진행할 것.
     ```
  5. 작업 완료 후 `remove_working_lock()` 호출

**→ 메시지 단위로 중복 처리 방지 + 스마트 재시작!**

### 잠금 파일 관리

두 잠금 파일 모두 Git에 커밋하지 않음 (`.gitignore`에 등록됨):
- `mybot_autoexecutor.lock` - 프로세스 잠금
- `working.json` - 메시지 잠금

---

## 작업 시작 전 메모리 조사 (필수)

지시사항을 실행하기 **앞서** 반드시 관련된 메모리를 먼저 조사해야 한다.

- `load_memory()`를 호출하여 기존 메모리 파일을 전부 읽는다.
- 지시사항의 키워드(예: 카페, 홈페이지, 시안 등)와 관련된 메모리가 있으면 해당 내용을 참고한다.
- 특히 `[보낸파일]` 섹션을 확인하여 이전에 보낸 파일이 있으면 **해당 작업 폴더 (`tasks/msg_X/`)에서 파일을 찾아** 기반으로 작업해야 한다.
- 연계된 작업을 놓치면 이전 결과와 불일치하는 문제가 발생할 수 있으므로, 관련 메모리가 없다는 것을 확인한 후에만 새로운 작업을 시작한다.

### 작업 폴더 구조 (중요!)

각 텔레그램 메시지는 독립적인 작업 폴더에서 관리된다:

```
tasks/
├── msg_5/
│   ├── task_info.txt       # 메모리 (지시사항, 결과, 보낸파일)
│   ├── cafe_landing.html   # 작업 결과물
│   ├── styles.css
│   └── preview.png
├── msg_6/
│   ├── task_info.txt
│   └── report.pdf
└── msg_7/
    └── task_info.txt
```

**작업 원칙**:
- 각 메시지의 작업은 `tasks/msg_{message_id}/` 폴더에서 수행
- 결과 파일도 해당 폴더에 저장
- 과거 작업 참조 시 `tasks/msg_X/` 폴더에서 파일 찾기

### 메모리 검색 (인덱스 기반 - 빠름!)

과거 작업을 찾을 때는 **인덱스 기반 검색**을 사용한다:

```python
from telegram_bot import search_memory

# 키워드로 검색
matches = search_memory(keyword="카페")
# → [
#     {
#       "message_id": 5,
#       "instruction": "카페 홈페이지 만들어줘",
#       "keywords": ["카페", "홈페이지", "HTML"],
#       "result_summary": "카페 홈페이지 완성!",
#       "files": ["cafe_landing.html"],
#       "task_dir": "tasks/msg_5"
#     },
#     ...
#   ]

# 특정 message_id로 검색
task = search_memory(message_id=5)[0]
# → {"message_id": 5, "task_dir": "tasks/msg_5", ...}

# 필요한 폴더만 상세 조회
task_dir = task["task_dir"]  # "tasks/msg_5"
files = os.listdir(task_dir)  # 해당 폴더의 파일 목록
```

**장점**:
- ✅ 빠른 검색 (tasks/index.json 1개 파일만 읽음)
- ✅ 키워드, message_id로 즉시 찾기
- ✅ 필요한 폴더만 상세 조회

---

## 작업 흐름 (자동화됨) - 🆕 최적화됨!

1. 사용자가 텔레그램 `@mysonol_bot`에게 메시지 보냄 (여러 개 가능!)
2. Windows 작업 스케줄러가 5분마다 `mybot_autoexecutor.bat` 실행
3. **1단계: Claude 프로세스 확인** → 실제 진행 중이면 즉시 종료
4. **2단계: Lock 파일 확인** → 프로세스 없는데 Lock 있으면 오류 중단, Lock 삭제 후 복구
5. **3단계: 빠른 메시지 확인 (Python)** → `quick_check.py` 실행
   - 새 메시지 없으면 → **즉시 종료 (Claude Code 실행 안 함!)** ← 90% 시간 절약!
   - 새 메시지 있으면 → 6번으로
6. **4단계: Lock 파일 생성** → Claude Code 실행 직전에 생성
7. **Claude Code 실행** → `check_telegram()` 호출 → **메시지 레벨 중복 방지** (working.json 자동 확인)
8. 새 메시지가 있으면:
   - **🆕 여러 메시지 합산** → `combine_tasks(pending)`로 모든 미처리 메시지를 하나로 통합
   - **즉시 답장** → `send_message_sync()`로 작업 시작 알림 (합산 개수 표시)
   - **`create_working_lock(message_ids, combined_instruction)`** → 원자적 잠금 생성 (실패 시 종료)
   - **`reserve_memory_telegram(combined_instruction, chat_id, all_timestamps, message_ids)`** → 메인 폴더 + 참조 폴더 생성 + 메모리 예약
   - **`load_memory()`** → 모든 `tasks/*/task_info.txt` 읽기, 관련 작업 조사
   - **작업 디렉토리 변경** → `get_task_dir(message_ids[0])`로 메인 폴더 이동
   - **작업 실행** → 파일 조작, 코드 실행 (결과물은 현재 폴더에 저장)
   - **진행 경과 보고** → `send_message_sync()`로 주요 단계마다 피드백
   - **`report_telegram(combined_instruction, result_text, chat_id, all_timestamps, message_ids, files)`** → 결과 전송 + 메모리 덮어쓰기
   - **`mark_done_telegram(message_ids)`** → 모든 메시지 처리 완료 기록
   - **`remove_working_lock()`** → 작업 잠금 해제

### 🆕 여러 메시지 합산 처리 예시

```
사용자 (10:00): 카페 홈페이지 만들어줘
사용자 (10:01): 반응형으로 해줘
사용자 (10:02): 다크모드도 추가해줘

→ Claude (10:05): ✅ 작업을 시작했습니다! (총 3개 요청 합산 처리)

→ 통합 지시사항:
   [요청 1] (10:00) 카페 홈페이지 만들어줘
   [요청 2] (10:01) 반응형으로 해줘
   [요청 3] (10:02) 다크모드도 추가해줘

→ Claude: 3가지 요청을 모두 고려하여 한 번에 처리
→ 결과: 카페 홈페이지 (반응형 + 다크모드) 완성!
```

### 🆕 이미지/파일 첨부 처리 예시

```
사용자 (11:00): 이 로고로 명함 디자인해줘
                 [이미지 첨부: logo.png]

→ Claude (11:05): ✅ 작업을 시작했습니다!

→ 통합 지시사항:
   [요청 1] (11:00)
   이 로고로 명함 디자인해줘

   📎 첨부 파일:
     🖼️ image_12345.jpg (125.3 KB)
        경로: E:\CLAUDE_PROJECT\mybot_ver2\tasks\msg_12345\image_12345.jpg

→ Claude: Read 도구로 이미지 읽기 → 명함 디자인 생성
→ 결과: 명함 디자인 완성! (logo.png 기반)
```

```
사용자 (12:00): 이 이력서 PDF로 변환해줘
                 [문서 첨부: resume.docx]
사용자 (12:01): 사진도 추가해줘
                 [이미지 첨부: profile.jpg]

→ Claude (12:05): ✅ 작업을 시작했습니다! (총 2개 요청 합산 처리)

→ 통합 지시사항:
   [요청 1] (12:00)
   이 이력서 PDF로 변환해줘

   📎 첨부 파일:
     📄 resume.docx (2.1 MB)
        경로: E:\CLAUDE_PROJECT\mybot_ver2\tasks\msg_23456\resume.docx

   [요청 2] (12:01)
   사진도 추가해줘

   📎 첨부 파일:
     🖼️ profile.jpg (450.2 KB)
        경로: E:\CLAUDE_PROJECT\mybot_ver2\tasks\msg_23457\profile.jpg

→ Claude: DOCX 읽기 → 이미지 삽입 → PDF 생성
→ 결과: 이력서 PDF 완성! (사진 포함)
```

### 🆕 봇 응답 포함 컨텍스트 (완전한 대화 흐름 이해)

**사용자 메시지 + 봇 응답을 모두 컨텍스트에 포함하여 대화 흐름을 완벽히 이해합니다!**

```
사용자 (13:00): 카페 홈페이지 만들어줘
봇 (13:05): ✅ 완료! cafe.html을 생성했습니다.

사용자 (14:00): 거기에 다크모드도 추가해줘 ← "거기"가 뭘까?
봇 (14:05): ✅ 다크모드 추가 완료!

사용자 (15:00): 로고도 추가해줘
      [이미지 첨부: logo.png]

→ Claude (15:05): 새 메시지 확인!

→ 컨텍스트:
   === 최근 24시간 대화 내역 ===

   [2026-02-07 13:00:00] 홍길동: 카페 홈페이지 만들어줘
   [2026-02-07 13:05:00] 🤖 소놀봇: ✅ 완료! cafe.html을 생성했습니다.
                                  반응형 디자인으로 제작했습니다.
                                  [전송: cafe.html, styles.css]

   [2026-02-07 14:00:00] 홍길동: 거기에 다크모드도 추가해줘
   [2026-02-07 14:05:00] 🤖 소놀봇: ✅ 다크모드 추가 완료!
                                  CSS에 다크모드 스타일을 추가했습니다.
                                  [전송: cafe.html, styles.css]

→ Claude: ✅ "거기" = cafe.html 임을 알 수 있음!
→ Claude: ✅ 이미 다크모드가 추가되었음을 알 수 있음!
→ Claude: cafe.html에 로고 이미지 추가 작업 진행
```

**장점**:
- ✅ 대명사 참조 이해 ("거기", "그거", "그 파일" 등)
- ✅ 이전 작업 결과 인식 (중복 작업 방지)
- ✅ 대화 맥락 유지 (연속된 요청 처리)
- ✅ 파일 추적 (어떤 파일을 만들었는지 기억)

### 🆕 실시간 지시사항 업데이트 (작업 중 새 메시지 반영)

**작업 진행 중에 새로운 메시지가 도착하면 자동으로 감지하고 반영합니다!**

#### 동작 방식

```
21:00 작업 시작: "카페 홈페이지 만들어줘"
   ↓
21:05 경과 보고: "📊 HTML 구조 설계 완료"
   ↓ (이 시점에 자동으로 새 메시지 확인)
   ↓
21:06 새 메시지 도착: "다크모드도 추가해줘" 🆕
   ↓
21:10 경과 보고: "📊 CSS 스타일 적용 중..."
   ↓ (새 메시지 감지!)
   ↓
   텔레그램 알림: "✅ 새로운 요청 1개 확인
                   1. 다크모드도 추가해줘
                   진행 중인 작업에 반영하겠습니다."
   ↓
   new_instructions.json에 저장
   ↓
21:15 완료: 카페 홈페이지 + 다크모드 ✅
   ↓
   모든 메시지 처리 완료 표시 (원래 메시지 + 새 메시지)
```

#### 핵심 기능

1. **자동 감지**: `send_message_sync()` 호출 시마다 자동으로 새 메시지 확인
2. **즉시 알림**: 새 메시지 발견 시 사용자에게 알림 전송
3. **파일 저장**: `new_instructions.json`에 저장하여 작업 중 참조 가능
4. **자동 처리**: 작업 완료 시 새 메시지도 함께 처리 완료 표시

#### API 사용법

```python
# 경과 보고 시 (자동으로 새 메시지 확인됨)
send_message_sync(chat_id, "📊 50% - 데이터 처리 중...")

# 작업 중 새 지시사항 확인 (선택)
new_instructions = load_new_instructions()
if new_instructions:
    print(f"새 지시사항 {len(new_instructions)}개:")
    for inst in new_instructions:
        print(f"  - {inst['instruction']}")

# 작업 완료 시 (자동으로 새 메시지도 함께 처리 완료)
mark_done_telegram(message_ids)  # 원래 메시지 + 새 메시지 모두 처리
```

#### 예시

```
사용자: 이력서 PDF 만들어줘
   ↓
Claude: ✅ 작업 시작!
Claude: 📊 텍스트 추출 중...
   ↓
사용자: 사진도 포함해줘 🆕
   ↓
Claude: 📊 레이아웃 설계 중...
Claude: ✅ 새로운 요청 1개 확인
        1. 사진도 포함해줘
        진행 중인 작업에 반영하겠습니다.
   ↓
Claude: 📊 사진 추가 중... (새 요청 반영!)
Claude: ✅ 완료! 이력서 PDF + 사진 포함
```

---

## telegram_bot.py API

```python
from telegram_bot import (
    check_telegram,
    combine_tasks,
    create_working_lock,
    remove_working_lock,
    reserve_memory_telegram,
    report_telegram,
    mark_done_telegram,
    load_memory,
    get_task_dir,
    load_new_instructions,  # 🆕 작업 중 추가된 지시사항 읽기
    clear_new_instructions  # 🆕 새 지시사항 정리
)
from telegram_sender import send_message_sync

# 1. 대기 중인 지시사항 확인 (working.json 자동 확인)
pending = check_telegram()
# [{"instruction": str, "message_id": int, "chat_id": int, "timestamp": str}, ...]
# → 다른 작업 진행 중이면 빈 리스트 반환!

if not pending:
    print("임무 완료")
    exit()

# 2. 여러 메시지를 하나로 합산 (NEW!)
combined = combine_tasks(pending)
# {
#   "combined_instruction": "[요청 1] 메시지1\n[요청 2] 메시지2\n...",
#   "message_ids": [1, 2, 3],
#   "chat_id": int,
#   "timestamp": str,
#   "all_timestamps": [str, str, str],
#   "user_name": str,
#   "files": [...]  # 🆕 모든 첨부 파일 정보 (path, type, size 등)
# }

# 3. 즉시 답장 (작업 시작 알림)
if len(combined['message_ids']) > 1:
    msg = f"✅ 작업을 시작했습니다! (총 {len(combined['message_ids'])}개 요청 합산 처리)"
else:
    msg = "✅ 작업을 시작했습니다!"
send_message_sync(combined['chat_id'], msg)

# 4. 작업 잠금 생성 (원자적 - 실패 시 종료)
if not create_working_lock(combined['message_ids'], combined['combined_instruction']):
    print("⚠️ 잠금 실패. 다른 작업이 진행 중입니다.")
    exit()

# 5. 메모리 예약 (즉시 [지시]만 기록 → 중복 방지)
# 동시에 tasks/msg_{message_id}/ 폴더 생성
reserve_memory_telegram(
    combined['combined_instruction'],
    combined['chat_id'],
    combined['all_timestamps'],  # 리스트
    combined['message_ids']      # 리스트
)

# 6. 기존 메모리 파일 전부 읽기
memories = load_memory()
# → tasks/*/task_info.txt에서 읽음
# → 관련 작업이 있으면 해당 tasks/msg_X/ 폴더에서 파일 찾기

# 7. 작업 수행 + 진행 경과 보고 (주요 단계마다)
# 중요: get_task_dir()로 절대 경로를 받아 작업 폴더로 이동 (chdir 후에도 경로 안 깨짐)
task_dir = get_task_dir(combined['message_ids'][0])  # 첫 번째 메시지 폴더가 메인
os.chdir(task_dir)  # 작업 폴더로 이동

send_message_sync(combined['chat_id'], "📊 50% - 데이터 처리 중...")

# 8. 결과 전송 + 메모리 덮어쓰기
# 파일은 현재 작업 폴더(task_dir)에 저장됨
report_telegram(
    combined['combined_instruction'],
    result_text="작업 완료!",
    chat_id=combined['chat_id'],
    timestamp=combined['all_timestamps'],  # 리스트
    message_id=combined['message_ids'],    # 리스트
    files=["cafe_landing.html", "preview.png"]  # 상대 경로 OK
)

# 9. 처리 완료 기록 (모든 메시지)
mark_done_telegram(combined['message_ids'])  # 리스트

# 10. 작업 잠금 해제
remove_working_lock()
```

> **중요**:
> - `check_telegram()`은 `working.json`을 자동으로 확인하여 다른 작업이 진행 중이면 빈 리스트를 반환합니다.
> - `combine_tasks()`로 여러 메시지를 하나로 합산하여 처리합니다. (NEW!)

---

## 메모리 시스템 (tasks/)

봇은 작업을 실행할 때마다 결과를 `tasks/msg_{message_id}/` 폴더에 저장한다.

### 폴더 구조
```
tasks/
├── msg_5/
│   ├── task_info.txt       # 작업 메모리
│   ├── cafe_landing.html   # 작업 결과물
│   └── preview.png
├── msg_6/
│   ├── task_info.txt
│   └── report.pdf
└── msg_7/
    └── task_info.txt
```

- **메시지 ID 기반 폴더**: 텔레그램 `message_id`를 폴더명으로 사용 (예: `msg_5`)
- **작업 격리**: 각 작업이 독립적인 폴더에서 관리
- **결과물 보관**: 작업 결과 파일도 같은 폴더에 저장

### task_info.txt 내용
```
[시간] 2026-02-03 15:00:00
[메시지ID] 5
[출처] Telegram (chat_id: 1234567890)
[메시지날짜] 2026-02-03 14:55:00
[지시] 카페 홈페이지 만들어줘
[결과] 카페 홈페이지 완성! 반응형 디자인으로 제작했습니다.
[보낸파일] cafe_landing.html, preview.png
```

- **메시지ID 기록**: 텔레그램 `message_id` 명시 (폴더 찾기 용이)
- **텔레그램날짜 기록 필수**: 원본 메시지의 날짜를 반드시 기록
- **보낸파일 명시 필수**: 작업 결과로 전송한 파일명을 반드시 기록

### 작업 흐름
1. 봇 실행 시 `load_memory()`로 모든 `tasks/*/task_info.txt` 읽기
2. 관련 작업이 있으면 해당 `tasks/msg_X/` 폴더에서 파일 찾기
3. 새 작업 시작 시 `tasks/msg_{message_id}/` 폴더 생성
4. 작업 결과물을 해당 폴더에 저장
5. `task_info.txt`에 메모리 기록

---

## 자동 실행 설정

Windows 작업 스케줄러를 통해 5분마다 자동으로 텔레그램 메시지를 확인하고 처리합니다.

**명령어**:
```powershell
# 작업 생성 (register_scheduler.bat 사용 - 폴더명 기반 자동 이름 생성!)
register_scheduler.bat 우클릭 -> "관리자 권한으로 실행" 클릭

# 비활성화 (자동 실행 멈추기) - 작업 이름은 폴더명에 따라 다름
schtasks /Change /TN "Claude_AutoBot_mybot_ver2" /DISABLE

# 재시작 (자동 실행 다시 켜기)
schtasks /Change /TN "Claude_AutoBot_mybot_ver2" /ENABLE

# 완전 삭제
schtasks /Delete /TN "Claude_AutoBot_mybot_ver2" /F
```

**🎉 멀티 봇 지원**: 폴더명에 따라 작업 이름이 자동 생성됩니다!
- `mybot_ver2` 폴더 → 작업 이름: `Claude_AutoBot_mybot_ver2`
- `mybot_ver3` 폴더 → 작업 이름: `Claude_AutoBot_mybot_ver3`
- **폴더 복사만으로 여러 봇 동시 운영 가능!**

**로그 확인**:
```
E:\CLAUDE_PROJECT\claude_task.log
```

---

## 사용 방법

### 방법 1: 자동 실행 (추천)
Windows 작업 스케줄러가 5분마다 자동으로 확인합니다.
1. 텔레그램 `@mysonol_bot`에게 메시지 보내기
2. 5분 이내 자동 처리 및 결과 회신

### 방법 2: 수동 실행
Claude Code에게 직접 명령:
```
텔레그램 메시지 확인해줘
```

### 방법 3: 리스너 백그라운드 실행 (선택)
`check_telegram()`이 자체로 Telegram API를 폴링하므로, 기본적으로 리스너를 별도 실행하는 것은 불필요합니다.
실시간(10초 간격) 수집이 필요한 경우에만 사용하며, 이때 자동 실행(방법 1)과는 동시 사용하지 않습니다:
```bash
python telegram_listener.py
```

**상세 사용 가이드**: `TELEGRAM_USAGE.md` 참조
