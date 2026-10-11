"""启动 FastAPI + Web 演示。"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("COMPLIANCE_HOST", "127.0.0.1")
    port = int(os.environ.get("COMPLIANCE_PORT", "8000"))
    uvicorn.run("app.api:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
