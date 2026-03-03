# AI 시큐어코딩 MD파일-Security_Checklist.md

> **버전**: 1.0.1(2026.02.27)
> **작성자**: 정보보안팀(sec_tech@rsupport.com)
> **용도**: 코드 생성 전 사전 가이드 / 생성된 코드 점검 / PR 리뷰 체크리스트
> **출처**: KISA 소프트웨어 보안약점 진단가이드(2021) 49개 항목
> **판정**: `양호` 통제+테스트 완료 / `보완필요` 부분 통제 / `취약` 통제 부재

---

## 0) 핵심 보안 원칙

1. **신뢰경계**: 외부입력(파라미터·헤더·쿠키·바디·파일명·API응답) = 전부 비신뢰
2. **최소권한**: DB계정·OS권한·API토큰·IAM은 최소권한으로
3. **안전한 기본값**: deny by default, 최소 노출, 강제 검증
4. **검증 가능성**: 모든 보안통제는 코드·테스트·로그로 증빙

**Source**: 요청 파라미터, 헤더, 쿠키, 바디, 파일명, 외부 API 응답
**Sink**: SQL/XPath/LDAP 생성, Shell 실행, URL 요청, 파일경로 접근, HTML 출력, 역직렬화
**Sanitizer 실효성 판정**: 모듈 존재 여부가 아닌 → 실행경로 연결·우회불가·컨텍스트 적합성으로 판정

---

## 1) AI가 절대 생성하면 안 되는 패턴

```python 예시
# ❌ SQL 문자열 결합
"SELECT * FROM users WHERE id=" + userId

# ❌ shell=True / 명령 문자열 결합
os.system("ping " + host)
subprocess.run("cmd " + input, shell=True)

# ❌ 동적 코드 실행
eval(req.body.expr)
exec(user_input)

# ❌ 비신뢰 역직렬화
pickle.loads(untrusted_data)

# ❌ 하드코드 자격증명
API_KEY = "sk_live_abc123"
password = "P@ssw0rd"

# ❌ TLS/인증서 검증 비활성화
requests.get(url, verify=False)
https.get(url, { rejectUnauthorized: false })

# ❌ 인증·인가 우회 플래그
if debug_mode: skip_auth()
if req.body.isAdmin: approve()

# ❌ fail-open 예외처리
try:
    auth.verify(token)
except Exception:
    pass  # 인증 실패를 무시하고 진행
```

---

## 2) 구현단계 49개 보안약점 통제 기준

### A. 입력데이터 검증 및 표현 (1~17)

| ID | 약점명 | 취약 패턴 (❌ 금지) | 필수 통제 | 검증 증적 |
|---|---|---|---|---|
| 1 | SQL 삽입 | `"WHERE id=" + userId` | Prepared Statement/ORM 바인딩, 동적 컬럼 allowlist | `' OR '1'='1` 페이로드 테스트 |
| 2 | 코드 삽입 | `eval(user_input)` | 동적실행 금지, 허용 동작 맵핑 | 금지 API 스캔 |
| 3 | 경로 조작 | `"/uploads/" + filename` | canonical path 비교, 루트 고정, 확장자 allowlist | `../../etc/passwd` 우회 테스트 |
| 4 | XSS | 템플릿 raw 출력 | 컨텍스트 인코딩, auto-escape 강제 | reflected/stored 페이로드 테스트 |
| 5 | OS 명령어 삽입 | `os.system("ping " + host)` | shell=False, 인자 배열, allowlist | `;&&\|$()` 주입 테스트 |
| 6 | 위험한 파일 업로드 | 확장자만 검사, 웹루트 저장 | 확장자+MIME+시그니처+크기, 비실행 저장소 | `.php.jpg` 우회 업로드 시도 |
| 7 | URL 자동접속 | `redirect(request.args["next"])` | 스킴·도메인 allowlist, 내부망 차단 | open redirect / SSRF 테스트 |
| 8 | XXE | 기본 XML 파서 사용 | DTD·외부엔티티 비활성화 | XXE 페이로드로 로컬파일 접근 차단 확인 |
| 9 | XML/XPath 삽입 | `"//user[name='" + q + "']"` | XPath 파라미터화 | 인젝션 페이로드 테스트 |
| 10 | LDAP 삽입 | `"(uid=" + uid + ")"` | LDAP escape, 검색 base 고정 | wildcard/괄호 주입 테스트 |
| 11 | CSRF | 토큰 없이 쿠키 기반 상태변경 | CSRF 토큰, Origin/Referer 검증, SameSite | 교차요청 재현 테스트 |
| 12 | SSRF | `requests.get(user_url)` | 목적지 allowlist, DNS 재확인, 내부망 IP 차단 | metadata/internal endpoint 차단 테스트 |
| 13 | HTTP 응답분할 | `res.setHeader("X-Info", userInput)` | CR/LF 제거 후 헤더 설정 | `%0d%0a` 주입 테스트 |
| 14 | 정수형 오버플로우 | `int len = Integer.parseInt(a) + Integer.parseInt(b)` | 범위검사, 안전 산술 API | 최소/최대 경계값 테스트 |
| 15 | 보안결정용 입력값 | `if (req.body.isAdmin) approve()` | 서버 DB/세션으로 권한 재조회 | 권한 상승 tampering 테스트 |
| 16 | 버퍼 오버플로우 | `strcpy(dst, src)` | 길이 검증 + 안전 함수(`strncpy`) | 장문 입력 퍼징 |
| 17 | 포맷 스트링 | `printf(user_input)` | 고정 포맷 문자열 사용 | `%x %n` 주입 테스트 |

