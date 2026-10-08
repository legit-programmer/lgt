from __future__ import annotations

import argparse

import uvicorn

from .runtime import application


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the local multi-agent workspace backend.")
    parser.add_argument("--config", required=True, help="Path to an explicit backend JSON configuration")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(application(args.config), host="127.0.0.1", port=args.port, workers=1,
                proxy_headers=False)


if __name__ == "__main__":
    main()
