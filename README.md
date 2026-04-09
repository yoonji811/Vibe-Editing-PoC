# Vibe Editor PoC

채팅 인터페이스로 이미지를 편집하는 웹 애플리케이션.  
OpenCV 기반 전통적 편집 + Gemini API 생성형 편집을 하나의 입력창에서 처리하고, 모든 사용자 행동을 trajectory로 기록합니다.

---

## 기술 스택

| 레이어 | 기술 |
|--------|------|
| Frontend | React + Vite + TailwindCSS |
| Backend | FastAPI (Python) |
| 이미지 처리 | OpenCV, Pillow |
| Intent 분류 | Gemini 2.5 Flash |
| 생성형 편집 | Gemini 2.5 Flash Image (이미지 출력) |
| Trajectory 저장 | PostgreSQL (Railway) / JSON 파일 (로컬) |
| 배포 | Railway (백엔드) + Vercel (프론트엔드) |

---

## 프로젝트 구조

```
.
├── backend/
│   ├── main.py                      # FastAPI 앱 진입점
│   ├── Procfile                     # Railway 배포 설정
│   ├── nixpacks.toml                # Railway 빌드 설정
│   ├── requirements.txt
│   ├── routers/
│   │   ├── session.py               # 세션 생성/조회
│   │   ├── edit.py                  # 편집 요청 처리
│   │   └── trajectory.py           # trajectory 조회/export
│   ├── services/
│   │   ├── intent_router.py         # Gemini로 편집 의도 분류
│   │   ├── opencv_editor.py         # OpenCV 편집 함수
│   │   ├── gemini_editor.py         # Gemini 생성형 편집
│   │   └── trajectory_store.py     # PostgreSQL / JSON 저장
│   ├── models/schemas.py            # Pydantic 스키마
│   ├── store.py                     # 인메모리 세션 저장소
│   └── data/trajectories/          # 로컬 JSON 저장 경로
├── frontend/
│   └── src/
│       ├── App.tsx
│       ├── components/
│       │   ├── ImageUploader.tsx
│       │   ├── ImageViewer.tsx
│       │   ├── HistoryBar.tsx       # 편집 이력 썸네일 사이드바
│       │   └── ChatPanel.tsx        # 명령 입력창
│       ├── hooks/useSession.ts      # 세션 상태 관리
│       └── api/client.ts           # FastAPI 통신
└── sync_trajectories.py            # Railway DB → 로컬 자동 동기화
```

---

## 로컬 실행

### 사전 준비

`.env` 파일 생성 (`.env.example` 참고):

```
GEMINI_API_KEY=your_gemini_api_key_here
CORS_ORIGINS=http://localhost:5173
```

### 백엔드

```bash
cd backend
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### 프론트엔드

```bash
cd frontend
npm install
npm run dev
```

브라우저에서 **http://localhost:5173** 접속

---

## 편집 흐름

```
사용자 입력
  └─ Gemini intent_router → 의도 분류
        ├─ opencv      → 밝기/대비/크롭/블러/흑백/회전 등
        ├─ gemini_generative → 배경 제거, 객체 제거, 스타일 변환 등
        └─ session_action → undo / reset
```

### OpenCV 편집 기능

`brightness` `contrast` `crop` `resize` `blur` `grayscale` `rotate` `flip` `hue_shift` `saturation` `sharpen` `denoise`

### Gemini 생성형 편집

배경 제거, 객체 제거, 스타일 변환, 인페인팅, 텍스트 추가

---

## 배포 구성

| 서비스 | URL |
|--------|-----|
| Backend (Railway) | `https://vibe-backend-production-55a7.up.railway.app` |
| Frontend (Vercel) | `https://frontend-six-rust-44.vercel.app` |
| DB (Railway PostgreSQL) | Railway 대시보드 → PostgreSQL 서비스 |

### 백엔드 재배포

```bash
cd backend
railway up --detach
```

### 프론트엔드 재배포

```bash
cd frontend
npm run build
vercel --prod
```

---

## Trajectory

### 스키마

```json
{
  "session_id": "uuid",
  "created_at": "ISO8601",
  "updated_at": "ISO8601",
  "original_image": {
    "filename": "photo.jpg",
    "size_bytes": 204800,
    "width": 1920,
    "height": 1080,
    "mime_type": "image/jpeg"
  },
  "events": [
    {
      "event_id": "uuid",
      "timestamp": "ISO8601",
      "type": "image_upload | chat_input | edit_applied | image_saved",
      "payload": {
        "user_text": "배경을 흐리게 해줘",
        "intent_classified": "blur_background",
        "engine_used": "opencv",
        "params": {"ksize": 21},
        "result_image_hash": "sha256...",
        "latency_ms": 340
      }
    }
  ]
}
```

### 로컬 자동 동기화

Railway PostgreSQL 데이터를 로컬 `backend/data/trajectories/`에 세션별 JSON으로 저장:

```bash
# 1회 동기화
python sync_trajectories.py

# 30초마다 자동 동기화
python sync_trajectories.py --watch 30
```

### 전체 Export API

```bash
curl https://vibe-backend-production-55a7.up.railway.app/api/trajectory/export/all \
  -o trajectories.json
```

---

## 환경변수

| 변수 | 설명 | 필수 |
|------|------|------|
| `GEMINI_API_KEY` | Google AI Studio API 키 | ✅ |
| `CORS_ORIGINS` | 허용할 origin (쉼표 구분) | ✅ |
| `DATABASE_URL` | PostgreSQL 연결 URL (Railway 자동 주입) | 배포 시 |
| `VITE_API_URL` | 백엔드 URL (프론트엔드 빌드 시 사용) | 배포 시 |
| `MAX_IMAGE_SIZE_MB` | 최대 이미지 크기 (기본: 10) | ❌ |
