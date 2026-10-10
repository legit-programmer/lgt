from __future__ import annotations

import argparse

import uvicorn

from .runtime import application
from .runtime import load_config
from .daemon import DaemonServer, DaemonState, configure_daemon_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the local multi-agent workspace backend.")
    parser.add_argument("--config", required=True, help="Path to an explicit backend JSON configuration")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--daemon", action="store_true", help="Serve a token-protected daemon for a detached desktop launcher")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    if args.daemon:
        data_dir = load_config(args.config).settings.data_dir
        configure_daemon_logging(data_dir)
        daemon = DaemonState(data_dir)
        server = DaemonServer(uvicorn.Config(
            application(args.config, daemon=daemon), host="127.0.0.1", port=args.port,
            workers=1, proxy_headers=False, log_config=None, use_colors=False,
            timeout_graceful_shutdown=10,
        ), daemon)
        try:
            server.run()
        finally:
            daemon.remove()
        return
    uvicorn.run(application(args.config), host="127.0.0.1", port=args.port, workers=1,
                proxy_headers=False)


if __name__ == "__main__":
    main()
