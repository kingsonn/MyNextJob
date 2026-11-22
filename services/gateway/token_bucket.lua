-- Atomic token bucket. KEYS[1] is the bucket. ARGV: now_ms, rate, window_ms, requested.
local key = KEYS[1]
local now_ms = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local window_ms = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])
local data = redis.call("HMGET", key, "tokens", "updated_ms")
local tokens = tonumber(data[1])
local updated_ms = tonumber(data[2])
if tokens == nil then
  tokens = rate
  updated_ms = now_ms
end
local elapsed = math.max(0, now_ms - updated_ms)
tokens = math.min(rate, tokens + (elapsed * rate / window_ms))
local allowed = 0
local retry_after_ms = 0
if tokens >= requested then
  tokens = tokens - requested
  allowed = 1
else
  retry_after_ms = math.ceil(((requested - tokens) * window_ms) / rate)
end
redis.call("HMSET", key, "tokens", tokens, "updated_ms", now_ms)
redis.call("PEXPIRE", key, window_ms)
return {allowed, retry_after_ms}
