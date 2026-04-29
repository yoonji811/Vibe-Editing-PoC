"""카리나 이미지로 3번 편집 + 피드백 파이프라인 실습."""
import json, os, time, requests

BASE = "http://localhost:8001"
IMG_PATH = r"C:\Users\qmffl\OneDrive\바탕 화면\Vibe-Editing\Vibe-Editing-PoC\karina aespa.jpg"

# ── 세션 생성 ─────────────────────────────────────────────────
with open(IMG_PATH, "rb") as f:
    raw = f.read()

resp = requests.post(
    f"{BASE}/api/session/new",
    files={"file": ("karina aespa.jpg", raw, "image/jpeg")},
    data={"user_nickname": "test_user"},
)
resp.raise_for_status()
session = resp.json()
session_id = session["session_id"]
print(f"\n[SESSION] id={session_id}")
print(f"          image: {session['width']}x{session['height']}")

def edit(prompt, label):
    print(f"\n{'='*60}")
    print(f"[EDIT {label}]")
    print(f"  prompt: \"{prompt}\"")
    t = time.time()
    r = requests.post(f"{BASE}/api/edit/{session_id}", json={"user_text": prompt})
    r.raise_for_status()
    d = r.json()
    wall = int((time.time() - t) * 1000)
    timing = d.get("timing_ms") or {}
    print(f"  event_id : {d.get('event_id')}")
    print(f"  intent   : {d.get('intent')}")
    print(f"  engine   : {d.get('engine')} / op: {d.get('operation')}")
    print(f"  latency  : {d.get('latency_ms')}ms  (wall={wall}ms)")
    if timing:
        print(f"  timing breakdown:")
        for k, v in timing.items():
            bar = "=" * (v // 200) if v else ""
            print(f"    {k:12s}: {str(v).rjust(5)}ms  {bar}")
    return d.get("event_id"), d.get("latency_ms", 0)

def feedback(event_id, action, score, label):
    r = requests.post(
        f"{BASE}/api/feedback/{session_id}",
        json={"target_event_id": event_id, "feedback_type": "explicit",
              "action": action, "reward_score": score},
    )
    r.raise_for_status()
    print(f"  feedback : [{label}] score={score}")

# ── 3번의 편집 ────────────────────────────────────────────────
eid1, lat1 = edit("따뜻한 분위기로 만들어줘", "1  (새 요청)")
feedback(eid1, "thumbs_up", 1.0, "GOOD")

eid2, lat2 = edit("너무 밝게 만들어줘", "2  (새 요청)")
feedback(eid2, "thumbs_down", -1.0, "BAD")

eid3, lat3 = edit("이건 별로야, 자연스러운 밝기로 돌아가줘", "3  (교정 요청)")
feedback(eid3, "thumbs_up", 1.0, "GOOD")

# ── 시간 요약 ─────────────────────────────────────────────────
total = lat1 + lat2 + lat3
print(f"\n{'='*60}")
print(f"[TIME SUMMARY]")
print(f"  Edit 1 : {lat1}ms")
print(f"  Edit 2 : {lat2}ms")
print(f"  Edit 3 : {lat3}ms")
print(f"  합계   : {total}ms  ({total/1000:.1f}s)")

# ── trajectory 파일 확인 ──────────────────────────────────────
traj_file = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "data", "trajectories", f"{session_id}.json")
)
print(f"\n[TRAJECTORY]")
print(f"  경로   : {traj_file}")
print(f"  존재   : {os.path.exists(traj_file)}")
if os.path.exists(traj_file):
    print(f"  크기   : {os.path.getsize(traj_file):,} bytes")
    with open(traj_file, encoding="utf-8") as f:
        traj = json.load(f)
    events = [e for e in traj.get("events", []) if e["type"] == "edit_applied"]
    print(f"  edit_applied 이벤트: {len(events)}개")
    for i, ev in enumerate(events, 1):
        p = ev["payload"]
        steps = (p.get("plan") or {}).get("steps", [])
        print(f"\n  [Event {i}]")
        print(f"    event_id     : {ev['event_id']}")
        print(f"    user_text    : {p.get('user_text')}")
        print(f"    intent       : {p.get('intent_classified')}")
        print(f"    is_correction: {p.get('is_correction')}")
        print(f"    satisfaction : {p.get('satisfaction_score')}")
        print(f"    feedback_type: {p.get('feedback_type')}")
        print(f"    tools used   : {[s.get('tool_name') for s in steps]}")
        print(f"    latency_ms   : {p.get('latency_ms')}")
