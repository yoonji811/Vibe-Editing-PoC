# 현재 동작 파이프라인 (as-is)

작성 기준: `dev/0423_gs` 브랜치 실제 코드  
목적: 피드백을 위한 현황 기록. 설계 의도(CLAUDE_override_v2.md)와 다른 부분은 **[GAP]** 으로 표시.

---

## 1. 전체 흐름 다이어그램

```
[Frontend]
  └─ POST /api/edit/{session_id}          ← 메인 편집 요청
       │
       ▼
[routers/edit.py]
  ├─ undo / reset 키워드 → session.edit_history 직접 조작 (파이프라인 우회)
  └─ 일반 요청
       │  input: user_text, input_image_b64 (optional)
       ▼
[OrchestratorAgent.process_edit()]        ← agents/orchestrator.py
  │
  ├─ Step 1: Hydration
  │    trajectory DB/file → in-memory edit tree 복구
  │
  ├─ Step 2: 베이스 이미지 결정
  │    _image_store[edit_id] 우선, 없으면 input_image_b64
  │
  ├─ Step 3: Next Prompt Analyzer (정규식)
  │    → is_correction: bool
  │    → previous_failed_attempts: List (교정 시 직전 plan 툴/파라미터 목록)
  │
  ├─ Step 4: VLM Analyzer
  │    Gemini vision → source_image_context (구조화된 이미지 분석 JSON)
  │    [Memory Agent 입력용 + trajectory 저장용 — Planner 전달 안 함]
  │
  ├─ Step 5: Memory Agent (ChromaDB RAG)
  │    user_text + source_image_context → embedding → Top-K 유사 성공 사례
  │    → retrieved_cases: List
  │
  ├─ Step 6: Planner
  │    retrieved_cases + previous_failed_attempts + ancestor_chain → Plan JSON
  │
  ├─ Step 7: Validator (현재 use_validator=False → 항상 skip)
  │
  ├─ Step 8: Plan 실행 (Tool.run, topological order)
  │    → result_image (np.ndarray), step_logs
  │
  └─ Step 9: Edit Node 저장 (in-memory tree)
       └─ return dict
            │
            ▼
[routers/edit.py (후처리)]
  ├─ session.current_image_b64 업데이트
  ├─ session.edit_history 추가
  ├─ Cloudinary 업로드 (non-fatal, 실패해도 계속)
  └─ TrajectoryEvent("edit_applied") append → trajectory_store.save()
```

---

## 2. 진입점 (API Endpoints)

### 메인 편집 엔드포인트
- **파일**: `routers/edit.py`
- **경로**: `POST /api/edit/{session_id}`
- **호출 주체**: Frontend (`useSession.ts`)
- **Input**:
  ```json
  {
    "user_text": "따뜻한 분위기로 바꿔줘",
    "input_image_b64": "<base64 | null>"
  }
  ```
  - `input_image_b64`: 현재 뷰어에서 보고 있는 이미지 (null이면 session.current_image_b64 사용)
- **Output**:
  ```json
  {
    "session_id": "...",
    "event_id": "...",
    "result_image_b64": "<base64>",
    "chat_message": "편집 완료 메시지",
    "intent": "...",
    "engine": "agent",
    "operation": "첫번째 툴 이름",
    "params": { ... },
    "latency_ms": 1234,
    "timing_ms": { "vlm": 300, "memory": 50, "planner": 800, "validator": 0, "tool_exec": 20, "total": 1234 }
  }
  ```

### 보조 에이전트 엔드포인트 (직접 Orchestrator 호출)
- **파일**: `agents/router.py`
- **경로**: `POST /api/agent/edit`, `POST /api/agent/edit/{session_id}`
- **주 용도**: 테스트/디버그 (프론트엔드는 사용 안 함)
- **차이점**: trajectory 저장 없음, 세션 store 없음

---

## 3. 컴포넌트별 상세

### 3-0. Session Store (`store.py` + `models/schemas.py`)

**역할**: 요청 간 이미지/채팅 상태를 메모리에 유지

**SessionState 주요 필드**:
| 필드 | 타입 | 설명 |
|------|------|------|
| `session_id` | str | UUID |
| `current_image_b64` | str | 현재 편집 결과 이미지 |
| `edit_history` | List[str] | base64 이미지 스냅샷 목록 (max 50) |
| `chat_history` | List[ChatMessage] | 사용자/어시스턴트 메시지 |
| `trajectory` | Trajectory | 영구 저장용 이벤트 로그 |