### B. 보안기능 (18~33)

| ID | 약점명 | 취약 패턴 (❌ 금지) | 필수 통제 | 검증 증적 |
|---|---|---|---|---|
| 18 | 인증 없는 중요기능 | 인증 미들웨어 없는 중요 라우트 | 모든 중요기능 서버측 인증 강제 | 인증 없이 호출 시 401/403 확인 |
| 19 | 부적절한 인가 | 타인 리소스 ID로 조회/수정 | 소유자·역할 기반 인가 일관 적용 | 수평/수직 권한상승 테스트 |
| 20 | 자원 권한 과다 | IAM `actions=["*"], resources=["*"]` | 최소권한, 기본거부, 서비스계정 분리 | IAM/ACL 점검, 권한 시뮬레이션 |
| 21 | 취약 알고리즘 | MD5/SHA1/DES/RC4/ECB 모드 | AES-256-GCM, SHA-256+, ECDSA/RSA-PSS | 코드 스캔 + 암호설정 점검 |
| 22 | 중요정보 평문 | `db.save({"ssn": ssn})` / HTTP 전송 | 저장 암호화, TLS, 마스킹/토큰화 | DB 샘플/패킷 캡처 검증 |
| 23 | 하드코드 비밀 | `API_KEY = "sk_live_123"` | Secret Manager/Vault, 환경변수 주입 | 시크릿 스캔 결과 |
| 24 | 짧은 키 길이 | RSA 1024, 낮은 work factor | RSA 2048+, AES-256, 교체주기 관리 | 키 파라미터 점검 |
| 25 | 약한 난수 | `Random(System.currentTimeMillis())` | CSPRNG(`secrets`, `SecureRandom`, `crypto.randomBytes`) | 토큰 예측 가능성 테스트 |
| 26 | 취약 비밀번호 정책 | 6자 이상만 허용, 잠금 없음 | 최소 길이/복잡도, bcrypt/Argon2, 잠금 | 정책 테스트 케이스 |
| 27 | 전자서명 검증 누락 | `if signature: return True` | 서명값·체인·알고리즘·유효기간 전체 검증 | 변조 샘플 검증 실패 확인 |
| 28 | 인증서 검증 누락 | `verify=False` / `rejectUnauthorized:false` | hostname/chain/CRL 검증 유지 | 중간자 시나리오 테스트 |
| 29 | 쿠키 정보노출 | `resp.set_cookie("token", token)` (플래그 없음) | Secure+HttpOnly+SameSite 강제, 민감정보 비저장 | Set-Cookie 헤더 점검 |
| 30 | 주석 정보노출 | `// prod db password: P@ssw0rd` | 배포 전 민감주석 제거, 저장소 스캔 | gitleaks/truffleHog 스캔 결과 |
| 31 | 솔트 없는 해시 | `sha256(password)` | bcrypt/Argon2/PBKDF2 (salt+work factor) | 동일 비밀번호 해시 비교 테스트 |
| 32 | 무결성 없는 다운로드 | `curl "$URL" \| sh` | sha256/서명 검증 후 실행 | 변조 파일 검증 실패 확인 |
| 33 | 인증시도 제한 없음 | 로그인 무제한 재시도 허용 | rate limit, 지연, 계정잠금, 탐지 로그 | 대량 시도 시 차단 동작 확인 |

### C. 시간 및 상태 (34~35)

| ID | 약점명 | 취약 패턴 (❌ 금지) | 필수 통제 | 검증 증적 |
|---|---|---|---|---|
| 34 | TOCTOU 경쟁조건 | `if exists(path): open(path)` (별도 연산) | 원자적 API/락/트랜잭션 | 동시성 재현 테스트 |
| 35 | 무한 반복/재귀 | `while True: work()` (외부입력 의존) | 반복 상한, 타임아웃, 취소 토큰 | 악성 입력으로 종료성 검증 |

### D. 에러처리 (36~38)

| ID | 약점명 | 취약 패턴 (❌ 금지) | 필수 통제 | 검증 증적 |
|---|---|---|---|---|
| 36 | 오류메시지 정보노출 | `res.json({ error: err.stack })` | 사용자 메시지 일반화, 상세는 내부 로그 | 오류 유도 시 응답 본문 점검 |
| 37 | fail-open 처리 | `except Exception: pass` (인증 모듈) | fail-safe(기본 거부), 예외 시 abort(403) | 장애 주입 테스트 |
| 38 | 광범위 예외 무시 | `catch (Exception e) {}` | 예외 유형별 처리, 재시도/중단 정책 | 로그/알람 연계 확인 |

