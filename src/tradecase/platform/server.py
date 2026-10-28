from tradecase.platform.api import create_app

app = create_app()
if __name__ == "__main__":
    import os

    import uvicorn

    uvicorn.run(
        "tradecase.platform.server:app",
        host=os.getenv("TRADECASE_HOST", "127.0.0.1"),
        port=int(os.getenv("TRADECASE_PORT", "8000")),
    )
