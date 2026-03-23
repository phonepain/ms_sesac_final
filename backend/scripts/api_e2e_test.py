"""
API E2E 테스트 — 프론트엔드가 사용하는 모든 엔드포인트 자동 검증

순서:
  1. Health Check
  2. 소스 업로드 (세계관 / 설정집 / 시나리오)
  3. 소스 목록 조회
  4. KB 통계 조회
  5. 전수조사 (모순 탐지)
  6. 원고 분석
  7. 사용자 확인 목록 조회 + 해결
  8. 수정 스테이징 + Push → 버전 생성
  9. 버전 목록 / 내용 / diff
 10. 소스 다운로드
 11. AI 질의
 12. 소스 삭제

사용법:
    python scripts/api_e2e_test.py
    python scripts/api_e2e_test.py --url http://localhost:8000
"""
import sys
import os
import argparse
import json
import time

# Windows cp949 환경에서 em dash 등 한글 외 문자 출력 시 인코딩 오류 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import httpx
except ImportError:
    print("[ERROR] httpx 없음 — pip install httpx")
    sys.exit(1)

SAMPLE_DIR = os.path.join(os.path.dirname(__file__), "../../data/sample")
SAMPLES = [
    ("세계관_그림자의비밀.txt", "worldview"),
    ("설정집_그림자의비밀.txt", "settings"),
    ("시나리오_그림자의비밀.txt", "scenario"),
]

SEP  = "=" * 65
DASH = "-" * 65
PASS = "PASS"
FAIL = "FAIL"


def log(msg=""):
    print(msg, flush=True)


def ok(label, detail=""):
    suffix = f"  →  {detail}" if detail else ""
    log(f"  [{PASS}] {label}{suffix}")


def fail(label, detail=""):
    log(f"  [{FAIL}] {label}  →  {detail}")


def section(title):
    log()
    log(DASH)
    log(f"  {title}")
    log(DASH)


