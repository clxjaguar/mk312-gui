-- subsync.lua by @cLxJaguar (2023)
-- place this script in ~/.config/mpv/scripts/ and get the subtitles content by UDP packets to
-- synchronise things with video with MPV. Script activation is done by pressing Ctrl+X.
-- You may need to type "sudo apt-get install lua-socket"

local dest_ip = '127.0.0.1'
local dest_port = 50000

local utils = require 'mp.utils'
local socket = require "socket"
local udp = socket.udp()
local enabled = false
local firstEnable = true

mp.observe_property("sub-text","string", function(prop,txt)
	local playing = not mp.get_property_native("pause")
	if enabled and playing and txt ~= nil then
		udp:send(txt.."\n")
		print(txt)
	end
end)

mp.observe_property("pause","bool", function(prop, paused)
	if enabled and paused then
		udp:send("\n")
		print("paused.")
	end
end)

mp.add_key_binding("Ctrl+x","toggle-tts-commands", function()
	enabled = not enabled

	if enabled then
		if firstEnable then
			udp:settimeout(0)
			udp:setpeername(dest_ip, dest_port)
			firstEnable = false
		end

		mp.osd_message("Subtitle to UDP enabled ("..dest_ip..":"..dest_port..")")
		mp.set_property_native("sub-color", "#0000FF00")
		mp.set_property_native("sub-border-color", "#0000FF00")
		mp.command("no-osd set sub-visibility yes")
	else
		mp.osd_message("Subtitle to UDP disabled")
		mp.set_property_native("sub-color", "#FFFFFFFF")
		mp.set_property_native("sub-border-color", "#FF000000")
    end
end)
