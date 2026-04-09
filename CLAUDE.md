# Image Editor Web — Claude Code Project Guide

## 프로젝트 개요

사용자가 이미지를 업로드하고 채팅 인터페이스로 편집할 수 있는 웹 애플리케이션.
OpenCV 기반 전통적 편집 + Gemini API 기반 생성형 편집을 하나의 채팅창에서 처리.
모든 사용자 행동(trajectory)을 JSON으로 기록해 추후 학습 데이터로 활용.

---

## 기술 스택

| 레이어 | 선택 | 이유 |
|--------|------|------|
| Frontend | React + Vite + TailwindCSS | 모바일 대응, 빠른 개발 |
| Backend | FastAPI (Python) | OpenCV, Pillow 연동 용이 |
| Image Processing | OpenCV, Pillow | 전통적 편집 |
| AI Routing / LLM | Gemini 2.5 Flash (`gemini-2.5-flash`) | 사용자 의도 파악, 세션 컨텍스트 추론 |
| AI Image Editing | Gemini 2.5 Flash Image (`gemini-2.5-flash-image`) | 생성형 이미지 편집 |
| Trajectory Storage | JSON files (→ 추후 DB 마이그레이션 가능) | 단순, 이식성 좋음 |
| 배포 | Railway (백엔드) + Vercel (프론트) | 무료 티어, 모바일 접근 용이 |

---

## 디렉토리 구조

```
image-editor/
├── CLAUDE.md                  # 이 파일
├── .env.example               # 환경변수 템플릿
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── index.html
│   └── src/
│       ├── App.tsx
│       ├── components/
│       │   ├── ImageUploader.tsx   # 드래그앤드롭 업로드
│       │   ├── ChatPanel.tsx       # 채팅 UI
│       │   ├── ImageViewer.tsx     # 현재/이전 이미지 비교
│       │   └── HistoryBar.tsx      # 세션 내 편집 이력
│       ├── hooks/
│       │   └── useSession.ts       # 세션 상태 관리
│       └── api/
│           └── client.ts           # FastAPI 통신
└── backend/
    ├── requirements.txt
    ├── main.py                     # FastAPI 앱 진입점
    ├── routers/
    │   ├── session.py              # 세션 CRUD
    │   ├── edit.py                 # 편집 엔드포인트
    │   └── trajectory.py          # trajectory 저장/조회
    ├── services/
    │   ├── intent_router.py        # Gemini로 편집 의도 분류
    │   ├── opencv_editor.py        # OpenCV 편집 함수들
    │   └── gemini_editor.py        # Gemini 생성형 편집
    ├── models/
    │   └── schemas.py              # Pydantic 모델
    └── data/
        └── trajectories/           # JSON trajectory 저장소
            └── .gitkeep
```

---

## 핵심 기능 명세

### 1. 세션 관리
- 이미지 업로드 시 `session_id` (UUID) 생성
- 같은 이미지에 대한 모든 채팅은 동일 세션으로 묶임
- 새 이미지 업로드 시 새 세션 시작
- 세션 내 편집 히스토리(텍스트1 → 텍스트2 → ...)를 컨텍스트로 유지

### 2. 채팅 기반 편집 흐름
```
사용자 입력 → intent_router (Gemini) → 의도 분류
                                        ├─ "brightness", "crop", "blur" 등 → opencv_editor
                                        ├─ "remove object", "add element", "style transfer" → gemini_editor
                                        └─ "undo", "save", "history" → 세션 액션
```

