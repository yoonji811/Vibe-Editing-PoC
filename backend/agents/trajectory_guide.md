# Trajectory 저장 구조 및 동작 가이드

> 실제 검증 기준: 2026-04-23, 서버 기동 후 3회 편집 세션으로 확인된 내용

---

## 1. 저장 위치 및 백엔드 선택

| 환경 | 저장소 | 결정 기준 |
|------|--------|----------|
| 로컬 개발 | `./data/trajectories/{session_id}.json` | `DATABASE_URL` 환경변수 없을 때 |
| 프로덕션 (Railway) | PostgreSQL `trajectories` 테이블 | `DATABASE_URL` 환경변수 있을 때 |

```
backend/data/trajectories/
└── 910dccb8-b420-4c9f-b089-357bfa363b23.json   ← 세션 1개 = 파일 1개
```

---

## 2. 이벤트 흐름 (실제 저장 순서)

```
POST /api/session/new
  └─ [image_upload 이벤트 저장]

POST /api/edit/{session_id}  (반복 n회)
  ├─ [chat_input 이벤트 저장]    ← 사용자 입력 즉시 기록
  └─ [edit_applied 이벤트 저장]  ← 편집 완료 후 결과 기록
```

한 번의 채팅 편집 = `chat_input` 1개 + `edit_applied` 1개.

---

## 3. 실제 저장된 JSON 구조 (검증됨)

### 3-1. 세션 루트

```json
{
  "session_id": "910dccb8-b420-4c9f-b089-357bfa363b23",
  "user_nickname": "tester_01",
  "created_at": "2026-04-23T01:52:12.107475",
  "updated_at": "2026-04-23T01:53:10.437499",
  "original_image": {
    "filename": "landscape.jpg",
    "size_bytes": 2528,
    "width": 400,
    "height": 300,
    "mime_type": "image/jpeg"
  },
  "events": [ ... ]
}
```

### 3-2. image_upload 이벤트

```json
{
  "event_id": "e7270ad6-cdc2-4f77-9bde-147bf68543fd",
  "timestamp": "2026-04-23T01:52:12.107475",
  "type": "image_upload",
  "payload": {
    "filename": "landscape.jpg",
    "size_bytes": 2528,
    "width": 400,
    "height": 300
    // 나머지 필드는 null (편집 전이므로)
  }
}
```

### 3-3. chat_input 이벤트

```json
{
  "event_id": "a2455377-4eee-434a-a1a3-67e1ae6d48a4",
  "timestamp": "2026-04-23T01:52:14.166103",
  "type": "chat_input",
  "payload": {
    "user_text": "따뜻한 분위기로 만들어줘"
    // 나머지 null — 사용자 입력만 기록, 아직 파이프라인 실행 전
  }
}
```

### 3-4. edit_applied 이벤트 (핵심)