### E. 코드오류 (39~43)

| ID | 약점명 | 취약 패턴 (❌ 금지) | 필수 통제 | 검증 증적 |
|---|---|---|---|---|
| 39 | Null Pointer 역참조 | `return user.getEmail()` (null 체크 없음) | null guard, Optional/null-safe API | null 입력 단위테스트 |
| 40 | 자원 해제 누락 | `f = open(path)` (close 없음) | with/try-finally/try-with-resources | FD/커넥션 누수 모니터링 |
| 41 | 해제 후 사용 | `free(p); strcpy(p, input)` | 수명주기 분리, 상태 검사 | 정적분석/ASAN |
| 42 | 미초기화 변수 | `int rc; if(ok) rc=0; return rc;` | 선언 시 초기화 (`int rc = -1`) | 컴파일 경고 0, 분기 테스트 |
| 43 | 비신뢰 역직렬화 | `pickle.loads(untrusted)` | JSON + 스키마 검증(pydantic/ajv) | gadget payload 차단 테스트 |

### F. 캡슐화 (44~47)

| ID | 약점명 | 취약 패턴 (❌ 금지) | 필수 통제 | 검증 증적 |
|---|---|---|---|---|
| 44 | 세션 정보노출 | `repo.find_by_user(request.args["uid"])` | 세션 재생성, 사용자-리소스 매핑 재검증 | 세션 고정 공격 테스트 |
| 45 | 디버그 코드 잔존 | `/debug`, `?admin=true` 무조건 노출 | 운영 빌드에서 제거, profile/feature flag | 운영 아티팩트 스캔 |
| 46 | Private 배열 직접 반환 | `return this.roles` (mutable 참조) | 방어적 복사, 불변 컬렉션 반환 | 반환값 수정 시 내부상태 불변 확인 |
| 47 | Public 데이터 직접 대입 | `self._items = items` (참조 공유) | 복사 후 저장 (`self._items = list(items)`) | 외부 객체 변경 전파 여부 테스트 |

### G. API 오용 (48~49)

| ID | 약점명 | 취약 패턴 (❌ 금지) | 필수 통제 | 검증 증적 |
|---|---|---|---|---|
| 48 | DNS 단독 보안결정 | `if host.endswith(".corp.local"): allow()` | IP·인증·정책 기반 다중 검증 | DNS 변조/재바인딩 테스트 |
| 49 | 취약 API 사용 | `strcpy`, `sprintf(dst, input)`, MD5 | 안전 대체 API, 금지목록 리뷰 점검 | 금지 API 스캔 결과 |

---

## 3) 수동검증 필수 항목

정적 도구만으로 판정 불가 → 반드시 수동 검토:

- **ID 18** 인증 없는 중요기능 (우회 엔드포인트 존재 여부)
- **ID 19** 부적절한 인가 (BOLA - 타인 리소스 접근)
- **ID 20** 자원 권한 과다 (IAM 실제 권한 범위)
- **ID 22** 중요정보 평문 (무엇이 중요정보인지 맥락 판단)
- **ID 4** Stored XSS (DB 값의 입력 기원 추적)
- **ID 29** 쿠키 정보노출 (민감 쿠키 식별)

---

## 4) PR/커밋 리뷰 체크리스트

```
□ 외부입력이 SQL·명령·경로·URL·HTML Sink로 직접 흐르지 않는가?
□ eval/exec/pickle/역직렬화에 외부입력이 도달하지 않는가?
□ 모든 중요 엔드포인트에 인증 미들웨어가 적용되어 있는가?
□ 권한 판단이 서버 DB/세션 기반인가? (req.body.isAdmin 등 금지)
□ 비밀값이 코드·주석·로그에 없는가?
□ 취약 암호 알고리즘(MD5/SHA1/DES/RC4)을 사용하지 않는가?
□ TLS 검증이 비활성화되어 있지 않은가? (verify=False 등)
□ 예외처리가 fail-safe(기본 거부)인가?
□ 파일·소켓·커넥션이 with/try-finally로 반드시 해제되는가?
□ 쿠키에 Secure+HttpOnly+SameSite가 설정되어 있는가?
□ 디버그 엔드포인트·백도어 플래그가 없는가?
```

---

## 5) 점검 결과 기록 템플릿

```md
### [KISA2021-{ID}] {약점명}
- 대상 파일: `path/to/file.ext:line`
- 입력 Source:
- 위험 Sink:
- 적용 Sanitizer:
- 악용 시나리오:
- 판정: 취약 | 보완필요 | 양호 | 해당없음
- 개선 코드/커밋:
- 재검증 결과:
```
