-- Native A2DP is unavailable while our HFP owner holds the controller.
-- Answer UI queries immediately; never open a controller, pair, scan or play.
local lib = require('liblipclua')
local h = assert(lib.init('com.lab126.btfd'))
local held = {}
local values = {isAudibleAvailable=tonumber(arg[1]) or 0,
    hasNeverPaired=0, isBtchQueuedOrRunning=0, isBtchRunning=0,
    BTstate=0, currentBTOperatingMode=0, kt3HfpOwner=1}
for name, value in pairs(values) do
    local p = h:register_int_property(name, 'r')
    p.value = value
    held[#held+1] = p
end
local name = h:register_string_property('BTconnectedDevName', 'r')
name.value = ''
held[#held+1] = name
io.stdout:write('BT_QUERY_SERVICE_READY\n')
io.stdout:flush()
-- The binding unrefs its asynchronous watcher. A bare event loop returns
-- immediately when idle; a timed loop keeps this publisher alive for queries.
while true do lib.run_event_loop(60) end
