# graph.py
from app.models.vertices import BaseVertex
from app.models.edges import BaseEdge

class GraphService:
    async def upsert_node(self, node: BaseVertex):
        """계층 3: Cosmos DB(Gremlin)에 노드 추가/업데이트"""
        # TODO: A님이 Cosmos DB 연동 로직 작성
        pass

    async def create_relationship(self, edge: BaseEdge):
        """계층 3: 노드 간 엣지 연결"""
        # TODO: A님이 Gremlin 쿼리 작성
        pass