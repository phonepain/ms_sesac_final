"""
Azure 테스트 데이터 정리 스크립트
- Blob Storage: conticheck-uploads 컨테이너에서 테스트 파일 삭제
- Cosmos DB: Gremlin 그래프 전체 vertex/edge 삭제
- AI Search: conticheck-index 인덱스 문서 삭제

사용법:
    python scripts/azure_cleanup.py
    python scripts/azure_cleanup.py --cosmos-only
    python scripts/azure_cleanup.py --blob-only
    python scripts/azure_cleanup.py --search-only
"""
import sys
import os
import argparse
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings

SEP  = "=" * 60
DASH = "-" * 60

# 정리 대상 source_id 목록
TARGET_SOURCE_IDS = [
    "azure-test-worldview",
    "azure-test-settings",
    "azure-test-scenario",
]


def log(msg=""):
    print(msg, flush=True)


def clean_blob_storage():
    log(DASH)
    log("[Blob Storage] 파일 삭제")
    log(DASH)
    try:
        from azure.storage.blob import BlobServiceClient
        client = BlobServiceClient.from_connection_string(
            settings.AZURE_STORAGE_CONNECTION_STRING
        )

        for container_name in [
            settings.AZURE_STORAGE_CONTAINER_UPLOADS,
            settings.AZURE_STORAGE_CONTAINER_VERSIONS,
        ]:
            log(f"  컨테이너: {container_name}")
            try:
                container = client.get_container_client(container_name)
                deleted = 0
                for sid in TARGET_SOURCE_IDS:
                    blobs = list(container.list_blobs(name_starts_with=sid))
                    for blob in blobs:
                        container.delete_blob(blob.name)
                        log(f"    삭제: {blob.name}")
                        deleted += 1
                if deleted == 0:
                    log(f"    (삭제할 파일 없음)")
                else:
                    log(f"    총 {deleted}개 파일 삭제 완료")
            except Exception as e:
                log(f"    ERR: {e}")
        log()
        return True
    except Exception as e:
        log(f"  ERR Blob Storage 연결 실패: {e}")
        log()
        return False


def clean_cosmos_db():
    log(DASH)
    log("[Cosmos DB] Gremlin 그래프 전체 삭제")
    log(DASH)
    try:
        from gremlin_python.driver import client as gc, serializer

        for graph_name in [settings.cosmos_graph_ws, settings.cosmos_graph_sc]:
            log(f"  그래프: {graph_name}")
            try:
                t0 = time.time()
                gremlin = gc.Client(
                    settings.cosmos_endpoint,
                    "g",
                    username=f"/dbs/{settings.cosmos_database}/colls/{graph_name}",
                    password=settings.cosmos_key,
                    message_serializer=serializer.GraphSONSerializersV2d0(),
                )
                # 현재 vertex 수 확인
                count_before = gremlin.submit("g.V().count()").all().result()[0]
                log(f"    삭제 전 Vertex 수: {count_before}")

                if count_before > 0:
                    # Cosmos DB는 한 번에 전체 drop 가능
                    gremlin.submit("g.V().drop()").all().result()
                    count_after = gremlin.submit("g.V().count()").all().result()[0]
                    log(f"    삭제 후 Vertex 수: {count_after}")
                    log(f"    {count_before - count_after}개 vertex/edge 삭제 완료 ({time.time()-t0:.2f}s)")
                else:
                    log(f"    (삭제할 데이터 없음)")

                gremlin.close()
            except Exception as e:
                log(f"    ERR: {e}")

        log()
        return True
    except Exception as e:
        log(f"  ERR Cosmos DB 연결 실패: {e}")
        log()
        return False


def clean_ai_search():
    log(DASH)
    log("[AI Search] 인덱스 문서 삭제")
    log(DASH)
    try:
        from azure.search.documents import SearchClient
        from azure.core.credentials import AzureKeyCredential

        search = SearchClient(
            endpoint=settings.search_endpoint,
            index_name="conticheck-index",
            credential=AzureKeyCredential(settings.search_key),
        )

        total_deleted = 0
        for sid in TARGET_SOURCE_IDS:
            log(f"  source_id={sid} 검색 중...")
            try:
                results = list(search.search(
                    search_text="*",
                    filter=f"source_id eq '{sid}'",
                    select=["id"],
                    top=1000,
                ))
                if results:
                    search.delete_documents(documents=[{"id": r["id"]} for r in results])
                    log(f"    {len(results)}개 문서 삭제 완료")
                    total_deleted += len(results)
                else:
                    log(f"    (삭제할 문서 없음)")
            except Exception as e:
                log(f"    ERR: {e}")

        if total_deleted > 0:
            log(f"  총 {total_deleted}개 문서 삭제 완료")
        log()
        return True
    except Exception as e:
        log(f"  ERR AI Search 연결 실패: {e}")
        log()
        return False


def main():
    parser = argparse.ArgumentParser(description="Azure 테스트 데이터 정리")
    parser.add_argument("--blob-only",   action="store_true", help="Blob Storage만 삭제")
    parser.add_argument("--cosmos-only", action="store_true", help="Cosmos DB만 삭제")
    parser.add_argument("--search-only", action="store_true", help="AI Search만 삭제")
    args = parser.parse_args()

    run_all    = not (args.blob_only or args.cosmos_only or args.search_only)
    run_blob   = run_all or args.blob_only
    run_cosmos = run_all or args.cosmos_only
    run_search = run_all or args.search_only

    log(SEP)
    log("Azure 테스트 데이터 정리")
    log(SEP)
    log(f"  대상 source_id: {TARGET_SOURCE_IDS}")
    log(f"  Blob={run_blob}  Cosmos={run_cosmos}  Search={run_search}")
    log()

    results = {}

    if run_blob:
        results["Blob Storage"] = clean_blob_storage()

    if run_cosmos:
        results["Cosmos DB"] = clean_cosmos_db()

    if run_search:
        results["AI Search"] = clean_ai_search()

    log(SEP)
    log("정리 완료 요약")
    log(SEP)
    for svc, ok in results.items():
        status = "OK  " if ok else "FAIL"
        log(f"  [{status}] {svc}")


if __name__ == "__main__":
    main()