**주의**: 서버 재시작 시 `edit_history`, `chat_history` 소멸. Trajectory만 DB에 영구 저장됨.

---

### 3-1. Next Prompt Analyzer (`orchestrator.py:_detect_correction`)

**역할**: 사용자 텍스트가 교정 요청인지 판단

**Input**: `prompt: str`

**Output**: `is_correction: bool`

**동작**: 정규식 패턴 매칭
```
아니|다시|다르게|바꿔|별로|맘에 안|안 좋|너무 (과해|강해|약해|어둡|밝)|
undo|reset|취소|되돌|correction|change it|not right|too much|too little
```

**교정으로 판정 시**: 직전 edit node의 plan에서 `previous_failed_attempts` 추출 (최대 3개 tool+params). Planner에 "이 조합 반복 금지"로 전달.

---

### 3-2. VLM Analyzer (`agents/vlm_analyzer.py`)

**역할**: 현재 이미지의 물리적/의미적 상태를 구조화하여 추출

**Input**: `image_b64: str` (base64, data URI prefix 없음)

**Output** (`source_image_context`):
```json
{
  "semantic_understanding": {
    "subjects": ["person", "mountain"],
    "scene_type": "outdoor",
    "mood": "calm",
    "objects": ["tree", "sky"]
  },
  "physical_properties": {
    "noise_level": "Low",
    "sharpness": "Normal",
    "blur": "None",
    "resolution_quality": "High"
  },
  "colorimetry_and_lighting": {
    "dominant_colors": ["blue", "green"],
    "color_temperature": "Neutral",
    "contrast": "Medium",
    "brightness": "Normal",
    "lighting_direction": "ambient"
  },
  "artistic_style": {
    "current_style": "realistic",
    "genre": "landscape",
    "mood_keywords": ["serene", "natural"]
  }
}
```

**모델**: `gemini-2.0-flash-lite`

**이 결과가 가는 곳**:
1. `MemoryAgent.search_similar(vlm_context=...)` — 더 정확한 RAG 쿼리 벡터 생성
2. `TrajectoryEvent.payload.source_image_context` — DB/파일에 영구 저장 (학습 데이터)
3. Planner에는 **전달하지 않음**

**실패 처리**: 예외 발생 시 `source_image_context = {}` 처리 후 파이프라인 계속 진행 (non-fatal)

---

### 3-3. Memory Agent (`agents/memory_agent.py`)

**역할**: 과거 성공 사례를 ChromaDB에 인덱싱하고, 현재 요청과 유사한 사례를 검색하여 Planner에 전달

**저장소**: ChromaDB (PersistentClient, `./data/chromadb`)  
**컬렉션**: `vibedit_success_cases`  
**임베딩**: ChromaDB 내장 `all-MiniLM-L6-v2`

#### 검색 (Runtime)

**Input**:
- `user_text: str` — 현재 사용자 프롬프트
- `vlm_context: Dict` — VLM 분석 결과
- `is_correction: bool`
- `top_k: int = 3`

**내부 동작**:
1. `_build_document(user_text, vlm_context)` → 임베딩용 복합 텍스트 생성
   ```
   "User Request: {text} | Scene: {scene_type} | Image Mood: {mood} | ..."
   ```
2. ChromaDB `query()` 호출
3. 교정 요청이면 `is_correction_case=true` 필터 우선 적용, 없으면 전체 검색
4. `similarity < 0.25` 결과 제외

**Output** (`retrieved_cases`):
```json
[
  {
    "user_text": "따뜻한 분위기로",
    "similarity": 0.82,
    "satisfaction_score": 0.95,
    "plan": { "steps": [ ... ] }
  }
]
```

#### 인덱싱 (Offline/Async)

**`index_success()`**: `satisfaction_score >= 0.8`인 이벤트만 인덱싱

**`batch_index_from_trajectory(session_id)`**: trajectory에서 qualifying 이벤트 일괄 인덱싱

**[GAP]** 현재 런타임에서 `index_success()`가 자동으로 호출되는 경로가 없음. `feedback` API로 `satisfaction_score`가 업데이트되어도 자동 인덱싱이 트리거되지 않음. 수동 배치 처리 필요.

---

### 3-4. Planner (`agents/planner.py`)

**역할**: 사용자 요청을 Plan JSON으로 변환

