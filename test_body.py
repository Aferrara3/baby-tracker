from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
import uvicorn
import asyncio
import httpx
import threading

app = FastAPI()

class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        body = b""
        if request.method == "POST":
            body = await request.body()
        
        # Starlette workaround for consumed body
        if request.method == "POST":
            async def receive():
                return {"type": "http.request", "body": body}
            request._receive = receive

        response = await call_next(request)
        return response

app.add_middleware(AccessLogMiddleware)

@app.post("/test")
async def test_endpoint(request: Request):
    data = await request.json()
    return {"received": data}

if __name__ == "__main__":
    def run_server():
        uvicorn.run(app, host="127.0.0.1", port=8010, access_log=False)
    
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    
    import time
    time.sleep(1)
    
    async def test():
        async with httpx.AsyncClient() as client:
            resp = await client.post("http://127.0.0.1:8010/test", json={"hello": "world"})
            print(resp.status_code, resp.json())
            
    asyncio.run(test())
