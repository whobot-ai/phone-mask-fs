--[[
  unmask.lua
  功能：从映射服务查询 Token → 真实手机号，写入 channel variable
  调用时机：dialplan 收到 Token 被叫后，bridge 之前

  依赖：
    - LuaSocket（freeswitch 自带）或系统 curl 命令
    - 环境变量 MASK_SERVICE_URL、GATEWAY_API_KEY

  channel variable 约定：
    输入：destination_number  (tok_xxxx)
    输出：real_phone          (真实手机号，失败时为空)
         unmask_error        (失败原因，成功时为空)
]]

local log_prefix = "[unmask] "

-- ── 读配置（优先 channel var，其次环境变量，最后默认值）──────────

local function get_conf(key, default)
  local val = session:getVariable(key)
  if val and val ~= "" then return val end
  val = os.getenv(key)
  if val and val ~= "" then return val end
  return default
end

local MASK_SERVICE_URL = get_conf("MASK_SERVICE_URL", "http://127.0.0.1:8080")
local GATEWAY_API_KEY  = get_conf("GATEWAY_API_KEY",  "")
local TIMEOUT_SEC      = tonumber(get_conf("UNMASK_TIMEOUT_SEC", "3"))

if GATEWAY_API_KEY == "" then
  freeswitch.consoleLog("ERR", log_prefix .. "GATEWAY_API_KEY 未配置，拒绝处理\n")
  session:setVariable("unmask_error", "missing_api_key")
  return
end

-- ── 取 Token ─────────────────────────────────────────────────────────

local token = session:getVariable("destination_number")

if not token or not token:match("^tok_[a-f0-9]+$") then
  freeswitch.consoleLog("WARNING", log_prefix .. "被叫不是合法Token: " .. tostring(token) .. "\n")
  session:setVariable("unmask_error", "invalid_token_format")
  return
end

freeswitch.consoleLog("INFO", log_prefix .. "查询 token=" .. token:sub(1,16) .. "...\n")

-- ── HTTP 请求（使用 LuaSocket）────────────────────────────────────────

local ok, http = pcall(require, "socket.http")
local ok2, ltn12 = pcall(require, "ltn12")

local phone = nil
local err_reason = nil

if ok and ok2 then
  -- 方案A：LuaSocket（推荐，纯Lua，无子进程）
  local url = MASK_SERVICE_URL .. "/unmask?token=" .. token
  local resp_body = {}

  local res, status_code, headers = http.request({
    url     = url,
    method  = "GET",
    headers = {
      ["X-Gateway-Key"] = GATEWAY_API_KEY,
      ["User-Agent"]    = "FreeSWITCH-MaskGateway/1.0",
    },
    sink    = ltn12.sink.table(resp_body),
    -- LuaSocket 不原生支持 timeout，通过 socket 设置
  })

  local body = table.concat(resp_body)

  if res == nil then
    -- 网络错误（连接拒绝、超时等）
    freeswitch.consoleLog("ERR", log_prefix .. "HTTP请求失败: " .. tostring(status_code) .. "\n")
    err_reason = "http_error"
  elseif status_code == 200 then
    phone = body:match('"phone"%s*:%s*"(%d+)"')
    if not phone then
      freeswitch.consoleLog("ERR", log_prefix .. "响应解析失败 body=" .. body .. "\n")
      err_reason = "parse_error"
    end
  elseif status_code == 404 then
    freeswitch.consoleLog("WARNING", log_prefix .. "Token不存在 token=" .. token:sub(1,16) .. "...\n")
    err_reason = "token_not_found"
  elseif status_code == 410 then
    freeswitch.consoleLog("WARNING", log_prefix .. "Token已过期 token=" .. token:sub(1,16) .. "...\n")
    err_reason = "token_expired"
  elseif status_code == 401 then
    freeswitch.consoleLog("ERR", log_prefix .. "GATEWAY_API_KEY 鉴权失败\n")
    err_reason = "auth_failed"
  else
    freeswitch.consoleLog("ERR", log_prefix .. "未知状态码 status=" .. tostring(status_code) .. "\n")
    err_reason = "unexpected_status_" .. tostring(status_code)
  end

else
  -- 方案B：回退到系统 curl（LuaSocket 不可用时）
  freeswitch.consoleLog("WARNING", log_prefix .. "LuaSocket不可用，回退到curl\n")

  local tmp_file = "/tmp/unmask_" .. token:sub(5, 12) .. ".json"
  local cmd = string.format(
    'curl -sf --max-time %d -H "X-Gateway-Key: %s" "%s/unmask?token=%s" -o %s 2>/dev/null; echo $?',
    TIMEOUT_SEC,
    GATEWAY_API_KEY,
    MASK_SERVICE_URL,
    token,
    tmp_file
  )

  local handle = io.popen(cmd)
  local exit_code = handle and handle:read("*n")
  if handle then handle:close() end

  if exit_code == 0 then
    local f = io.open(tmp_file, "r")
    if f then
      local body = f:read("*a")
      f:close()
      os.remove(tmp_file)
      phone = body:match('"phone"%s*:%s*"(%d+)"')
      if not phone then
        err_reason = "parse_error"
      end
    else
      err_reason = "file_read_error"
    end
  else
    err_reason = "curl_failed_" .. tostring(exit_code)
    os.remove(tmp_file)
  end
end

-- ── 写结果到 channel variable ────────────────────────────────────────

if phone then
  session:setVariable("real_phone", phone)
  session:setVariable("unmask_error", "")
  -- 日志只打末4位，不暴露完整号码
  freeswitch.consoleLog("INFO", log_prefix .. "成功 token=" .. token:sub(1,16) .. "... -> ***" .. phone:sub(-4) .. "\n")
else
  session:setVariable("real_phone", "")
  session:setVariable("unmask_error", err_reason or "unknown")
  freeswitch.consoleLog("ERR", log_prefix .. "失败 token=" .. token:sub(1,16) .. "... reason=" .. tostring(err_reason) .. "\n")
end
