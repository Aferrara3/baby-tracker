from fastapi import FastAPI, Request, Depends
from starlette.middleware.base import BaseHTTPMiddleware
import uvicorn
import time

app = FastAPI()

class LogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        end = time.time()
        username = getattr(request.state, "username", "anonymous")
        print(f"[{username}] {request.method} {request.url.path} ({(end - start)*1000:.2f}ms)")
        return response

app.add_middleware(LogMiddleware)

def set_user(request: Request):
    request.state.username = "testuser"

@app.get("/", dependencies=[Depends(set_user)])
def read_root():
    return {"Hello": "World"}

if __name__ == "__main__":
    import asyncio
    async def run_server():
        config = uvicorn.Config(app=app, host="127.0.0.1", port=8000, access_log=False)
        server = uvicorn.Server(config)
        asyncio.create_task(server.serve())
        await asyncio.sleep(1)
        import httpx
        async with httpx.AsyncClient() as client:
            await client.get("http://127.0.0.1:8000/")
        await asyncio.sleep(1)
        # server.should_exit = True
    asyncio.run(run_server())
