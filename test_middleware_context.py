import asyncio
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from context import user_context

app = FastAPI()

class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Reset context var at start of request
        token = user_context.set("-")
        try:
            response = await call_next(request)
            username = user_context.get()
            print(f"Inside dispatch after call_next: {username}")
        finally:
            username = user_context.get()
            print(f"[{username}] {request.method} {request.url.path}")
            user_context.reset(token)
        return response

app.add_middleware(AccessLogMiddleware)

@app.get("/login")
async def login(request: Request):
    user_context.set("alice")
    request.state.username = "alice"
    print(f"Inside handler: {user_context.get()}")
    return {"ok": True}

if __name__ == "__main__":
    import httpx
    import uvicorn
    import threading
    import time
    
    def run():
        uvicorn.run(app, host="127.0.0.1", port=8011, access_log=False)
        
    t = threading.Thread(target=run, daemon=True)
    t.start()
    time.sleep(1)
    
    async def main():
        async with httpx.AsyncClient() as client:
            await client.get("http://127.0.0.1:8011/login")
            
    asyncio.run(main())
