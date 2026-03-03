# 텔레그램 봇 사용 가이드

## 시스템 구성

```
텔레그램 앱 (사용자)
    ↓ 메시지 전송
텔레그램 봇 API
    ↓ 메시지 수집 (10초마다)
telegram_listener.py
    ↓ 저장
telegram_messages.json
    ↓ 읽기
Claude Code (check_telegram)
    ↓ 작업 실행
telegram_bot.report_telegram()
    ↓ 결과 전송
텔레그램 앱 (사용자)
```

---

## 📋 사용 방법

### 1단계: 메시지 수집기 실행

메시지 수집기를 백그라운드로 실행합니다.

**방법 A: 수동 실행 (터미널)**
```bash
python telegram_listener.py
```

**방법 B: 백그라운드 실행 (Windows)**
```bash
start /B python telegram_listener.py
```

**방법 C: 별도 터미널에서 실행**
```bash
# 새 터미널 창을 열고
cd E:\CLAUDE_PROJECT\mybot_ver2
python telegram_listener.py
```

> 💡 메시지 수집기는 계속 실행 상태를 유지해야 합니다!

---

### 2단계: 텔레그램에서 메시지 보내기

텔레그램 앱에서 `@mysonol_bot`에게 메시지를 보냅니다.

예시:
```
오늘 날씨 알려줘
```

```
카페 홈페이지 시안 다시 만들어줘
```

```
Python으로 Hello World 프로그램 만들어줘
```

---

### 3단계: Claude Code로 명령 확인

Claude Code에게 다음과 같이 요청합니다:

```
텔레그램 메시지 확인해줘
```

또는

```
python check_telegram.py
```

Claude Code가 자동으로:
1. `check_telegram()` 호출
2. 새 명령 확인
3. 관련 메모리 조사 (`load_memory()`)
4. 작업 시작 전 메모리 예약 (`reserve_memory_telegram()`)
5. 작업 실행
6. 결과 전송 (`report_telegram()`)
7. 처리 완료 표시 (`mark_done_telegram()`)

---

## 🤖 Claude Code 작업 흐름 (예시)

### 사용자 요청:
```
텔레그램 메시지 확인해줘
```

### Claude Code 실행:

```python
from telegram_bot import check_telegram, reserve_memory_telegram, report_telegram, mark_done_telegram, load_memory

# 1. 새 명령 확인
pending = check_telegram()

if not pending:
    print("임무 완료")
    exit()

task = pending[0]

# 2. 메모리 예약 (중복 방지)
reserve_memory_telegram(task['instruction'], task['chat_id'], task['timestamp'])

# 3. 관련 메모리 조사
memories = load_memory()
# ... 메모리 분석 ...

# 4. 작업 실행
# ... Claude Code가 작업 수행 ...
result = "작업 완료 결과..."
files = ["결과파일.txt"]  # 있으면

# 5. 결과 전송
report_telegram(
    task['instruction'],
    result,
    task['chat_id'],
    task['timestamp'],
    files=files
)

# 6. 처리 완료
mark_done_telegram(task['message_id'])
```

---

## 🔄 자동화 설정 (선택)

### Windows 작업 스케줄러 (10초 간격)

**1. 배치 파일 생성** (`check_telegram.bat`)
```batch
@echo off
cd /d E:\CLAUDE_PROJECT\mybot_ver2
python check_telegram.py
```

**2. 작업 스케줄러 등록**

10초 간격은 Windows 작업 스케줄러로 불가능하므로, **무한 루프 방식** 사용:

`auto_telegram_bot.bat`:
```batch
@echo off
:loop
cd /d E:\CLAUDE_PROJECT\mybot_ver2
python check_telegram.py
timeout /t 10 /nobreak >nul
goto loop
```

실행:
```bash
start /B auto_telegram_bot.bat
```

**3. 서비스 등록 (권장)**

NSSM (Non-Sucking Service Manager) 사용:
```bash
# NSSM 다운로드 후
nssm install TelegramBot "E:\CLAUDE_PROJECT\mybot_ver2\telegram_listener.py"
nssm start TelegramBot
```

---

## 📊 상태 확인

### 메시지 수집 상태
```bash
# telegram_messages.json 확인
cat telegram_messages.json
```

### 메모리 확인
```bash
# 텔레그램 관련 메모리
ls -la memory/*TG*
```

### 미처리 메시지 확인
```bash
python check_telegram.py
```

---

## 🔧 트러블슈팅

### 1. 메시지가 수집되지 않음

**원인**: telegram_listener.py가 실행되지 않음

**해결**:
```bash
# 리스너 실행 확인
ps aux | grep telegram_listener

# 없으면 실행
python telegram_listener.py
```

### 2. 봇이 응답하지 않음

**원인**: 봇 토큰 또는 사용자 ID 오류

**해결**:
```bash
# .env 확인
cat .env

# 연결 테스트
python test_telegram_connection.py
```

### 3. "processed": false인데도 처리 안 됨

**원인**: Claude Code가 check_telegram()을 호출하지 않음

**해결**:
```
Claude Code에게 "텔레그램 메시지 확인해줘" 요청
```

---

## 📝 메일 시스템과의 차이점

| 항목 | 메일 (bot.py) | 텔레그램 (telegram_bot.py) |
|---|---|---|
| 키워드 필터 | "소놀봇" 필수 | 모든 메시지 처리 |
| 컨텍스트 | 없음 | 최근 24시간 대화 내역 |
| 폴링 주기 | 5분 | 10초 |
| 메모리 파일명 | `YYYYMMDD_HHMM_*.txt` | `YYYYMMDD_HHMM_[TG]*.txt` |
| 사용자 검증 | 자기 자신만 | ALLOWED_USERS 목록 |

---

## 🎯 다음 개선 사항

1. ✅ 기본 메시지 송수신
2. ✅ 24시간 컨텍스트 전달
3. ✅ 메모리 시스템 통합
4. ⬜ 이미지/파일 수신 지원
5. ⬜ 음성 메시지 지원
6. ⬜ 그룹 채팅 지원
7. ⬜ 명령어 시스템 (/help, /status 등)
8. ⬜ 웹훅 방식 전환 (폴링 → 푸시)
