# Memory Agent (RAG 기반 피드백 학습 에이전트) 설계서

이 문서는 사용자의 편집 피드백(성공 및 보정 이력)을 거대한 데이터베이스에 축적하고, 새로운 편집 요청 시 이를 검색(RAG)하여 Planner에게 제공함으로써 **"사용자 친화적이고 트렌디한 편집 결과"**를 보장하는 Memory Agent의 설계 및 구현 명세입니다.

---

## 1. 핵심 목적 (Core Objective)

Planner(LLM)는 도구의 사용법은 알지만, **"사용자가 실제로 어떤 색감이나 강도를 좋아하는지"**, **"특정 사진 상태에서 어떤 프롬프트(Gen Edit)가 잘 먹히는지"**에 대한 경험적 직관이 부족합니다.

Memory Agent는 전 세계 사용자들의 피드백이 담긴 **Trajectory 데이터**를 Vector DB에 구축하여, Planner에게 **"과거에 이와 정확히 일치하는 상황(사진 상태 + 요청)에서 이렇게 편집했을 때 사용자가 가장 만족했다"**라는 확실한 컨텍스트(Few-Shot RAG)를 제공합니다.

---

## 2. 아키텍처 설계 (Architecture)

Memory Agent는 크게 **색인(Indexing)** 파이프라인과 **검색(Retrieval)** 파이프라인으로 구성됩니다.

### 2.1 Indexing (경험 축적 파이프라인)

사용자의 세션이 종료되거나 유의미한 피드백이 발생했을 때 비동기적(또는 배치)으로 동작합니다.

1. **데이터 추출**: `TrajectoryStore`에서 `satisfaction_score`가 높은(예: 0.8 이상) 성공적인 `edit_applied` 이벤트를 가져옵니다.
2. **임베딩 텍스트(Vector Key) 생성**:
   - 사용자의 감성적 요청과 사진의 물리적 상태를 결합합니다.
   - 예: `"User Request: {user_text} | Image State: {source_image_context(VLM)}"`
3. **임베딩 변환**: `text-embedding-3-small` 등을 사용하여 벡터화합니다.
4. **메타데이터 패키징 및 Vector DB 저장**:
   - 벡터화된 키와 함께, **"그래서 어떻게 편집했는가(Plan)"**를 메타데이터로 저장합니다.

### 2.2 Retrieval (경험 인출 파이프라인)

새로운 사용자가 편집을 요청할 때 Orchestrator에 의해 실시간(Synchronous)으로 동작합니다.

1. **상황 캡처**: 사용자의 현재 `user_text`와 방금 추출한 현재 이미지의 `VLM 분석 JSON`을 확보합니다.
2. **쿼리 벡터화**: 위 두 정보를 결합하여 검색 쿼리 벡터를 생성합니다.
3. **유사도 검색(Top-K)**: Vector DB에서 현재 상황과 가장 유사한 과거의 성공 사례 3~5개를 가져옵니다.
4. **Planner 주입**: 검색된 사례들을 포매팅하여 Planner의 시스템 프롬프트(또는 Request Payload)에 주입합니다.

---

## 3. 데이터 스키마 설계

Vector DB (예: Pinecone, Milvus, ChromaDB)에 들어갈 데이터 구조입니다.

### 3.1 Vector Embedding (비교 기준)

오직 **"상황"**만을 임베딩하여 유사도를 측정합니다.

```text
[User Prompt]
"아니, 너무 인위적이잖아. 밤거리 느낌나게 자연스럽게 해줘"

[Image VLM Context]
- semantic: 복잡한 도심 거리, 단일 인물
- physical: 노이즈 높음, 약간 블러리함
- color: 푸른빛이 도는 차가운 톤
```

### 3.2 Metadata (검색 후 활용될 실제 정답지)

유사도 검색이 완료된 후 Planner에게 전달될 **"과거의 훌륭한 대처법"**입니다.

```json
{
  "session_id": "uuid-...",
  "original_intent": "correction",
  "satisfaction_score": 0.95,
  "successful_plan": {
    "steps": [
      {
        "tool_name": "opencv_denoise",
        "params": {"strength": 10},
        "rationale": "밤거리의 자글거리는 노이즈를 먼저 부드럽게 잡습니다."
      },
      {
        "tool_name": "split_toning",
        "params": {"shadows_hue": 210, "highlights_hue": 35, "saturation": 40},
        "rationale": "푸른 밤거리의 섀도우는 유지하되, 하이라이트에 웜 톤(가로등 불빛)을 넣어 자연스러운 대비를 만듭니다."
      }
    ]
  }
}
```

---

## 4. Planner 프롬프트 연동 (RAG Injection)

Memory Agent가 검색해 온 과거 사례들은 `PlannerAgent` 내부에서 다음과 같이 조립되어 LLM에 전달됩니다. (TODO.MD의 Phase 3과 연계)

```text
## Reference Success Cases (RAG Memory)

과거에 현재 사용자와 매우 유사한 사진 상태에서, 유사한 요청을 했을 때 성공했던(사용자가 만족했던) 검증된 편집 플랜들입니다. 아래 사례들의 도구(Tool) 선택, 수치(Params), 그리고 프롬프트 작성 방식을 적극적으로 모방하십시오.

[Case 1: 유사도 92%]
- User Asked: "아니, 너무 인위적이잖아. 밤거리 느낌나게 자연스럽게 해줘"
- Image State: 노이즈가 높고 푸른 톤의 도심 거리
- Applied Plan: 1. opencv_denoise (strength: 10) → 2. split_toning (shadows_hue: 210, highlights_hue: 35)
- Learning Point: 밤거리 감성에서는 Gen Edit을 쓰지 않고 노이즈 제거와 색조 분리만으로 자연스러움을 극대화하여 큰 호평을 받음

[Case 2: 유사도 88%]
...
```

---

## 5. 향후 개발 스텝 (To-Do)

1. **`agents/memory_agent.py` 스캐폴딩**: Vector DB (초기엔 로컬 `chromadb` 추천) 연결 및 CRUD 인터페이스 구축
2. **Batch Indexing Job 작성**: `trajectory_store.py`의 JSON/DB를 스캔하여 `satisfaction_score`가 존재하는 이벤트를 찾아 Vector DB에 Upsert 하는 스크립트 작성
3. **Orchestrator 통합**: `_edit_image` 흐름 내에서 VLM 컨텍스트를 뽑은 직후, Memory Agent의 `search_similar_cases(query_text, vlm_context)`를 호출하도록 연결
4. **Planner 통합**: Planner의 입력 페이로드에 `retrieved_cases` 배열을 추가하고 시스템 프롬프트 템플릿 수정
