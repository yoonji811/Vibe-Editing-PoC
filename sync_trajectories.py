"""
Trajectory auto-sync script.
Railway PostgreSQL → 로컬 backend/data/trajectories/{session_id}.json

사용법:
  python sync_trajectories.py              # 1회 동기화
  python sync_trajectories.py --watch 30  # 30초마다 자동 동기화
"""
import argparse
import json
import time
from datetime import datetime
from pathlib import Path
import urllib.request

API_URL = "https://vibe-backend-production-55a7.up.railway.app/api/trajectory/export/all"
LOCAL_DIR = Path(__file__).parent / "backend" / "data" / "trajectories"


def sync():
    ts = datetime.now().strftime("%H:%M:%S")
    try:
        with urllib.request.urlopen(API_URL, timeout=15) as resp:
            remote_list = json.loads(resp.read())
    except Exception as e:
        print(f"[{ts}] 연결 실패: {e}")
        return

    LOCAL_DIR.mkdir(parents=True, exist_ok=True)

    new_count = updated_count = 0
    for traj in remote_list:
        session_id = traj.get("session_id")
        if not session_id:
            continue

        path = LOCAL_DIR / f"{session_id}.json"

        if path.exists():
            local = json.loads(path.read_text(encoding="utf-8"))
            # 이벤트 수가 늘었으면 업데이트
            if len(traj.get("events", [])) > len(local.get("events", [])):
                path.write_text(json.dumps(traj, ensure_ascii=False, indent=2), encoding="utf-8")
                updated_count += 1
        else:
            path.write_text(json.dumps(traj, ensure_ascii=False, indent=2), encoding="utf-8")
            new_count += 1

    parts = [f"총 {len(remote_list)}개"]
    if new_count:
        parts.append(f"신규 {new_count}개")
    if updated_count:
        parts.append(f"업데이트 {updated_count}개")
    print(f"[{ts}] {', '.join(parts)} → {LOCAL_DIR}")


def main():
    parser = argparse.ArgumentParser(description="Railway trajectory 로컬 동기화")
    parser.add_argument("--watch", type=int, metavar="초",
                        help="N초마다 자동 동기화 (없으면 1회 실행)")
    args = parser.parse_args()

    sync()
    if args.watch:
        print(f"자동 동기화 중... (매 {args.watch}초, 종료: Ctrl+C)")
        while True:
            time.sleep(args.watch)
            sync()


if __name__ == "__main__":
    main()
