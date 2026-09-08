#!/usr/bin/env python3
"""End-to-end smoke test against a deployed Multi-Major environment.

Creates one throwaway confirmed account, pushes synthetic audit PDFs through
upload -> analysis -> saved map, then deletes the account. Uses no real student
data and never touches DARS/.
"""
import argparse, json, os, secrets, sys, time
import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.cloud.fixtures import pdf, audit_text  # noqa: E402

PROGRAMS = [
    ("Computer Science", "ASBSCS"),
    ("Minor in Spanish", "MINSPA"),
    ("Certificate in Sustainability", "CERSUS"),
]


def step(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--origin", required=True)
    ap.add_argument("--wait", type=int, default=180, help="seconds to wait for processing")
    args = ap.parse_args()
    origin = args.origin.rstrip("/")

    sup = os.environ["SUPABASE_URL"].rstrip("/")
    sec = os.environ["SUPABASE_SECRET_KEY"]
    cron = os.environ.get("CRON_SECRET", "")
    admin = {"apikey": sec, "Authorization": f"Bearer {sec}"}

    email = f"smoke-{secrets.token_hex(5)}@example.com"
    password = secrets.token_urlsafe(18) + "aA1!"
    user_id = None
    failures = []

    print(f"\nSmoke test against {origin}")
    print(f"throwaway account: {email}\n")
    try:
        # 1. A confirmed account, created straight through the admin API so the
        #    test needs no inbox and no CAPTCHA.
        r = httpx.post(f"{sup}/auth/v1/admin/users", headers=admin, timeout=60,
                       json={"email": email, "password": password, "email_confirm": True})
        user_id = r.json().get("id")
        if not step("create confirmed test account", r.status_code in (200, 201) and user_id,
                    f"HTTP {r.status_code}"):
            failures.append("account"); return failures

        c = httpx.Client(base_url=origin, timeout=90, follow_redirects=False)

        s = c.get("/api/auth/session")
        csrf = s.json().get("csrf", "")
        H = {"Origin": origin, "X-CSRF-Token": csrf}
        if not step("fetch CSRF token", s.status_code == 200 and bool(csrf), f"HTTP {s.status_code}"):
            failures.append("csrf"); return failures

        r = c.post("/api/auth/login", headers=H, json={"email": email, "password": password})
        if not step("sign in", r.status_code == 200, f"HTTP {r.status_code} {r.text[:120]}"):
            failures.append("login"); return failures

        docs = [pdf(audit_text(program=n, code=cd)) for n, cd in PROGRAMS]
        r = c.post("/api/v1/uploads", headers=H,
                   json={"files": [{"size": len(d)} for d in docs], "preferences": {}, "consent": True})
        if not step("request upload ticket", r.status_code == 200, f"HTTP {r.status_code} {r.text[:160]}"):
            failures.append("uploads"); return failures
        ticket = r.json()
        job = ticket["job_id"]

        ok = True
        for obj, content in zip(ticket["uploads"], docs):
            u = httpx.put(obj["url"], content=content, timeout=120,
                          headers={"Content-Type": "application/pdf", "x-upsert": "false"})
            if u.status_code >= 400:
                ok = False
                step("upload PDF to storage", False, f"HTTP {u.status_code} {u.text[:200]}")
                break
        if ok:
            step("upload 3 synthetic PDFs to private storage", True)
        else:
            failures.append("storage"); return failures

        r = c.post("/api/v1/analyses", headers=H, json={"job_id": job})
        # The engine accepts the job with 202, not 200.
        if not step("enqueue analysis", r.status_code in (200, 202), f"HTTP {r.status_code} {r.text[:160]}"):
            failures.append("enqueue"); return failures

        # The queue may not be available on this plan; the maintenance sweep is
        # the documented fallback dispatcher, so nudge it rather than waiting
        # for the scheduled run.
        if cron:
            m = httpx.get(f"{origin}/api/maintenance", timeout=120,
                          headers={"Authorization": f"Bearer {cron}"})
            step("trigger maintenance sweep", m.status_code == 200,
                 f"HTTP {m.status_code} {m.text[:120]}")

        deadline = time.time() + args.wait
        status, nudged = "", False
        while time.time() < deadline:
            j = c.get(f"/api/v1/analyses/{job}")
            status = j.json().get("status", "?")
            if status in ("completed", "failed", "cancelled"):
                break
            time.sleep(5)
            if cron and not nudged and time.time() > deadline - args.wait / 2:
                httpx.get(f"{origin}/api/maintenance", timeout=120,
                          headers={"Authorization": f"Bearer {cron}"})
                nudged = True
        if not step(f"analysis reaches 'completed' (got '{status}')", status == "completed"):
            failures.append(f"processing:{status}")

        if status == "completed":
            p = c.get("/api/v1/plans")
            step("a semester map was saved", p.status_code == 200 and len(p.json()) > 0,
                 f"{len(p.json()) if p.status_code==200 else '?'} plan(s)")

        # Originals must be gone regardless of outcome.
        o = httpx.get(f"{sup}/rest/v1/objects?select=name&bucket_id=eq.audit-uploads",
                      headers={**admin, "Accept-Profile": "storage"}, timeout=60)
        left = len(o.json()) if o.status_code == 200 else -1
        if not step("original PDFs deleted from storage", left == 0, f"{left} object(s) remain"):
            failures.append("cleanup")
        return failures
    finally:
        if user_id:
            d = httpx.delete(f"{sup}/auth/v1/admin/users/{user_id}", headers=admin, timeout=60)
            step("delete throwaway account", d.status_code in (200, 204), f"HTTP {d.status_code}")


if __name__ == "__main__":
    f = main() or []
    print("\n" + ("SMOKE TEST PASSED — the deployment works end to end."
                  if not f else f"SMOKE TEST FAILED at: {', '.join(f)}"))
    sys.exit(1 if f else 0)
