from fastapi import FastAPI
from app.config import settings

app = FastAPI(
    title=settings.app_name,
    description="시나리오 정합성 검증 시스템 POC (ContiCheck) 백엔드",
    version="0.1.0",
)

@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": settings.app_name}

# 기타 라우터들은 차후 단계(Phase 7)에서 추가될 예정입니다.
