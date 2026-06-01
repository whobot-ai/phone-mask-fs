--[[
  check_mask_service.lua
  功能：启动时检查映射服务是否可达，打印配置摘要
  用法：在 freeswitch.xml 的 <startup_script> 里调用
        或手动执行：fs_cli -x "luarun check_mask_service.lua"
]]

local MASK_SERVICE_URL = os.getenv("MASK_SERVICE_URL") or "http://127.0.0.1:8080"
local GATEWAY_API_KEY  = os.getenv("GATEWAY_API_KEY")  or ""

freeswitch.consoleLog("INFO", "=== 映射服务健康检查 ===\n")
freeswitch.consoleLog("INFO", "MASK_SERVICE_URL = " .. MASK_SERVICE_URL .. "\n")
freeswitch.consoleLog("INFO", "GATEWAY_API_KEY  = " .. (GATEWAY_API_KEY ~= "" and "已配置(***" .. GATEWAY_API_KEY:sub(-4) .. ")" or "!! 未配置 !!") .. "\n")

-- 尝试调用 /health
local ok, http  = pcall(require, "socket.http")
local ok2, ltn12 = pcall(require, "ltn12")

if not ok or not ok2 then
  freeswitch.consoleLog("WARNING", "LuaSocket 不可用，跳过连通性检查\n")
  return
end

local resp_body = {}
local res, code = http.request({
  url    = MASK_SERVICE_URL .. "/health",
  method = "GET",
  sink   = ltn12.sink.table(resp_body),
})

if res and code == 200 then
  freeswitch.consoleLog("INFO", "映射服务连通正常 ✓\n")
else
  freeswitch.consoleLog("ERR", "映射服务不可达！code=" .. tostring(code) .. " 请检查服务是否启动\n")
end

freeswitch.consoleLog("INFO", "========================\n")