### 3. Trajectory 스키마 (`trajectories/{session_id}.json`)
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
      "type": "image_upload | chat_input | edit_applied | image_saved | undo | session_end",
      "payload": {
        "user_text": "배경을 흐리게 해줘",
        "intent_classified": "blur_background",
        "engine_used": "opencv",
        "model_used": null,
        "params": {"ksize": 21},
        "result_image_hash": "sha256...",
        "latency_ms": 340,
        "error": null
      }
    }
  ]
}
```

### 4. OpenCV 편집 기능 목록
- 밝기/대비 조정 (`brightness`, `contrast`)
- 크롭 (`crop`)
- 리사이즈 (`resize`)
- 블러 (`blur`, `gaussian_blur`)
- 흑백 변환 (`grayscale`)
- 회전/뒤집기 (`rotate`, `flip`)
- 색상 필터 (`hue_shift`, `saturation`)
- 샤프닝 (`sharpen`)
- 노이즈 제거 (`denoise`)

### 5. Gemini 모델 사용 구분

| 역할 | 모델 ID | 용도 |
|------|---------|------|
| Intent Router | `gemini-2.5-flash` | 사용자 텍스트 분석 → opencv / gemini_image / 세션액션 분류, 세션 히스토리 컨텍스트 포함 |
| 생성형 이미지 편집 | `gemini-2.5-flash-image` | 이미지 입력 → 편집된 이미지 출력 |

**생성형 편집 기능**: 배경 제거, 객체 제거, 스타일 변환, 인페인팅, 텍스트 추가
**세션 히스토리**: intent_router 호출 시 직전 편집 이력 전체를 system prompt에 포함해 문맥 유지

---

## 환경변수 (`.env`)

```
GEMINI_API_KEY=your_gemini_api_key_here
CORS_ORIGINS=http://localhost:5173,https://your-vercel-app.vercel.app
MAX_IMAGE_SIZE_MB=10
TRAJECTORY_DIR=./data/trajectories
```

---

## 개발 시작 명령어

```bash
# 1. 백엔드
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# 2. 프론트엔드 (새 터미널)
cd frontend
npm install
npm run dev
```

---

## 배포 전략 (모바일 테스터용)

### 옵션 A — Railway + Vercel (권장, 무료)
1. **백엔드 → Railway**
   ```bash
   # Railway CLI 설치
   npm install -g @railway/cli
   railway login
   cd backend
   railway init
   railway up
   # GEMINI_API_KEY 환경변수를 Railway 대시보드에서 설정
   ```
2. **프론트엔드 → Vercel**
   ```bash
   npm install -g vercel
   cd frontend
   vercel
   # VITE_API_URL 환경변수를 Railway 백엔드 URL로 설정
   ```
3. 테스터에게 Vercel URL 공유 → 모바일 브라우저에서 바로 사용

### 옵션 B — Render (백엔드+프론트 한 번에, 무료)
- `render.yaml` 작성 후 GitHub 연결, 자동 배포

### 옵션 C — ngrok (로컬 테스트용, 빠름)
```bash
ngrok http 8000  # 백엔드 터널
# 발급된 URL을 프론트의 VITE_API_URL에 설정
```

---

## 구현 순서 (Claude Code 작업 단계)

```
Phase 1 — 뼈대
  1. 프로젝트 스캐폴딩 (디렉토리, 패키지 설치)
  2. FastAPI 기본 앱 + 헬스체크 엔드포인트
  3. React 기본 앱 + 이미지 업로드 컴포넌트

Phase 2 — 핵심 기능
  4. 세션 생성/관리 API
  5. OpenCV 편집 서비스 구현
  6. Gemini intent_router 구현
  7. 채팅 UI + 편집 결과 표시

Phase 3 — 생성형 편집
  8. Gemini 생성형 편집 서비스
  9. 세션 히스토리 컨텍스트 연동

Phase 4 — Trajectory
  10. 모든 이벤트 JSON 저장 미들웨어
  11. trajectory 조회 API (디버깅용)

Phase 5 — 배포
  12. Docker화 (선택)
  13. Railway + Vercel 배포
  14. 모바일 UI 최종 점검
```

---

## 주의사항 / 제약

- 이미지는 서버 메모리/임시 디렉토리에서만 처리, 영구 저장 안 함 (trajectory에는 메타데이터만)
- 편집된 이미지 결과는 base64로 프론트에 전달
- 세션당 편집 이력 최대 50개 (메모리 관리)
- Gemini API 무료 티어 RPM 제한 고려 → 클라이언트 사이드 debounce 적용
- 모바일 대응: 이미지 업로드는 카메라 + 갤러리 모두 지원 (`accept="image/*"`)

---

## 참고 링크

- [Gemini API Docs](https://ai.google.dev/gemini-api/docs)
- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [Railway Docs](https://docs.railway.app/)
- [Vercel Docs](https://vercel.com/docs)
