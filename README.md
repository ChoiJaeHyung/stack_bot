# 소놀봇 (mybot_ver2)

텔레그램을 통해 실시간으로 지시사항을 받고 Claude Code가 자동으로 작업을 처리하는 자율 작업 봇입니다.

## ✨ 주요 기능

- 📱 **텔레그램 통합**: 텔레그램으로 명령을 보내면 자동 처리
- 🤖 **Claude Code 자동 실행**: AI가 코드 작성, 파일 생성, 분석 등 자동 수행
- 💾 **메모리 시스템**: 모든 작업 기록 및 컨텍스트 유지
- 🔄 **자동 스케줄링**: 1분마다 자동으로 새 메시지 확인
- 📎 **파일/이미지 지원**: 사진, 문서, 비디오, 위치 정보 자동 처리
- 🚀 **효율적 실행**: 새 메시지 없으면 0.1초만에 종료 (98% 시간 절약)

## 📋 요구사항

- **Windows 10/11** (작업 스케줄러 사용)
- **Python 3.8+**
- **Claude Code** (설치됨)
- **텔레그램 봇 토큰** (BotFather에서 발급)

## 🚀 빠른 시작

### 1. 텔레그램 봇 토큰 발급

1. 텔레그램에서 [@BotFather](https://t.me/BotFather) 검색
2. `/newbot` 명령으로 봇 생성
3. 봇 이름 및 사용자명 설정
4. 발급받은 **토큰** 복사 (예: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 2. 사용자 ID 확인

1. 텔레그램에서 [@userinfobot](https://t.me/userinfobot) 검색
2. `/start` 명령 실행
3. **사용자 ID** 복사 (예: `123456789`)

또는 프로젝트 폴더에서:
```bash
python get_my_id.py
```

### 3. 프로젝트 설치

**방법 A: 자동 설치 (추천)**

1. `setup.bat` 파일을 더블클릭
2. 봇 토큰과 사용자 ID 입력
3. 설치 완료!

**방법 B: 수동 설치**

```bash
# Python 패키지 설치
pip install -r requirements.txt

# .env 파일 생성
copy .env.example .env
notepad .env
```

`.env` 파일 내용:
```env
TELEGRAM_BOT_TOKEN=당신의_봇_토큰
TELEGRAM_ALLOWED_USERS=당신의_사용자_ID
TELEGRAM_POLLING_INTERVAL=10
```

### 4. 작업 스케줄러 등록 (자동 실행)

1. `register_scheduler.bat` 파일을 **마우스 우클릭** → **관리자 권한으로 실행**
2. 등록 완료! (1분마다 자동 확인)

## 📖 사용 방법

### 텔레그램으로 명령 보내기

1. 텔레그램에서 당신의 봇 검색 (예: `@mysonol_bot`)
2. 메시지 보내기:
   ```
   카페 홈페이지 만들어줘
   ```
3. 1분 이내 자동 처리 및 결과 회신! 🎉

### 지원되는 작업

- 📝 **파일 생성/편집**: "이력서 PDF 만들어줘"
- 🎨 **디자인**: "명함 디자인해줘" + 이미지 첨부
- 💻 **코드 작성**: "Python 크롤링 코드 작성해줘"
- 📊 **데이터 분석**: "이 CSV 파일 분석해줘" + 파일 첨부
- 🌍 **위치 기반**: "여기 날씨 알려줘" + 위치 전송
- 🔍 **정보 검색**: "최신 AI 뉴스 정리해줘"

## 🔧 고급 설정

### 작업 스케줄러 관리

```bash
# 상태 확인
schtasks /Query /TN "Claude_AutoTestFix_30Sec" /FO LIST

# 비활성화 (자동 실행 멈추기)
schtasks /Change /TN "Claude_AutoTestFix_30Sec" /DISABLE

# 활성화 (자동 실행 재개)
schtasks /Change /TN "Claude_AutoTestFix_30Sec" /ENABLE

# 삭제
schtasks /Delete /TN "Claude_AutoTestFix_30Sec" /F
```

### 수동 테스트

```bash
# 빠른 메시지 확인 (0.1초)
python quick_check.py

# 전체 처리 테스트
mybot_autoexecutor.bat

# 처리 스크립트 직접 실행
python process_telegram.py
```

### 로그 확인

**Windows 명령 프롬프트 (CMD)**:
```cmd
REM 전체 로그 보기
type claude_task.log

REM 마지막 50줄 보기 (PowerShell)
powershell -command "Get-Content claude_task.log -Tail 50"
```

**Git Bash 사용 시**:
```bash
# 최근 로그 확인
tail -50 claude_task.log

# 실시간 로그 모니터링
tail -f claude_task.log
```

**또는**: 텍스트 에디터로 `claude_task.log` 파일 직접 열기

## 📁 프로젝트 구조

```
mybot_ver2/
├── setup.bat                   # 자동 설치 스크립트
├── register_scheduler.bat      # 작업 스케줄러 등록
├── mybot_autoexecutor.bat     # 메인 실행 파일 (스케줄러가 호출)
├── quick_check.py             # 빠른 메시지 확인
├── telegram_bot.py            # 텔레그램 봇 로직
├── telegram_listener.py       # 메시지 수집기
├── telegram_sender.py         # 메시지 전송기
├── process_telegram.py        # 처리 스크립트
├── requirements.txt           # Python 패키지 목록
├── .env                       # 환경 변수 (봇 토큰 등)
├── CLAUDE.md                  # 상세 문서
├── tasks/                     # 작업 메모리 폴더
│   ├── index.json            # 빠른 검색 인덱스
│   └── msg_*/                # 메시지별 작업 폴더
└── claude_task.log           # 실행 로그
```

## 🔒 보안

- `.env` 파일은 Git에 커밋되지 않음
- 허용된 사용자 ID만 봇 사용 가능
- 작업 메모리는 로컬에만 저장

## 🆘 문제 해결

### "Python이 설치되어 있지 않습니다"
- Python 3.8 이상을 설치하세요: https://www.python.org/downloads/

### "관리자 권한이 필요합니다"
- `register_scheduler.bat`를 우클릭 → "관리자 권한으로 실행"

### "봇이 응답하지 않습니다"
1. `.env` 파일의 봇 토큰 확인
2. 사용자 ID가 `TELEGRAM_ALLOWED_USERS`에 등록되었는지 확인
3. 로그 확인: `type claude_task.log` (또는 파일 직접 열기)

### "작업이 중단되었습니다"
- Lock 파일 자동 복구 기능이 있으므로 다음 주기(1분)에 자동 재시작됩니다.

## 📦 다른 컴퓨터로 이동

**모든 경로가 자동 감지되므로 어디든 복사 가능!**

1. 전체 폴더 복사
2. `setup.bat` 더블클릭 (Python 패키지 설치 + .env 설정)
3. `register_scheduler.bat` 우클릭 → **관리자 권한으로 실행** (작업 스케줄러 등록)
4. 완료! 🎉

**중요**: 같은 컴퓨터에서 폴더 경로만 바꾸는 경우에도 3번(작업 스케줄러 재등록)은 필수입니다!

## 🤖 멀티 봇 운영 (여러 봇 동시 사용)

**폴더명 기반 자동 작업 이름 생성으로 여러 봇을 동시에 운영 가능!**

```
E:\CLAUDE_PROJECT\
├── mybot_ver2\      → 작업 이름: Claude_AutoBot_mybot_ver2
├── mybot_ver3\      → 작업 이름: Claude_AutoBot_mybot_ver3
└── sonol_assistant\ → 작업 이름: Claude_AutoBot_sonol_assistant
```

### 멀티 봇 설정 방법:

1. 폴더 복사 (예: `mybot_ver2` → `mybot_ver3`)
2. 새 텔레그램 봇 생성 (BotFather에서)
3. `setup.bat` 실행 → 새 봇 토큰 입력
4. `register_scheduler.bat` 실행 (관리자 권한)

**코드 수정 불필요!** 폴더명만 다르면 자동으로 별도 작업으로 등록됩니다! 🚀

## 📚 상세 문서

- **CLAUDE.md**: 전체 시스템 아키텍처 및 API 문서
- **TELEGRAM_BOT.md**: 텔레그램 봇 설계
- **FILE_SUPPORT.md**: 파일 첨부 기능
- **LOCATION_SUPPORT.md**: 위치 정보 기능

## 🤝 기여

이슈 및 풀 리퀘스트 환영합니다!

## 📄 라이센스

MIT License

---

**Made with ❤️ by Claude Code**
