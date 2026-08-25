from __future__ import annotations

import os

import uvicorn

from ipi_webview.api.app import create_app


app = create_app()


def main() -> None:
    uvicorn.run(
        "ipi_webview.api.main:app",
        host=os.environ.get("WEBVIEW_API_HOST", "0.0.0.0"),
        port=int(os.environ.get("WEBVIEW_API_PORT", "8000")),
        workers=1,
        reload=False,
    )


if __name__ == "__main__":
    main()
