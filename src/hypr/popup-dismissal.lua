-- Passive click dismissal for Quattro's card-sized layer windows.
-- The native focus-grab protocol consumes the first click into the previously
-- focused app on Hyprland 0.56.2. These bindings never consume or replay input.
local function inside(layer, point)
    return point.x >= layer.x and point.x < layer.x + layer.w
        and point.y >= layer.y and point.y < layer.y + layer.h
end

local function dismissOutside()
    local point = hl.get_cursor_pos()
    if not point then return end
    local tokens = {}
    for _, layer in ipairs(hl.get_layers()) do
        if layer.mapped then
            local token = layer.namespace:match("^quattro%-popup%-(%d+%-%d+)$")
            if token then
                if inside(layer, point) then return end
                tokens[#tokens + 1] = token
            elseif layer.namespace == "quattro-bar" and inside(layer, point) then
                -- The bar dispatches buttons synchronously through PopupManager.
                return
            end
        end
    end
    for _, token in ipairs(tokens) do
        -- Only numeric shell-generated identity is interpolated, never UI text.
        hl.exec_cmd("qs ipc call popups dismiss " .. token)
    end
end

local function dismissAll()
    for _, layer in ipairs(hl.get_layers()) do
        local token = layer.mapped and layer.namespace:match("^quattro%-popup%-(%d+%-%d+)$")
        if token then hl.exec_cmd("qs ipc call popups dismiss " .. token) end
    end
end

-- OnDemand allows focus to follow the mouse. Escape still closes the temporary
-- panel, but must not consume application Escape keys when no panel is open.
local escape = hl.bind("Escape", dismissAll, {description = "Close temporary Quattro panel"})
local function updateEscape()
    local active = false
    for _, layer in ipairs(hl.get_layers()) do
        if layer.mapped and layer.namespace:match("^quattro%-popup%-%d+%-%d+$") then active = true end
    end
    escape:set_enabled(active)
end
hl.on("layer.opened", updateEscape)
hl.on("layer.closed", updateEscape)
updateEscape()

for _, button in ipairs({272, 273, 274}) do
    hl.bind("mouse:" .. button, dismissOutside, {
        non_consuming = true,
        ignore_mods = true,
        description = "Dismiss temporary Quattro panel without consuming the click",
    })
end
