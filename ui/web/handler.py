# ui/web/handler.py

import pwnisher
def Handler(config, agent, app):
    from fastapi import APIRouter
    from fastapi.responses import JSONResponse

    router = APIRouter()

    @router.get("/api/wifi")
    async def get_wifi():
        print("PROVA")
        try:
            print("QUI1")
            aps = [
                        ap for ap in pwnisher.known_aps.values()
                        if ap.get("AT_visible", False)
                    ]
            return {"aps": aps}
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)
        
    
    @router.get("/api/access_points")
    async def get_access_points():
        # Prendi la lista attuale degli AP dall’agent
        aps = agent.get_access_points()
        return JSONResponse(content=aps)

    app.include_router(router)
