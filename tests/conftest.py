import os

os.environ["CACHE_BACKEND"] = "memory"
os.environ["STORE_BACKEND"] = "memory"
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ.pop("REDIS_URL", None)
# The suite makes hundreds of POSTs from one peer; production limits are tested on a dedicated app.
os.environ["RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["RATE_LIMIT_GLOBAL_PER_MINUTE"] = "100000"
