from typing import List, Dict, Any, Optional
import uuid
import structlog
from gremlin_python.driver import client, serializer
from gremlin_python.structure.graph import Graph
from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection

logger = structlog.get_logger()

# (추후 intermediate.py 뼈대가 잡히면 import)
# from app.models.intermediate import NormalizationResult
# from app.models.vertices import Source

def create_gremlin_client(endpoint: str, key: str, database: str, container: str):
    """GremlinPython 클라이언트 생성 헬퍼"""
    # Cosmos DB Gremlin 엔드포인트 포맷에 맞게 수정: wss://<account>.gremlin.cosmos.azure.com:443/
    url = endpoint if endpoint.startswith("wss://") else f"wss://{endpoint}:443/"
    
    # gremlinpython은 username에 /dbs/db명/colls/col명 포맷을 요구합니다.
    username = f"/dbs/{database}/colls/{container}"
    
    graph = Graph()
    connection = DriverRemoteConnection(
        url, 
        'g',
        username=username,
        password=key,
        message_serializer=serializer.GraphSONSerializersV2d0()
    )
    g = graph.traversal().withRemote(connection)
    return g, connection

class GremlinGraphService:
    """Azure Cosmos DB (Gremlin API)와 연동하는 메인 서비스"""
    
    def __init__(self, endpoint: str, key: str, database: str, container: str):
        self.endpoint = endpoint
        self.key = key
        self.database = database
        self.container = container
        self.g, self.connection = create_gremlin_client(endpoint, key, database, container)
        logger.info("GremlinGraphService initialized.")

    def _dict_to_properties(self, traversal, data: dict):
        """pydantic model_dump 딕셔너리를 property들로 묶어주는 유틸리티"""
        for k, v in data.items():
            if v is not None:
                # 리스트, 딕셔너리는 문자열화하거나 다중 프로퍼티로 처리할 수 있으나, 
                # Cosmos DB Gremlin의 경우 다중 값 지원이 까다로워 일단 문자열 처리
                if isinstance(v, (list, dict)):
                    traversal = traversal.property(k, str(v))
                else:
                    traversal = traversal.property(k, v)
        return traversal

    # === Vertex CRUD 골격 ===
    def _add_vertex_generic(self, label: str, data: dict, partition_key: str) -> str:
        """범용 Vertex 추가"""
        vid = data.get("id", str(uuid.uuid4()))
        data["id"] = vid

        # g.addV(label).property('id', id).property('pk', partition_key)...
        t = self.g.addV(label).property('id', vid).property(partition_key, partition_key)
        t = self._dict_to_properties(t, data)
        result = t.toList()
        logger.debug(f"Added vertex {label}", vid=vid)
        return vid
        
    def add_character(self, data: dict) -> str:
        return self._add_vertex_generic("character", data, "character")
        
    def add_fact(self, data: dict) -> str:
        return self._add_vertex_generic("fact", data, "fact")
        
    def add_event(self, data: dict) -> str:
        return self._add_vertex_generic("event", data, "event")
        
    def add_trait(self, data: dict) -> str:
        return self._add_vertex_generic("trait", data, "trait")
        
    def add_organization(self, data: dict) -> str:
        return self._add_vertex_generic("organization", data, "organization")

    def add_location(self, data: dict) -> str:
        return self._add_vertex_generic("location", data, "location")
        
    def add_item(self, data: dict) -> str:
        return self._add_vertex_generic("item", data, "item")
        
    def add_source(self, data: dict) -> str:
        return self._add_vertex_generic("source", data, "source")
        
    def add_user_confirmation(self, data: dict) -> str:
        return self._add_vertex_generic("confirmation", data, "confirmation")
    
    # === Edge 추가 골격 ===
    def _add_edge_generic(self, label: str, from_id: str, to_id: str, data: dict) -> str:
        """범용 Edge 추가"""
        eid = data.get("id", str(uuid.uuid4()))
        data["id"] = eid
        
        # g.V(from_id).addE(label).to(g.V(to_id)).property('id', id)...
        t = self.g.V(from_id).addE(label).to(__.V(to_id)).property('id', eid)
        t = self._dict_to_properties(t, data)
        result = t.toList()
        logger.debug(f"Added edge {label}", from_id=from_id, to_id=to_id, eid=eid)
        return eid
        
    def add_learns(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("LEARNS", from_id, to_id, data)
        
    def add_mentions(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("MENTIONS", from_id, to_id, data)
        
    def add_participates_in(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("PARTICIPATES_IN", from_id, to_id, data)
        
    def add_has_status(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("HAS_STATUS", from_id, to_id, data)
        
    def add_at_location(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("AT_LOCATION", from_id, to_id, data)
        
    def add_related_to(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("RELATED_TO", from_id, to_id, data)
        
    def add_belongs_to(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("BELONGS_TO", from_id, to_id, data)
        
    def add_feels(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("FEELS", from_id, to_id, data)
        
    def add_has_trait(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("HAS_TRAIT", from_id, to_id, data)
        
    def add_violates_trait(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("VIOLATES_TRAIT", from_id, to_id, data)
        
    def add_possesses(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("POSSESSES", from_id, to_id, data)
        
    def add_loses(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("LOSES", from_id, to_id, data)
        
    def add_sourced_from(self, from_id: str, to_id: str, data: dict) -> str:
        return self._add_edge_generic("SOURCED_FROM", from_id, to_id, data)
    
    # === 계층 3: Graph 적재 ===
    def materialize(self, normalized_result: Any, source: Any):
        """계층 2에서 출력된 정규화 결과를 Cosmos DB에 실제 적재한다."""
        logger.info("Materializing NormalizedEntity to Cosmos DB Graph")
        try:
            # 1. Vertex 추가 수행
            # 2. Edge 추가 수행
            # 3. _assign_time_axes() 로직 호출
            pass
        except Exception as e:
            logger.error("Error during graph materialization", error=str(e))
            raise e

    # === 임시 그래프 격리 골격 ===
    def snapshot_graph(self, relevant_ids: List[str]):
        """분석에 필요한 부분만 In-Memory로 복제하여 canonical graph를 보호"""
        pass

    def close(self):
        """Clean up remote connection."""
        self.connection.close()

class InMemoryGraphService:
    """테스트용 In-Memory Graph 구현체. 로컬 리스트 및 딕셔너리로 관리"""
    def __init__(self):
        self.vertices = {}
        self.edges = []
        
    def add_character(self, data: dict) -> str:
        cid = data.get("id", str(uuid.uuid4()))
        self.vertices[cid] = {"label": "character", **data}
        return cid

    # ... 다른 헬퍼 메서드들은 구동용 테스트시 추가 ...
