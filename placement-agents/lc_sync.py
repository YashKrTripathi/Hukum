"""LeetCode sync from your PUBLIC profile (no login needed). Needs LEETCODE_USERNAME.
- total solved count -> kv 'lc_total' (counts toward the 300 goal)
- last 20 accepted submissions -> auto-marks matching problems in the sheet list"""
import httpx
import db
from config import LEETCODE_USERNAME

URL = "https://leetcode.com/graphql"
HDR = {"Content-Type": "application/json", "Referer": "https://leetcode.com"}
Q_RECENT = "query($u:String!,$l:Int!){recentAcSubmissionList(username:$u,limit:$l){title}}"
Q_STATS = "query($u:String!){matchedUser(username:$u){submitStats{acSubmissionNum{difficulty count}}}}"


def _gql(q, v):
    r = httpx.post(URL, json={"query": q, "variables": v}, headers=HDR, timeout=15)
    r.raise_for_status()
    return r.json()["data"]


def sync() -> list[str]:
    """Returns names of sheet problems newly detected as solved."""
    if not LEETCODE_USERNAME:
        return []
    u = LEETCODE_USERNAME
    stats = _gql(Q_STATS, {"u": u})["matchedUser"]["submitStats"]["acSubmissionNum"]
    total = next((s["count"] for s in stats if s["difficulty"] == "All"), 0)
    db.put("lc_total", total)
    found = []
    for s in _gql(Q_RECENT, {"u": u, "l": 20})["recentAcSubmissionList"] or []:
        row = db.q("SELECT id,name FROM problems WHERE done=0 AND lower(name)=lower(?)", (s["title"],))
        if row:
            db.x("UPDATE problems SET done=1, done_on=date('now') WHERE id=?", (row[0]["id"],))
            found.append(row[0]["name"])
    return found
