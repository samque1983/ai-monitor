from fastapi import FastAPI

app = FastAPI(title="交易领航员 Agent")


@app.get("/health")
def health():
    return {"status": "ok"}