def run(base_url: str):
    results = {}

    with httpx.Client(base_url=base_url, timeout=120.0) as c:

        # ── 1. Health ─────────────────────────────────────────────
        section("1. Health Check")
        try:
            r = c.get("/api/health")
            r.raise_for_status()
            ok("GET /api/health", r.json())
            results["health"] = True
        except Exception as e:
            fail("GET /api/health", str(e))
            results["health"] = False
            log("\n  서버가 실행 중인지 확인하세요: uvicorn app.main:app --reload")
            return results

        # ── 2. 소스 업로드 ─────────────────────────────────────────
        section("2. 소스 업로드 (3종)")
        uploaded = {}
        for filename, stype in SAMPLES:
            path = os.path.join(SAMPLE_DIR, filename)
            if not os.path.exists(path):
                fail(f"POST /api/sources/upload [{stype}]", f"파일 없음: {path}")
                continue
            try:
                t0 = time.time()
                with open(path, "rb") as f:
                    r = c.post(
                        "/api/sources/upload",
                        files={"file": (filename, f, "text/plain")},
                        data={"source_type": stype},
                    )
                r.raise_for_status()
                data = r.json()
                source_id = data["source_id"]
                uploaded[stype] = source_id
                ok(
                    f"POST /api/sources/upload [{stype}]",
                    f"source_id={source_id}  entities={data.get('extracted_entities')}  ({time.time()-t0:.1f}s)",
                )
            except Exception as e:
                fail(f"POST /api/sources/upload [{stype}]", str(e))
        results["upload"] = len(uploaded) == len(SAMPLES)

        # ── 3. 소스 목록 ───────────────────────────────────────────
        section("3. 소스 목록 조회")
        try:
            r = c.get("/api/sources")
            r.raise_for_status()
            sources = r.json()
            ok("GET /api/sources", f"{len(sources)}개")
            for s in sources:
                log(f"     id={s.get('id') or s.get('source_id')}  type={s.get('source_type')}  name={s.get('name')}")
            results["sources_list"] = True
        except Exception as e:
            fail("GET /api/sources", str(e))
            results["sources_list"] = False

        # ── 4. KB 통계 ─────────────────────────────────────────────
        section("4. KB 통계 조회")
        try:
            r = c.get("/api/kb/stats")
            r.raise_for_status()
            stats = r.json()
            ok("GET /api/kb/stats")
            for k, v in stats.items():
                log(f"     {k:20s}: {v}")
            results["kb_stats"] = True
        except Exception as e:
            fail("GET /api/kb/stats", str(e))
            results["kb_stats"] = False

        # ── 5. 전수조사 ────────────────────────────────────────────
        section("5. 전수조사 (POST /api/scan)")
        try:
            t0 = time.time()
            r = c.post("/api/scan")
            r.raise_for_status()
            data = r.json()
            hard = len(data.get("contradictions", []))
            conf = len(data.get("confirmations", []))
            ok("POST /api/scan", f"HARD={hard}  확인필요={conf}  ({time.time()-t0:.1f}s)")
            results["scan"] = True
        except Exception as e:
            fail("POST /api/scan", str(e))
            results["scan"] = False

        # ── 6. 원고 분석 ───────────────────────────────────────────
        section("6. 원고 분석 (POST /api/analyze)")
        manuscript = "형사 A: B가 범인이야, 분명해.\nB: 나는 그날 집에 있었어.\nA: 목격자 C가 증언했어. B가 현장에 있었다고."
        try:
            t0 = time.time()
            r = c.post("/api/analyze", json={"content": manuscript, "title": "API E2E 테스트 원고"})
            r.raise_for_status()
            data = r.json()
            hard = len(data.get("contradictions", []))
            conf = len(data.get("confirmations", []))
            ok("POST /api/analyze", f"HARD={hard}  확인필요={conf}  ({time.time()-t0:.1f}s)")
            for c_ in data.get("contradictions", [])[:3]:
                log(f"     [{c_.get('hard_or_soft','?').upper()}] {c_.get('description','')[:60]}")
            results["analyze"] = True
            analysis_data = data
        except Exception as e:
            fail("POST /api/analyze", str(e))
            results["analyze"] = False
            analysis_data = {}

        # ── 7. 사용자 확인 ─────────────────────────────────────────
        section("7. 사용자 확인 (GET /api/confirmations)")
        confirmation_id = None
        try:
            r = c.get("/api/confirmations")
            r.raise_for_status()
            confs = r.json()
            ok("GET /api/confirmations", f"{len(confs)}개")
            for cf in confs[:3]:
                log(f"     id={cf.get('id')}  type={cf.get('confirmation_type')}  status={cf.get('status')}")
                if not confirmation_id:
                    confirmation_id = cf.get("id")
            results["confirmations_list"] = True
        except Exception as e:
            fail("GET /api/confirmations", str(e))
            results["confirmations_list"] = False

        if confirmation_id:
            try:
                r = c.post(
                    f"/api/confirmations/{confirmation_id}/resolve",
                    json={"decision": "confirmed_contradiction", "user_response": "테스트 해결"},
                )
                r.raise_for_status()
                ok(f"POST /api/confirmations/{confirmation_id}/resolve", r.json().get("final_status"))
                results["confirmation_resolve"] = True
            except Exception as e:
                fail(f"POST /api/confirmations/{confirmation_id}/resolve", str(e))
                results["confirmation_resolve"] = False
        else:
            log("  (SKIP) 해결할 확인 항목 없음")

        # ── 8. 수정 스테이징 + Push ────────────────────────────────
        section("8. 수정 스테이징 + Push")
        source_id_for_fix = uploaded.get("scenario") or (list(uploaded.values())[0] if uploaded else None)
        version_id = None

        if source_id_for_fix:
            try:
                r = c.post("/api/fixes/stage", json={
                    "contradiction_id": "test-c-001",
                    "is_intentional": True,
                    "intent_note": "API E2E 테스트 — 작가 의도 인정",
                })
                r.raise_for_status()
                ok("POST /api/fixes/stage", r.json().get("status"))
                results["stage_fix"] = True
            except Exception as e:
                fail("POST /api/fixes/stage", str(e))
                results["stage_fix"] = False

            try:
                r = c.post("/api/fixes/push", json={
                    "source_id": source_id_for_fix,
                    "description": "API E2E 테스트 수정",
                })
                r.raise_for_status()
                data = r.json()
                version_id = data.get("id")
                ok("POST /api/fixes/push", f"version={data.get('version')}  fixes={data.get('fixes_count')}")
                results["push_fix"] = True
            except Exception as e:
                fail("POST /api/fixes/push", str(e))
                results["push_fix"] = False
        else:
            log("  (SKIP) 업로드된 소스 없음")

        # ── 9. 버전 관리 ───────────────────────────────────────────
        section("9. 버전 관리")
        try:
            r = c.get("/api/versions")
            r.raise_for_status()
            versions = r.json()
            ok("GET /api/versions", f"{len(versions)}개")
            for v in versions:
                log(f"     id={v.get('id')}  version={v.get('version')}  fixes={v.get('fixes_count')}")
            results["versions_list"] = True
            if not version_id and versions:
                version_id = versions[0].get("id")
        except Exception as e:
            fail("GET /api/versions", str(e))
            results["versions_list"] = False

        if version_id:
            try:
                r = c.get(f"/api/versions/{version_id}/content")
                r.raise_for_status()
                content = r.json().get("content", "")
                ok(f"GET /api/versions/{version_id}/content", f"{len(content)}자")
                results["version_content"] = True
            except Exception as e:
                fail(f"GET /api/versions/{version_id}/content", str(e))
                results["version_content"] = False
        else:
            log("  (SKIP) 버전 없음")

        # ── 10. 소스 다운로드 ──────────────────────────────────────
        section("10. 소스 다운로드")
        dl_id = uploaded.get("worldview") or (list(uploaded.values())[0] if uploaded else None)
        if dl_id:
            try:
                r = c.get(f"/api/sources/{dl_id}/download")
                r.raise_for_status()
                ok(f"GET /api/sources/{dl_id}/download", f"{len(r.content):,} bytes")
                results["download"] = True
            except Exception as e:
                fail(f"GET /api/sources/{dl_id}/download", str(e))
                results["download"] = False
        else:
            log("  (SKIP) 업로드된 소스 없음")

        # ── 11. AI 질의 ────────────────────────────────────────────
        section("11. AI 질의 (POST /api/ai/query)")
        try:
            r = c.post("/api/ai/query", json={"query": "형사 A와 B의 관계는?"})
            r.raise_for_status()
            data = r.json()
            ok("POST /api/ai/query", data.get("answer", "")[:60])
            results["ai_query"] = True
        except Exception as e:
            fail("POST /api/ai/query", str(e))
            results["ai_query"] = False

        # ── 12. 소스 삭제 ──────────────────────────────────────────
        section("12. 소스 삭제 (DELETE /api/sources/{id})")
        for stype, sid in uploaded.items():
            try:
                r = c.delete(f"/api/sources/{sid}")
                r.raise_for_status()
                ok(f"DELETE /api/sources/{sid} [{stype}]", r.json().get("status"))
            except Exception as e:
                fail(f"DELETE /api/sources/{sid} [{stype}]", str(e))
        results["delete"] = True

    # ── 최종 요약 ─────────────────────────────────────────────────
    log()
    log(SEP)
    log("  최종 결과")
    log(SEP)
    passed = sum(1 for v in results.values() if v)
    total  = len(results)
    for step, ok_ in results.items():
        status = PASS if ok_ else FAIL
        log(f"  [{status}] {step}")
    log()
    log(f"  {passed}/{total} 통과")
    log(SEP)


def main():
    parser = argparse.ArgumentParser(description="ContiCheck API E2E 테스트")
    parser.add_argument("--url", default="http://localhost:8000", help="백엔드 서버 URL")
    args = parser.parse_args()

    log(SEP)
    log(f"  ContiCheck API E2E 테스트")
    log(f"  서버: {args.url}")
    log(SEP)

    run(args.url)


if __name__ == "__main__":
    main()
