"""One worker keeps in-memory streams and rate limits consistent."""
import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.api.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8005")), workers=1,
                access_log=False, proxy_headers=True,
                forwarded_allow_ips=os.getenv("TRUSTED_PROXY_IPS", "127.0.0.1"), timeout_keep_alive=5,
                limit_concurrency=64, timeout_graceful_shutdown=15)
