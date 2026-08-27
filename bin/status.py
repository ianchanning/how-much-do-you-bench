#!/usr/bin/env python3
"""Query live benchmark leaderboard and submission status from the backend API."""

import json
import os
import sys
import urllib.request
from pathlib import Path


def load_env() -> None:
    for candidate in [Path(".env"), Path("../.env")]:
        if candidate.exists():
            try:
                for line in candidate.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k and k not in os.environ:
                        os.environ[k] = v
            except Exception:
                pass


def main() -> None:
    load_env()
    key = os.environ.get("GATEWAY_API_KEY")
    if not key:
        print("Error: GATEWAY_API_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1)

    api_url = os.environ.get("API_URL", "https://bench.playground.dataminded.cloud")
    url = f"{api_url}/results"

    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception as exc:
        print(f"Failed to fetch results from {url}: {exc}", file=sys.stderr)
        sys.exit(1)

    print("=" * 75)
    print("🏆 LIVE BENCHMARK LEADERBOARD 🏆")
    print("=" * 75)

    teams: dict[str, dict] = {}
    for sub in data.get("submissions", []):
        team = sub.get("team", "unknown")
        passed = sub.get("passed", 0)
        completed = sub.get("completed", 0)
        tokens = sub.get("tokens", 0)
        sub_id = sub.get("submission_id")
        status = sub.get("status")

        if team not in teams or passed > teams[team]["passed"]:
            teams[team] = {
                "submission_id": sub_id,
                "passed": passed,
                "completed": completed,
                "tokens": tokens,
                "status": status,
            }

    sorted_teams = sorted(
        teams.items(), key=lambda x: (x[1]["passed"], -x[1]["tokens"]), reverse=True
    )
    for rank, (team, stats) in enumerate(sorted_teams, 1):
        medal = "🥇" if rank == 1 else ("🥈" if rank == 2 else ("🥉" if rank == 3 else f"#{rank:2d}"))
        print(
            f"{medal} {team:22s} | Passed: {stats['passed']:2d}/17 | Tokens: {stats['tokens']:10,d} | Best: {stats['submission_id']}"
        )

    print("\n" + "=" * 75)
    print("YOUR SUBMISSIONS (Team: trainspotters)")
    print("=" * 75)

    my_subs = [
        s
        for s in data.get("submissions", [])
        if s.get("team") == "trainspotters" or "trainspotters" in s.get("submission_id", "")
    ]

    for sub in reversed(my_subs):
        sub_id = sub.get("submission_id")
        commit = sub.get("commit", "unknown")
        status = sub.get("status", "unknown")
        passed = sub.get("passed", 0)
        completed = sub.get("completed", 0)
        total = sub.get("task_count", 17)
        tokens = sub.get("tokens", 0)
        dur = sub.get("duration_s", 0)

        print(
            f"ID: {sub_id} (commit {commit}) [{status.upper()}] - Completed: {completed}/{total} | Passed: {passed} | Tokens: {tokens:,} | Time: {dur:.1f}s"
        )

        tasks = sub.get("tasks", [])
        if tasks:
            for t in tasks:
                icon = "✅" if t.get("passed") else "❌"
                task_name = t.get("task_id", "")
                t_dur = t.get("duration_s", 0)
                agent = t.get("agent", "")
                print(f"   {icon} {task_name:42s} ({t_dur:5.1f}s, agent: {agent})")
        else:
            print("   (Tasks currently running in worker queue...)")
        print("-" * 75)


if __name__ == "__main__":
    main()
