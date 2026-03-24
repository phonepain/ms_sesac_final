from typing import List, Optional
import json
import os
import structlog
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient

from app.config import settings
from app.models.api import DocumentChunk, EvidenceItem
from app.models.vertices import SourceExcerpt

logger = structlog.get_logger(__name__)

class SearchService:
    def __init__(self):
        self.endpoint = settings.search_endpoint
        self.key = settings.search_key
        # Index name set as a default, could be configured via env
        self.index_name = "conticheck-index"
        
        if not self.endpoint or not self.key or "localhost" in self.endpoint:
            logger.warning("Azure Search endpoint or key not configured properly (or using localhost placeholder). SearchClient will not connect.")
            self.client = None
        else:
            try:
                self.credential = AzureKeyCredential(self.key)
                self.client = SearchClient(endpoint=self.endpoint,
                                           index_name=self.index_name,
                                           credential=self.credential)
            except Exception as e:
                logger.error("Failed to initialize SearchClient", error=str(e))
                self.client = None

    async def index_chunks(self, source_id: str, chunks: List[DocumentChunk]):
        if not self.client:
            logger.error("SearchClient not initialized. Cannot index.")
            return

        documents = []
        for chunk in chunks:
            # Map DocumentChunk to Azure Search document fields
            doc = {
                "id": chunk.id,
                "source_id": chunk.source_id,
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "source_name": chunk.location.source_name,
                "page": chunk.location.page,
                "chapter": chunk.location.chapter,
                "line_range": f"{chunk.location.line_range[0]}-{chunk.location.line_range[1]}" if chunk.location.line_range else None
            }
            documents.append(doc)
            
        try:
            result = self.client.upload_documents(documents=documents)
            logger.info("Indexed chunks", source_id=source_id, count=len(result))
        except Exception as e:
            logger.error("Failed to index chunks", error=str(e), source_id=source_id)

    async def search_context(self, query: str, top_k: int = 5) -> List[EvidenceItem]:
        if not self.client:
            logger.error("SearchClient not initialized. Cannot search.")
            return []
            
        try:
            results = self.client.search(search_text=query, top=top_k)
            evidence_list = []
            for result in results:
                location_str = result.get("chapter") or ""
                if result.get("page"):
                    location_str += f" p.{result.get('page')}"
                if result.get("line_range"):
                    location_str += f" lines {result.get('line_range')}"
                    
                evidence = EvidenceItem(
                    source_name=result.get("source_name", "Unknown"),
                    source_location=location_str.strip(),
                    text=result.get("content", "")
                )
                evidence_list.append(evidence)
            return evidence_list
        except Exception as e:
            logger.error("Failed to search context", error=str(e), query=query)
            return []

    async def get_source_excerpts(self, entity_ids: List[str]) -> List[SourceExcerpt]:
        if not self.client or not entity_ids:
            return []

        try:
            id_list = ",".join(entity_ids)
            filter_query = f"search.in(id, '{id_list}', ',')"

            results = self.client.search(search_text="*", filter=filter_query)
            excerpt_list = []
            for result in results:
                location_str = result.get("chapter") or ""
                if result.get("page"):
                    location_str += f" p.{result.get('page')}"
                if result.get("line_range"):
                    location_str += f" lines {result.get('line_range')}"

                excerpt = SourceExcerpt(
                    source_name=result.get("source_name", "Unknown"),
                    source_location=location_str.strip(),
                    text=result.get("content", "")
                )
                excerpt_list.append(excerpt)
            return excerpt_list
        except Exception as e:
            logger.error("Failed to get source excerpts", error=str(e))
            return []

    async def remove_source(self, source_id: str):
        if not self.client:
            return

        try:
            results = self.client.search(search_text="*", filter=f"source_id eq '{source_id}'", select="id", top=1000)
            docs_to_delete = [{"id": r["id"]} for r in results]

            if docs_to_delete:
                self.client.delete_documents(documents=docs_to_delete)
                logger.info("Removed source documents", source_id=source_id, count=len(docs_to_delete))
        except Exception as e:
            logger.error("Failed to remove source", error=str(e))

    async def reset_index(self) -> None:
        """인덱스를 삭제하고 JSON 정의로 재생성합니다 (데이터 초기화)."""
        if not self.endpoint or not self.key:
            logger.warning("SearchService not configured, skipping reset_index")
            return
        try:
            from azure.search.documents.indexes import SearchIndexClient
            from azure.search.documents.indexes.models import SearchIndex

            index_client = SearchIndexClient(
                endpoint=self.endpoint,
                credential=AzureKeyCredential(self.key)
            )

            # 인덱스 삭제
            try:
                index_client.delete_index(self.index_name)
                logger.info("search_index_deleted", index=self.index_name)
            except Exception as e:
                logger.warning("search_index_delete_skipped", error=str(e))

            # JSON 파일로 재생성
            json_path = os.path.join(
                os.path.dirname(__file__), "..", "..", "..", "docs", "azure-search-index.json"
            )
            json_path = os.path.normpath(json_path)
            if os.path.exists(json_path):
                with open(json_path, "r", encoding="utf-8") as f:
                    index_def = json.load(f)
                index = SearchIndex.deserialize(index_def)
                index_client.create_index(index)
                logger.info("search_index_recreated", index=self.index_name)
                # SearchClient 재초기화
                self.client = SearchClient(
                    endpoint=self.endpoint,
                    index_name=self.index_name,
                    credential=AzureKeyCredential(self.key)
                )
            else:
                logger.warning("index_json_not_found", path=json_path)
        except Exception as e:
            logger.error("reset_index_failed", error=str(e))
            raise