```json
{
  "event_id": "df8a1407-183b-4d42-9ac5-5071a4edff22",
  "timestamp": "2026-04-23T01:52:38.510484",
  "type": "edit_applied",
  "payload": {

    // ── 기본 정보 ──────────────────────────────────────────
    "user_text": "따뜻한 분위기로 만들어줘",
    "intent_classified": "The user wants to create a warm atmosphere in the image.",
    "engine_used": "agent",
    "params": { "highlights_hue": 35, "shadows_hue": 25, ... },  // 첫 번째 step params
    "result_image_hash": "940613ecae9687e7",                     // SHA-256 앞 16자
    "image_url": null,                                            // Cloudinary 미설정 시 null
    "latency_ms": 24344,
    "error": null,

    // ── Plan JSON (Planner 출력) ────────────────────────────
    "plan": {
      "plan_id": "123e4567-e89b-12d3-a456-426614174000",  // ⚠️ 고정값 버그 (아래 참고)
      "intent": "The user wants to create a warm atmosphere in the image.",
      "confidence": 0.95,
      "steps": [
        {
          "step_id": "s1",
          "tool_name": "split_toning",
          "params": { "highlights_hue": 35, "shadows_hue": 25, "highlights_saturation": 40, ... },
          "depends_on": [],
          "rationale": "To create a warm atmosphere, split_toning is applied... VLM analysis shows 'Neutral' color temperature..."
        },
        {
          "step_id": "s2",
          "tool_name": "saturation",
          "params": { "scale": 1.15 },
          "depends_on": ["s1"],
          "rationale": "..."
        }
      ],
      "unmet_requirements": []
    },

    // ── Validator 결과 ─────────────────────────────────────
    "validator_verdict": {
      "approved": true,
      "quality_score": 0.9,
      "reasons": [],
      "feedback_for_planner": ""
    },
    "validator_attempts": 2,  // 1차 거절 후 재시도해서 2번째에 승인된 경우

    // ── V2: VLM 이미지 분석 결과 ──────────────────────────
    "source_image_context": {
      "semantic_understanding": {
        "scene_type": "abstract",
        "mood": "calm",
        "subjects": [],
        "objects": []
      },
      "physical_properties": {
        "noise_level": "Low",
        "sharpness": "Sharp",
        "blur": "None",
        "resolution_quality": "High"
      },
      "colorimetry_and_lighting": {
        "dominant_colors": ["Green"],
        "color_temperature": "Neutral",
        "contrast": "Low",
        "brightness": "Normal",
        "lighting_direction": "ambient"
      },
      "artistic_style": {
        "current_style": "flat",
        "genre": "abstract",
        "mood_keywords": ["minimalist", "uniform", "simple", "calm"]
      }
    },

    // ── 툴 실행 로그 (step별 성공/실패) ───────────────────
    "orchestrator_step_logs": [
      {
        "step_id": "s1",
        "tool_name": "split_toning",
        "params": { "highlights_hue": 35, ... },
        "status": "success",
        "error": null,
        "latency_ms": 7
      },
      {
        "step_id": "s2",
        "tool_name": "saturation",
        "params": { "scale": 1.15 },
        "status": "success",
        "error": null,
        "latency_ms": 2
      }
    ],

    // ── 피드백 (POST /api/feedback 호출 시 채워짐) ─────────
    "satisfaction_score": null,  // thumbs_up → 1.0, thumbs_down → -1.0
    "feedback_type": null        // "explicit" | "implicit"
  }
}
```

---

## 4. 필드별 저장 여부 체크리스트

| 필드 | 저장 여부 | 채워지는 시점 | 비고 |
|------|----------|-------------|------|
| `user_text` | ✅ | 편집 즉시 | chat_input + edit_applied 둘 다 |
| `intent_classified` | ✅ | 편집 완료 | plan.intent 값 |
| `engine_used` | ✅ | 편집 완료 | 항상 "agent" |
| `params` | ✅ | 편집 완료 | 첫 번째 step의 params만 |
| `result_image_hash` | ✅ | 편집 완료 | SHA-256 앞 16자 |
| `image_url` | ✅/null | 편집 완료 | Cloudinary 설정 시 URL, 아니면 null |
| `latency_ms` | ✅ | 편집 완료 | 전체 파이프라인 소요 시간 |
| `plan` | ✅ | 편집 완료 | 전체 Plan JSON (steps, rationale 포함) |
| `validator_verdict` | ✅ | 편집 완료 | approved, quality_score, attempts |
| `validator_attempts` | ✅ | 편집 완료 | 몇 번 만에 승인됐는지 |
| `source_image_context` | ✅ | 편집 완료 | VLM 분석 결과 (V2 신규) |
| `orchestrator_step_logs` | ✅ | 편집 완료 | step별 성공/실패/latency |
| `satisfaction_score` | 🕐 지연 | 피드백 수신 시 | POST /api/feedback/{session_id} |
| `feedback_type` | 🕐 지연 | 피드백 수신 시 | "explicit" \| "implicit" |
| `model_used` | ❌ 미구현 | - | 항상 null, 코드에서 채우지 않음 |
| `quality_verdict` | ❌ 미구현 | - | QualityCheckerAgent 미연결 |

