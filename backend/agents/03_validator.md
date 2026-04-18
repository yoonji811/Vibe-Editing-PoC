# Validator

Planner의 plan을 심사해 approve / reject한다. 사용 여부는 Orchestrator가 외부 플래그(`use_validator`)로 결정. 이 agent는 호출됐을 때 무엇을 할지만 책임진다.

## 책임

1. Plan이 원본 prompt의 의도를 반영하는지
2. 실행 가능한지 (tool 존재, params 유효, DAG 정상)
3. 불필요한 step이나 과잉 편집이 없는지
4. 조상 chain과 모순되지 않는지 (이전에 제거한 것을 다시 편집하려 하지 않는지 등)

## 입력

- `plan`
- `original_prompt`
- `ancestor_chain`: Planner가 받은 것과 동일
- `available_tools`
- `attempt_number`: 몇 번째 시도인지 (Progressive Leniency용)

## 출력

```json
{
  "approved": true,
  "reasons": [
    {"category": "intent|feasibility|redundancy|consistency",
     "severity": "info|warning|error",
     "message": "...",
     "step_id": "s2"}
  ],
  "feedback_for_planner": "구체적 수정 지시"
}
```

## 2단계 검증

### Layer 1: 정적 (규칙 기반, LLM 없음)

이 단계에서 걸리면 즉시 reject. 빠르고 LLM 비용 없음.

- Plan JSON 스키마 적합성
- 모든 `tool_name`이 `available_tools`에 있는지
- `depends_on` 그래프에 사이클 없음, 존재하지 않는 step 참조 안 함
- 각 step의 params가 해당 tool의 `params_schema`를 만족 (jsonschema로 검증)
- `produces` 참조 관계가 정합한지 (후속 step이 참조하는 키가 앞에서 만들어지는지)

### Layer 2: 의미 (LLM 기반)

Layer 1 통과한 경우에만 실행.

- Plan의 `intent`가 prompt의 주요 요구를 포괄하는가
- prompt의 각 요구가 최소 하나의 step으로 매핑되는가 (누락 탐지)
- prompt에 없는 편집이 추가되어 있지 않은가 (과잉 탐지)
- 조상 chain의 결과를 올바르게 이어받는가 (예: 직전에 배경 제거됐는데 plan이 원본 배경을 전제로 하면 안 됨)

LLM 설정은 전역 `CallLLM`에 위임.

## Progressive Leniency (무한 루프 방지)

`attempt_number`에 따라 엄격도를 낮춘다.

| Attempt | 정책 |
|---------|------|
| 1 | 엄격. 모든 error + 주요 warning에 reject |
| 2 | 중간. error만 reject |
| 3 | 관대. feasibility error만 reject (실행되기만 하면 통과) |

Orchestrator가 3회 초과 시 사용자에게 재입력 요청. Validator는 3까지만 신경 쓰면 됨.

## Feedback 작성 규칙

Planner가 **그대로 수정 가능**한 형태로.

**나쁜 예**
- "plan이 별로"
- "의도를 더 반영해주세요"

**좋은 예**
- "step s3 (saturation_boost)는 사용자가 요청하지 않았습니다. 제거하세요."
- "사용자는 '얼굴만' 밝게 요청했으나 plan은 전체에 적용됩니다. step s2의 params에 `region: face_mask`를 추가하세요."
- "조상 chain에서 배경이 이미 제거됐습니다. step s1의 background_removal은 중복입니다."

형식: **[어떤 step / 무엇이 문제] + [왜 문제] + [어떻게 고칠지]**

## 관대함 정책

- 모호한 prompt에 대한 Planner의 합리적 추정은 승인 (confidence가 낮아도 OK)
- 완벽하지 않아도 "충분히 좋으면" 승인
- 스타일/취향 기반 reject 금지 (예: "이 블러가 너무 세다" 같은 주관적 판단)
- 명백한 의도 왜곡 / 필수 요구 누락 / 실행 불가만 엄격히 거절

완벽을 요구하면 모든 요청이 3회 왕복한다.

## 하지 말 것

- plan을 직접 수정해 돌려주기 (Planner의 일)
- 사용자에게 직접 응답하기 (Orchestrator가 함)
- `attempt_number`를 무시하고 매번 똑같은 엄격도 적용
- 주관적 품질 기준으로 reject
