# OMC (oh-my-claudecode) 설치 & 사용 가이드

> 출처: https://github.com/Yeachan-Heo/oh-my-claudecode (현재 v4.11.x 기준)

---

## 설치

### 방법 A — Claude Code 플러그인 마켓플레이스 (권장)
```
# Claude Code 세션 안에서 실행
/plugin marketplace add https://github.com/Yeachan-Heo/oh-my-claudecode
/plugin install oh-my-claudecode
```

### 방법 B — npm 직접 설치
```bash
# 패키지 이름 주의: 브랜드명은 oh-my-claudecode지만 npm 패키지명은 다름
npm install -g oh-my-claude-sisyphus@latest
```

---

## 최초 설정 (설치 후 딱 한 번)

```
# Claude Code 세션 안에서 실행
/oh-my-claudecode:omc-setup
```

- 새 프로젝트마다 로컬 설정이 필요하면: `/oh-my-claudecode:omc-setup --local`
- 플러그인 업데이트 후에도 반드시 재실행해야 최신 CLAUDE.md가 적용됨

---

## 이 프로젝트에서 시작하는 법

```bash
# 1. 프로젝트 폴더 생성 & 파일 배치
mkdir image-editor && cd image-editor
# CLAUDE.md, .env.example, requirements.txt 복사

# 2. .env 세팅
cp .env.example .env
# .env 열고 GEMINI_API_KEY 입력

# 3. Claude Code 실행
claude
```

Claude Code가 열리면:
```
autopilot: CLAUDE.md를 읽고 Phase 1부터 시작해줘
```

---

## Magic Keywords — 외울 필요 없이 자연어로

| 키워드 | 효과 | 예시 |
|--------|------|------|
| `autopilot` | 아이디어 → 완성 코드까지 완전 자율 실행 | `autopilot: build a REST API` |
| `ralph` | 완료될 때까지 멈추지 않는 루프 (ultrawork 자동 포함) | `ralph: fix the auth bug` |
| `ulw` | 최대 병렬 실행 (ultrawork) | `ulw refactor the API` |
| `ralplan` | 합의 도달까지 반복 플래닝 | `ralplan this feature` |
| `plan` | 요구사항 인터뷰 후 플래닝 | `plan the new endpoints` |
| `team` | N개 에이전트 동시 실행 | `team 3:executor fix all errors` |

> `ralph`를 쓰면 ultrawork가 자동 포함되므로 둘을 같이 쓸 필요 없음

---

## 세션 내 슬래시 커맨드

```
/oh-my-claudecode:omc-setup            # 환경 설정 (최초 1회)
/oh-my-claudecode:omc-setup --local    # 프로젝트별 로컬 설정
/autopilot "할 일 설명"                # 자율 실행
/team 3:executor "할 일"               # 에이전트 3개로 병렬 실행
/oh-my-claudecode:omc-help             # 도움말
```

---

## 터미널 CLI 커맨드 (npm 설치 시)

```bash
omc                      # 전체 대시보드 (통계 + 에이전트 + 비용)
omc stats                # 토큰 사용량 & 비용
omc agents               # 현재 에이전트 상태
omc hud                  # HUD 상태바 렌더링
omc team status <name>   # 특정 팀 잡 상태 확인
```

---

## 19개 전문 에이전트 (자동 라우팅)

| 카테고리 | 에이전트 |
|----------|---------|
| 빌드/분석 | explore, analyst, planner, architect, debugger, executor, code-simplifier |
| 리뷰 | security-reviewer, code-reviewer, critic |
| 전문 도메인 | document-specialist, test-engineer, designer, writer, qa-tester, scientist, git-master, tracer |

복잡한 태스크는 Opus(아키텍처/분석), Sonnet(일반), Haiku(단순 조회) 순으로 자동 모델 라우팅.

---

## 로컬 개발 실행

```bash
# 터미널 1 — 백엔드
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# 터미널 2 — 프론트엔드
cd frontend
npm install
npm run dev

# 접속: http://localhost:5173
```

---

## 배포 (Railway + Vercel)

### 백엔드 → Railway
```bash
npm install -g @railway/cli
railway login
cd backend
railway init
railway up
# Railway 대시보드 > Variables에서 환경변수 설정:
#   GEMINI_API_KEY=...
#   CORS_ORIGINS=https://your-app.vercel.app
```

### 프론트엔드 → Vercel
```bash
npm install -g vercel
cd frontend
vercel
# Vercel 대시보드 > Settings > Environment Variables에서:
#   VITE_API_URL=https://your-backend.railway.app
```

테스터에게 Vercel URL 공유 → 모바일 브라우저에서 바로 사용 가능

---

## 빠른 로컬 터널 (ngrok)

```bash
ngrok http 8000
# 출력된 URL을 frontend/.env의 VITE_API_URL에 설정
```

---

## Trajectory 데이터 확인

```bash
ls backend/data/trajectories/
cat backend/data/trajectories/{session_id}.json | python -m json.tool
```

---

## 업데이트

```bash
# 플러그인 업데이트
/plugin marketplace update omc

# npm 업데이트
npm update -g oh-my-claude-sisyphus

# 업데이트 후 반드시 재설정
/oh-my-claudecode:omc-setup
```
