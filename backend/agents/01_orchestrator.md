# Orchestrator

사용자 요청을 받아 Planner → (Validator) → 실행 파이프라인을 돌리는 관제 에이전트. Tool은 registry에서 이름으로 꺼내 `run()`만 호출한다. **Registry에 없는 tool이 plan에 나오는 상황은 없다고 가정한다** (Planner가 available_tools 안에서만 고르기 때문).

## 책임

1. 세션 및 편집 히스토리 tree 관리
2. Planner에 필요한 컨텍스트 조립해 전달
3. 사용자가 켜둔 경우에만 Validator 호출
4. 승인된 plan의 step을 순서대로 실행
5. 결과 이미지를 히스토리 tree의 새 node로 기록
6. 결과 + 설명을 사용자에게 응답

## 입출력

**Request**
```
session_id (optional)
base_edit_id (optional)    # 어느 편집 시점을 기반으로 수정할지
user_id
image (optional)           # 세션 이어가기면 생략 가능, 서버가 base_edit_id의 이미지 사용
prompt
use_validator: bool        # 외부 UI에서 전달, validator 사용 여부
```

**Response**
```
session_id
edit_id                    # 이번 편집 결과의 고유 id (tree node)
parent_edit_id
result_image
executed_plan
explanation
errors
```

## 편집 히스토리: Tree

사용자가 "3번째 수정 후 2번째로 돌아가 다른 방향으로 재수정" 하는 시나리오를 지원해야 한다. linear history가 아니라 **tree**로 저장.

```
세션 내부:
  v0 (원본)
   └─ v1 ── v2 ── v3       ← 첫 시도
           └─ v2' ── v3'   ← v2에서 분기한 대안
```

각 node(= edit):
```
{
  edit_id,
  parent_edit_id,          # 루트 node만 None
  session_id,
  prompt,                  # 이 수정에서 사용자가 입력한 prompt
  plan,                    # Planner가 낸 plan
  validator_verdict,       # Validator 사용했으면 결과, 아니면 null
  image_ref,               # 결과 이미지 저장 위치
  created_at
}
```

요청이 `base_edit_id`를 포함하면 Orchestrator는 그 node의 `image_ref`를 현재 입력 이미지로 쓰고, 새 node의 `parent_edit_id`로 그 값을 기록한다. 생략하면 세션의 가장 최근 node를 기준으로 한다.

## Planner에 넘기는 컨텍스트

- 현재 prompt
- **현재 분기의 조상 chain** (base_edit_id부터 루트까지 거슬러 올라가며 수집한 {prompt, plan 요약, intent}). 다른 분기(v3')의 내용은 포함하지 않는다.
- base image의 메타데이터 (width, height, detected_objects, dominant_colors)
- `tool_registry.list()` 결과
- 재시도인 경우 Validator의 직전 feedback

## Validator 호출 조건

`use_validator` 플래그로 제어.

| use_validator | 동작 |
|--------------|------|
| `true` | Planner → Validator → (reject 시 Planner 재호출, 최대 3회) → 실행 |
| `false` | Planner → 바로 실행 (Validator 건너뜀) |

기본값은 운영 정책에 따라 결정 (권장: UI에서 사용자가 선택, default는 `true`).

## 재시도 정책

Validator 사용 시:

| 상황 | 동작 |
|------|------|
| Validator reject (attempt < 3) | feedback 붙여 Planner 재호출 |
| Validator 3회 연속 reject | "prompt가 모호합니다, 구체화해 주세요" 반환 |
| Tool 실행 중 예외 | 동일 step 1회 재시도, 실패 시 전체 편집 실패 |
| 전체 타임아웃 (예: 60초) | 부분 결과 반환 또는 에러 |

Validator 미사용 시에는 실패하면 그대로 에러 반환.

## Plan 실행

```
current_image = base_edit_id의 이미지 (또는 요청으로 새로 들어온 이미지)
for step in topological_sort(plan.steps):
    tool = registry.get(step.tool_name)
    current_image, produced = tool.run(current_image, **step.params)
    produced (예: mask)를 step.produces 키로 임시 저장
    후속 step의 params에 이 키가 참조되어 있으면 치환
최종 이미지를 저장, 새 edit node로 트리에 추가
```

## 사용자 응답

결과 이미지 외에 다음을 포함:
- Planner의 `intent` 문장 ("인물을 강조하고 배경을 단순화하신 거네요")
- 이번 편집의 `edit_id` (사용자가 나중에 돌아올 때 쓸 수 있음)
- Validator가 관대 모드 승인을 한 경우 해석 방식 안내

## 로깅

모든 로그에 `session_id`, `edit_id`, `parent_edit_id`, `plan_id`를 주입. 나중에 세션 로그 DB에서 Tool Generator가 이 기록을 분석한다.

## 상태 보존

Orchestrator 인스턴스는 stateless. 세션 tree, 이미지, 메타는 전부 외부 store(DB + 파일시스템/S3)에. 인스턴스가 죽어도 session_id로 다른 인스턴스가 이어받을 수 있어야 한다.

## 하지 말 것

- Registry에 없는 tool을 런타임에 생성 시도하기 (그런 상황 자체가 없어야 함; 있으면 Planner 버그 또는 registry 동기화 문제)
- plan을 직접 수정하기 (Validator의 일)
- 사용자 prompt를 직접 해석하기 (Planner의 일)
- 다른 분기(sibling)의 편집 내용을 Planner 컨텍스트에 섞기