**Input**:
| 파라미터 | 타입 | 설명 |
|---------|------|------|
| `prompt` | str | 사용자 원본 텍스트 |
| `ancestor_chain` | List[Dict] | 이전 편집 히스토리 (오래된 순, prompt/intent/tools/params/satisfaction) |
| `image_meta` | Dict | `{width, height, dominant_colors}` — OpenCV로 계산한 기본 메타데이터 |
| `available_tools` | List[Dict] | tool_registry에 등록된 모든 툴 목록 |
| `retrieved_cases` | List[Dict] | Memory Agent RAG 결과 (VLM 정보는 여기에 간접 포함) |
| `previous_failed_attempts` | List[Dict] | 교정 시 반복 금지 tool+params 목록 |
| `feedback` | str | Validator 거부 시 재시도 피드백 |
| `mode` | str | `"prod"` or `"dev"` |

**모델**: `gemini-2.5-flash` (temperature=0.0)

**프롬프트 구성**:
```
[System: 툴 선택 가이드 + 출력 스키마]
[User: 
  ## User Request
  ## Available Tools (카탈로그)
  ## Basic Image Metadata
  ## Reference Success Cases from Memory (RAG)
  ## Edit History
  ## Previous Failed Attempts (교정 시)
  ## Previous Attempt Was Rejected (Validator 거부 시)
]
```

**Output** (`plan`):
```json
{
  "plan_id": "uuid4",
  "intent": "추론된 편집 의도",
  "confidence": 0.9,
  "steps": [
    {
      "step_id": "s1",
      "tool_name": "split_toning",
      "params": { "highlights_hue": 35, "shadows_hue": 25, "saturation": 40 },
      "depends_on": [],
      "produces": null,
      "rationale": "RAG Case 1(82%)에서 동일 요청에 split_toning 성공"
    }
  ],
  "unmet_requirements": []
}
```

**Self-check**: tool_registry에 없는 tool_name은 자동으로 `unmet_requirements`로 이동

---

### 3-5. Validator (`agents/validator.py`)

**역할**: Plan의 파라미터 정합성 및 의도 충족도 검증

**[GAP] 현재 상태**: `routers/edit.py`에서 `use_validator` 파라미터를 `process_edit()`에 전달하지 않아 기본값 `False`로 동작. **항상 bypass.**

`agents/router.py`에서 직접 호출 시 요청 body에 `use_validator: true` 전달하면 활성화 가능.

---

### 3-6. Tool Registry (`agents/tool_registry.py`)

**역할**: 모든 편집 툴을 등록하고 조회하는 중앙 레지스트리

**등록된 툴 분류**:
| 타입 | 툴 |
|------|----|
| `opencv` | brightness, contrast, crop, resize, blur, gaussian_blur, grayscale, rotate, flip, sharpen, denoise, hue_shift, saturation |
| `color_grading` | split_toning, color_grade, color_curves, hsl_selective, apply_lut |
| `generative` | gemini_remove_background, gemini_remove_object, gemini_add_element, gemini_style_transfer, gemini_generative_edit |

**Tool 인터페이스**:
```python
class Tool:
    name: str
    tool_type: str            # "opencv" | "color_grading" | "generative"
    description: str
    params_schema: dict       # JSON Schema

    def run(self, image: np.ndarray, **params) -> Tuple[np.ndarray, Optional[Any]]:
        ...
```

`run()`의 두 번째 반환값은 `produces` 키로 이후 step에 아티팩트를 전달할 때 사용.

---

### 3-7. Plan 실행 (`orchestrator.py:_execute_plan`)

**역할**: Plan의 steps를 topological order로 실행

**Input**: `plan: Dict`, `base_image: np.ndarray`

**동작**:
1. `_topological_sort(steps)` — `depends_on` 기반 정렬
2. 각 step: `params`에서 이전 step이 `produces`한 아티팩트 치환 후 `tool.run()`
3. tool not found → step skip, error 기록
4. tool 실패 → 1회 재시도, 2회 실패 시 error 기록 + 다음 step 계속

**Output**:
- `result_image: np.ndarray`
- `errors: List[str]`
- `step_logs: List[Dict]` — 각 step의 status, latency_ms, error

---

### 3-8. Trajectory Store (`services/trajectory_store.py`)

**역할**: 모든 이벤트를 영구 저장 (SSoT)