---

## 5. 알려진 문제

### ① plan_id 고정값 버그
**현상**: 모든 edit_applied 이벤트의 `plan.plan_id`가 동일한 UUID 사용
```
"plan_id": "123e4567-e89b-12d3-a456-426614174000"  ← Gemini가 스키마 예시값 그대로 반환
```
**원인**: `planner.py`의 `_SYSTEM` 프롬프트 스키마에 예시 UUID가 없음에도 Gemini 모델이
학습 데이터에서 본 RFC UUID 예시(`123e4567-...`)를 반환함.
`planner.py`의 자기검사 로직 `if not raw.get("plan_id"): raw["plan_id"] = str(uuid.uuid4())`이
plan_id가 존재하면 덮어쓰지 않으므로 고정값이 통과됨.

**수정 방법**:
```python
# planner.py — generate_plan() 마지막 부분
# 현재:
if not raw.get("plan_id"):
    raw["plan_id"] = str(uuid.uuid4())

# 수정: 항상 새 UUID로 덮어쓰기
raw["plan_id"] = str(uuid.uuid4())
```

### ② is_correction trajectory 미기록
**현상**: Orchestrator가 `is_correction=True`를 감지해도 trajectory에 저장 안 됨.
**영향**: Memory Agent의 `batch_index_from_trajectory`가 보정 케이스 구분 불가.
**수정 방법**: `edit.py`의 `edit_applied` 이벤트에 `is_correction` 필드 추가 필요
(현재 `TrajectoryEventPayload`에 해당 필드 없음).

### ③ 중복 서버 인스턴스 문제 (개발 환경)
`uvicorn main:app --reload` 실행 시 워커 프로세스가 분리돼 ChromaDB lazy init이
각 프로세스마다 독립적으로 일어남. 새 데이터 색인 후 서버 재시작 전까지 RAG 검색에서
해당 케이스가 보이지 않을 수 있음. 프로덕션(단일 프로세스)에서는 해당 없음.

---

## 6. 학습 데이터로 활용 시 추출 쿼리

```python
# 고품질 학습 샘플 필터링 조건:
# - type == "edit_applied"
# - satisfaction_score >= 0.8  (피드백 수신된 것)
# - plan.steps 비어있지 않음
# - source_image_context 존재 (VLM 분석됨)

from services.trajectory_store import load_trajectory

def get_training_samples(session_id: str):
    traj = load_trajectory(session_id)
    return [
        e for e in traj.events
        if e.type == "edit_applied"
        and (e.payload.satisfaction_score or 0) >= 0.8
        and e.payload.plan
        and e.payload.source_image_context
    ]
```

---

## 7. 저장 트리거 정리

| API 엔드포인트 | 저장 시점 | 저장 내용 |
|---------------|----------|----------|
| `POST /api/session/new` | 즉시 | image_upload 이벤트 |
| `POST /api/edit/{session_id}` | 편집 시작 시 + 완료 시 | chat_input + edit_applied |
| `POST /api/feedback/{session_id}` | 즉시 | 기존 edit_applied에 satisfaction_score 갱신 |
| `POST /api/trajectory/{session_id}/end` | 즉시 | 인메모리 → 디스크 강제 flush |
| `POST /api/trajectory/{session_id}/save` | 즉시 | image_saved 이벤트 추가 |
| `POST /api/agent/edit` (V2 전용) | **없음** | ⚠️ trajectory 저장 안 됨 |

> **주의**: `/api/agent/edit` 직접 호출은 trajectory를 저장하지 않음.
> 프론트엔드는 항상 `/api/edit/{session_id}`를 통해 편집해야 함.