class MockSearchService:
    def __init__(self):
        self.chunks: List[DocumentChunk] = []
        logger.info("Initialized MockSearchService")

    async def index_chunks(self, source_id: str, chunks: List[DocumentChunk]):
        self.chunks.extend(chunks)
        logger.info("Mock indexed chunks", source_id=source_id, count=len(chunks))

    async def search_context(self, query: str, top_k: int = 5) -> List[EvidenceItem]:
        logger.info("Mock searching context", query=query, top_k=top_k)
        
        # Simple keyword matching
        query_words = query.lower().split()
        
        # Score chunks
        scored_chunks = []
        for chunk in self.chunks:
            content_lower = chunk.content.lower()
            score = sum(1 for word in query_words if word in content_lower)
            if score > 0:
                scored_chunks.append((score, chunk))
                
        # Sort by score descending
        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        
        evidence_list = []
        for _, chunk in scored_chunks[:top_k]:
            location_str = chunk.location.chapter or ""
            if chunk.location.page:
                location_str += f" p.{chunk.location.page}"
            if chunk.location.line_range:
                location_str += f" lines {chunk.location.line_range[0]}-{chunk.location.line_range[1]}"
                
            evidence = EvidenceItem(
                source_name=chunk.location.source_name,
                source_location=location_str.strip(),
                text=chunk.content
            )
            evidence_list.append(evidence)
            
        return evidence_list

    async def get_source_excerpts(self, entity_ids: List[str]) -> List[SourceExcerpt]:
        logger.info("Mock getting source excerpts", entity_ids=entity_ids)
        excerpt_list = []

        for chunk in self.chunks:
            if chunk.id in entity_ids:
                location_str = chunk.location.chapter or ""
                if chunk.location.page:
                    location_str += f" p.{chunk.location.page}"
                if chunk.location.line_range:
                    location_str += f" lines {chunk.location.line_range[0]}-{chunk.location.line_range[1]}"

                excerpt = SourceExcerpt(
                    source_name=chunk.location.source_name,
                    source_location=location_str.strip(),
                    text=chunk.content
                )
                excerpt_list.append(excerpt)

        return excerpt_list

    async def remove_source(self, source_id: str):
        original_count = len(self.chunks)
        self.chunks = [c for c in self.chunks if c.source_id != source_id]
        logger.info("Mock removed source", source_id=source_id, removed=original_count - len(self.chunks))

    async def reset_index(self) -> None:
        self.chunks = []
        logger.info("MockSearchService index reset")


_search_service = None

def get_search_service():
    global _search_service
    if _search_service is None:
        if settings.use_mock_search:
            _search_service = MockSearchService()
        else:
            _search_service = SearchService()
    return _search_service