**백엔드**: `DATABASE_URL` 환경변수 있으면 PostgreSQL(Railway), 없으면 JSON 파일(`./data/trajectories/`)

**저장 타이밍**: `routers/edit.py`에서 orchestrator 결과 처리 후 `append_event()` 호출

**`edit_applied` 이벤트 페이로드 (`TrajectoryEventPayload`)**:
| 필드 | 값 | 설명 |
|-----|-----|------|
| `user_text` | str | 원본 프롬프트 |
| `intent_classified` | str | plan.intent |
| `engine_used` | "agent" | 항상 agent |
| `params` | Dict | 첫 번째 step의 params |
| `result_image_hash` | str | sha256 앞 16자 |
| `image_url` | str | Cloudinary URL (업로드 성공 시) |
| `latency_ms` | int | 전체 소요 시간 |
| `plan` | Dict | 전체 Plan JSON |
| `orchestrator_step_logs` | List | 각 step 실행 로그 |
| `source_image_context` | Dict | VLM 분석 결과 |
| `is_correction` | bool | 교정 요청 여부 |
| `satisfaction_score` | float | 피드백 API로 사후 업데이트 |
| `feedback_type` | str | "explicit" / "implicit" — 피드백 API로 사후 업데이트 |

**Hydration** (`get_edit_events`): `type == "edit_applied"` 이벤트만 필터링하여 in-memory edit tree 재구성에 사용

---

### 3-9. 피드백 처리 (`routers/feedback.py`)

**역할**: 사용자 thumbs_up/down → trajectory의 `satisfaction_score` 업데이트

**연결**: `trajectory_store.update_event_feedback(session_id, event_id, score, type)`

**[GAP]** 피드백 저장 후 `MemoryAgent.index_success()`가 자동으로 호출되지 않음. ChromaDB 인덱싱은 별도 배치 작업으로만 가능.

---

## 4. In-Memory Edit Tree (Orchestrator 내부)

서버 메모리에 유지되는 편집 트리 구조:

```python
_edit_trees: Dict[session_id, Dict[edit_id, EditNode]]
_latest_edit: Dict[session_id, edit_id]
_image_store: Dict[image_ref, np.ndarray]
```

**EditNode 구조**:
```json
{
  "edit_id": "uuid",
  "parent_edit_id": "uuid | null",
  "session_id": "uuid",
  "prompt": "사용자 입력",
  "plan": { ... },
  "source_image_context": { ... },
  "validator_verdict": null,
  "is_correction": false,
  "image_ref": "uuid (→ _image_store)",
  "created_at": "ISO8601",
  "satisfaction_score": null
}
```

**Hydration 시**: `image_ref = None` (pixel 데이터 없음). ancestor chain 컨텍스트 제공 목적으로만 사용.

**[GAP]** Orchestrator의 edit tree에 사용되는 `edit_id`와 trajectory의 `event_id`는 서로 다른 UUID. 두 시스템 간의 명시적인 연결 고리가 없음.

---

## 5. 타이밍 / 비용

`timing_ms` 필드로 각 단계 소요시간 측정:

| 단계 | 모델/비용 | 예상 레이턴시 |
|------|---------|------------|
| VLM Analyzer | `gemini-2.0-flash-lite` | 300~800ms |
| Memory Agent | ChromaDB 로컬 벡터 검색 | 10~100ms |
| Planner | `gemini-2.5-flash` | 800~2000ms |
| Validator | `gemini-2.5-flash` | (현재 skip) |
| Tool 실행 | 로컬 CPU (OpenCV/NumPy) | 5~50ms |

---

## 6. 현재 코드와 CLAUDE_override_v2.md 간의 GAP 요약

| # | GAP 내용 | 위치 |
|---|---------|------|
| 1 | Validator가 항상 bypass됨 (`use_validator` 미전달) | `routers/edit.py:113` |
| 2 | 피드백 저장 후 Memory Agent 자동 인덱싱 없음 | `routers/feedback.py` |
| 3 | Orchestrator edit_id ↔ Trajectory event_id 연결 안 됨 | `orchestrator.py`, `trajectory_store.py` |
| 4 | `quality_verdict` 필드 항상 `null` (QualityChecker 미사용) | `orchestrator.py:530` |
| 5 | Hydration된 노드는 `image_ref=None` → 서버 재시작 후 첫 편집 시 `image_b64` 필수 | `orchestrator.py:376` |
