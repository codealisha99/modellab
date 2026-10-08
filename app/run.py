"""One worker keeps in-memory streams and rate limits consistent."""
import os

import uvicorn


class Server(uvicorn.Server):
    """Ends open event streams as soon as a stop signal arrives.

    Uvicorn waits for open connections before running lifespan shutdown, so an SSE client
    would otherwise hold a redeploy until ``timeout_graceful_shutdown`` expires.
    """

    def handle_exit(self, sig, frame):
        from .api.main import streams

        try:
            streams.begin_shutdown()
        except RuntimeError:  # no running loop (signal before startup); nothing to wake
            pass
        super().handle_exit(sig, frame)


def build_server() -> Server:
    config = uvicorn.Config(
        "app.api.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8005")), workers=1,
        access_log=False, proxy_headers=True,
        forwarded_allow_ips=os.getenv("TRUSTED_PROXY_IPS", "127.0.0.1"), timeout_keep_alive=5,
        limit_concurrency=64, timeout_graceful_shutdown=15,
    )
    return Server(config)


if __name__ == "__main__":
    build_server().run()
