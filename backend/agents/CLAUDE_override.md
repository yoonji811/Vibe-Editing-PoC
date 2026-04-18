# Agentic AI Image Editor — Agents

4개 agent로 구성된 이미지 편집 시스템.

## Agent 역할

| Agent | 역할 | 실행 시점 |
|-------|------|----------|
| **Orchestrator** | 세션/히스토리 관리, Planner·Validator 호출, plan 실행 | Runtime (매 요청) |
| **Planner** | prompt → plan JSON 생성 (Gemini) | Runtime |
| **Validator** | plan의 의도 정합성/실행 가능성 심사 (optional) | Runtime, 외부 UI 플래그로 on/off |
| **Tool Generator** | 세션 로그 분석 → 필요한 tool의 코드 생성 + registry 등록 | **개발 시점 오프라인 배치** |

## 런타임 데이터 흐름

```
User → Orchestrator ──→ Planner ──→ (Validator) ──→ Plan 실행
                          ▲                │
                          └─── reject ─────┘
                                    ↓ approve
                              Tool Registry의 tool.run() 호출
```

핵심: **런타임에는 Tool Generator가 등장하지 않는다.** Registry는 항상 충분하다는 가정으로 동작한다.

## 개발 시점 흐름 (오프라인)

```
세션 로그 DB ──→ Tool Generator (주기적 실행 or 개발자 트리거)
                      ↓
                패턴 분석 → tool 코드 생성 → sandbox 검증
                      ↓
                Tool Registry에 등록
```

## 공통 계약

### 1. Plan JSON

Planner 출력, Validator 입력, Orchestrator 실행 대상.

```json
{
  "plan_id": "uuid",
  "intent": "추론된 사용자 의도",
  "confidence": 0.0,
  "steps": [
    {
      "step_id": "s1",
      "tool_name": "registry에 이미 있는 이름",
      "params": { "...": "tool마다 다름" },
      "depends_on": [],
      "produces": "mask_1",
      "rationale": "이 step을 넣은 이유"
    }
  ],
  "unmet_requirements": []
}
```

`unmet_requirements`: 현재 registry로 완벽히 달성 불가능한 요구사항을 Planner가 기록. 런타임 동작에는 영향 없음. Tool Generator가 오프라인에서 이 필드를 집계해 tool 추가 판단에 씀.

### 2. Tool Registry 인터페이스

Orchestrator는 tool을 **블랙박스**로 다룬다. Planner / Validator만 내부 schema를 본다.

```python
class Tool:
    name: str
    description: str       # Planner가 선택할 때 읽음
    params_schema: dict    # Validator가 검증할 때 읽음
    def run(self, image, **params) -> image: ...
```

Registry API:
- `get(name) -> Tool`
- `list() -> [{name, description, params_schema}]`
- `register(tool)`  ← Tool Generator (개발 시점)만 호출

### 3. 편집 히스토리: Tree 구조

단순 linear append가 아니라 **branching tree**. 사용자가 3번째 수정에서 2번째로 돌아가 다른 방향으로 편집할 수 있어야 한다.

```
   v0 (원본)
    └── v1 ── v2 ── v3
              └── v2' ── v3'   (v2에서 분기)
```

각 node는 `{edit_id, parent_id, prompt, plan, image_ref, created_at}`. Orchestrator가 이 tree를 관리.

### 4. 공용 LLM 호출

전체 시스템이 쓰는 `CallLLM` 래퍼 하나를 만든다. 각 agent는 모델명/temperature 같은 세부 설정을 자기 파일에 하드코딩하지 않고 `CallLLM`에 위임. 이 agent들 명세에서 LLM 세팅은 다루지 않는다.

## 구현 순서

1. Tool Registry + 기본 OpenCV tool 몇 개 (수동 등록)
2. Planner (mock validator로 단독 테스트)
3. Validator (정적 검증만 먼저)
4. Orchestrator 단일 편집 (tree 없이)
5. 편집 히스토리 tree 추가 (멀티턴 + 분기)
6. Validator LLM 계층 추가 + on/off 플래그
7. Tool Generator (별도 배치/CLI 툴로)

## 파일

- `01_orchestrator.md`
- `02_planner.md`
- `03_validator.md`
- `04_tool_generator.md`
