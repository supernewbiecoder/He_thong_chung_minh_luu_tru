"""Điểm vào dịch vụ khách. `python -m client`"""
import logging, os
from typing import Any
import uvicorn
from fastapi import FastAPI


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "info").upper(),
                        format="%(asctime)s %(levelname)s [client] %(message)s")
    app = FastAPI(title="engram-client", version="0.1.0")

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {"service": "client", "name": os.getenv("CLIENT_NAME", "Chi")}

    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="warning")


if __name__ == "__main__":
    main()
