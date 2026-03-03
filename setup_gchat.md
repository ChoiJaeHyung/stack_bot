# Google Chat 비서최재형 GCP 설정 가이드

## 사전 요구사항

- Google Workspace 계정 (jhchoi@rsupport.com)
- Google Cloud Console 접근 권한

---

## Step 1: GCP 프로젝트 생성

1. [Google Cloud Console](https://console.cloud.google.com) 접속
2. 상단 프로젝트 선택 > "새 프로젝트"
3. 프로젝트 이름: `jaehyung-bot` (또는 원하는 이름)
4. 프로젝트 ID 기록 → `.env`의 `GCP_PROJECT_ID`에 입력

## Step 2: API 활성화

Google Cloud Console > APIs & Services > Library에서 다음 API 활성화:

- [x] **Google Chat API**
- [x] **Cloud Pub/Sub API**
- [x] **Google Drive API** (파일 전송용)

## Step 3: Pub/Sub 설정

### 3-1. Topic 생성

1. Cloud Console > Pub/Sub > Topics
2. "CREATE TOPIC" 클릭
3. Topic ID: `jaehyung-bot-topic`
4. 생성

### 3-2. Topic에 Chat API Publisher 권한 부여

1. 생성된 Topic 클릭
2. "PERMISSIONS" 탭
3. "ADD PRINCIPAL" 클릭
4. 주 구성원: `chat-api-push@system.gserviceaccount.com`
5. 역할: `Pub/Sub Publisher`
6. 저장

### 3-3. Pull Subscription 생성

1. Topic 상세 > "CREATE SUBSCRIPTION"
2. Subscription ID: `jaehyung-bot-sub`
3. 전송 유형: **Pull** 선택
4. 메시지 보관 기간: 7일
5. 생성

## Step 4: Service Account 생성

1. Cloud Console > IAM & Admin > Service Accounts
2. "CREATE SERVICE ACCOUNT" 클릭
3. 이름: `jaehyung-bot-sa`
4. 역할 부여:
   - `Pub/Sub Subscriber` (Pub/Sub 메시지 수신)
   - `Pub/Sub Viewer` (구독 정보 조회)
5. 완료 후 Service Account 클릭
6. "KEYS" 탭 > "ADD KEY" > "Create new key"
7. JSON 선택 > 다운로드
8. 다운로드된 파일을 `D:\mybot_ver2\service-account-key.json`으로 이동

## Step 5: Google Chat API 앱 설정

1. Cloud Console > APIs & Services > Google Chat API
2. "CONFIGURATION" 탭
3. 설정 입력:
   - **앱 이름**: `비서최재형`
   - **아바타 URL**: (선택사항, 원하는 이미지 URL)
   - **설명**: `AI 업무 비서 - 비서최재형`
   - **기능**: "1:1 메시지 수신" 체크
   - **연결 설정**: **Cloud Pub/Sub** 선택
   - **Pub/Sub Topic**: `projects/{프로젝트ID}/topics/jaehyung-bot-topic`
   - **공개 범위**: "특정 사용자 및 그룹에서 사용 가능" 선택
   - **허용 이메일**: `jhchoi@rsupport.com` (추가 사용자 입력 가능)
4. 저장

## Step 6: .env 설정

```env
# Google Chat AI 비서
GOOGLE_APPLICATION_CREDENTIALS=./service-account-key.json
GCP_PROJECT_ID=<Step 1에서 기록한 프로젝트 ID>
PUBSUB_SUBSCRIPTION_ID=<Step 4에서 생성한 구독 ID>
GCHAT_ALLOWED_DOMAIN=<허용할 이메일 도메인 (예: rsupport.com)>
BOT_NAME=<봇 이름>
```

## Step 7: 의존성 설치

```bash
pip install -r requirements.txt
```

## Step 8: 테스트

### 8-1. 메시지 수신 테스트

```bash
python gchat_listener.py
```

→ Google Chat에서 비서최재형에게 "테스트" 메시지 전송
→ 콘솔에 메시지 수신 로그 확인
→ `gchat_messages.json` 파일 생성 확인

### 8-2. 메시지 발신 테스트

```bash
python gchat_sender.py spaces/XXXXXXX "테스트 메시지"
```

→ Google Chat에서 비서최재형이 메시지 보낸 것 확인

### 8-3. 전체 파이프라인 테스트

```bash
python quick_check.py
echo %ERRORLEVEL%
```

→ 새 메시지 있으면 exit code 1, 없으면 0

```bash
mybot_autoexecutor.bat
```

→ 전체 워크플로 동작 확인

---

## 문제 해결

### "Permission denied" 오류
- Service Account에 `Pub/Sub Subscriber` 역할이 있는지 확인
- `GOOGLE_APPLICATION_CREDENTIALS` 경로가 올바른지 확인

### "Chat app not found" 오류
- Google Chat API 설정에서 앱이 게시되었는지 확인
- 공개 범위에 본인 이메일이 포함되어 있는지 확인

### "Topic not found" 오류
- Pub/Sub Topic 이름이 정확한지 확인
- Topic에 `chat-api-push@system.gserviceaccount.com` Publisher 권한이 있는지 확인

### 관리자 승인이 필요한 경우
- 조직의 Google Workspace 관리자에게 Chat 앱 승인 요청
- Admin Console > Apps > Google Workspace Marketplace apps에서 설정
