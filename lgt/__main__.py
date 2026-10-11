from __future__ import annotations

import argparse

import uvicorn

from .runtime import application
from .runtime import load_config
from .daemon import DaemonServer, DaemonState, configure_daemon_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the local multi-agent workspace backend.")
    parser.add_argument("--config", required=True, help="Path to an explicit backend JSON configuration")
    parser.add_argument("--port", type=int, help="Override settings.listen_port")
    parser.add_argument("--daemon", action="store_true", help="Serve a token-protected daemon for a detached desktop launcher")
    args = parser.parse_args()
    config = load_config(args.config)
    port = config.settings.listen_port if args.port is None else args.port
    host = config.settings.listen_host
    if not 0 <= port <= 65535:
        parser.error("--port must be between 0 and 65535")
    # A remote listener cannot accidentally expose the development API.
    if args.daemon or host != "127.0.0.1":
        data_dir = config.settings.data_dir
        configure_daemon_logging(data_dir)
        daemon = DaemonState(data_dir)
        server = DaemonServer(uvicorn.Config(
            application(args.config, daemon=daemon), host=host, port=port,
            workers=1, proxy_headers=False, log_config=None, use_colors=False,
            timeout_graceful_shutdown=10,
        ), daemon)
        try:
            server.run()
        finally:
            daemon.remove()
        return
    uvicorn.run(application(args.config), host=host, port=port, workers=1,
                proxy_headers=False)


if __name__ == "__main__":
    main()
