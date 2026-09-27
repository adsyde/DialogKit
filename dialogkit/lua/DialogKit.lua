-- DialogKit: выбор варианта правленых диалогов при загрузке (сервер и клиент). Общий для всех модов на
-- DialogKit (Team Effort, SuccubusPlus, …): каждый кладёт этот файл к себе и зовёт DialogKit.Apply.
--
-- Правило: каждый мод работает один. Если включены два мода на DialogKit и оба правят диалог, подменяет
-- ровно один — тот, что позже в порядке загрузки (его банк диалогов всё равно победит), и берёт вариант
-- «all» со всеми правками; второй для этого диалога ничего не делает. Если включён мод-база (например,
-- If Fate Chose Differently), который сам подменяет этот диалог, берётся вариант поверх его версии
-- («own@UUID» / «all@UUID»), а если база позже нас в порядке загрузки — подменяется и её файл.
-- Без Script Extender работает вариант «own» из нашего банка диалогов. Диалоги, которые подменяет мод-база,
-- в наш банк не входят (bank = false): их подменяем только отсюда, чтобы никогда не затереть правки базы.

local DialogKit = {}

local function order()
    local out = {}
    for i, u in ipairs(Ext.Mod.GetLoadOrder()) do
        out[u] = i
    end
    return out
end

local function override(from, to, log)
    if from ~= to then
        Ext.IO.AddPathOverride(from, to)
        log("%s -> %s", from, to)
    end
end

-- me: UUID нашего мода; manifest: таблица из DialogKit (lua_manifest); log(fmt, ...) — журнал или nil.
function DialogKit.Apply(me, manifest, log)
    log = log or function() end
    local mod = Ext.Mod.GetMod(me)
    local folder = mod and mod.Info and mod.Info.Directory
    if not folder then
        log("DialogKit: не нашёл папку мода %s", me)
        return
    end
    local pos = order()
    local mine = pos[me] or 0
    local function fix(p)
        return p and (p:gsub("{MOD}", folder)) or nil
    end
    for _, d in ipairs(manifest) do
        local withPartner, partnerLater = false, false
        for _, p in ipairs(d.partners or {}) do
            if Ext.Mod.IsModLoaded(p) then
                withPartner = true
                if (pos[p] or 0) > mine then
                    partnerLater = true
                end
            end
        end
        if partnerLater then
            log("%s: подменяет мод-партнёр (он позже в порядке загрузки)", d.name)
        else
            local base = nil
            for u in pairs(d.bases or {}) do
                if Ext.Mod.IsModLoaded(u) then
                    base = u
                end
            end
            local suffix = base and ("@" .. base) or ""
            local want = (withPartner and "all" or "own") .. suffix
            local v = d.variants[want] or d.variants["own" .. suffix] or d.variants.own
            if not d.variants[want] then
                log("%s: нет варианта %s (партнёр собран без нас?) — беру ближайший", d.name, want)
            end
            local own = d.variants.own
            if d.bank ~= false then
                -- диалог в нашем банке: игра грузит наш файл (если наш банк главнее), подменяем его
                override(fix(own.dialog), fix(v.dialog), log)
                if own.timeline and v.timeline then
                    override(fix(own.timeline), fix(v.timeline), log)
                end
                if base and (pos[base] or 0) > mine then   -- банк базы победит наш: подменяем и её файлы
                    override(d.bases[base].dialog, fix(v.dialog), log)
                    if d.bases[base].timeline and v.timeline then
                        override(d.bases[base].timeline, fix(v.timeline), log)
                    end
                end
            else
                -- диалог мода-базы не в нашем банке: игра грузит файл базы (или игры) — подменяем его
                local from = base and d.bases[base] or d.vanilla
                override(from.dialog, fix(v.dialog), log)
                if from.timeline and v.timeline then
                    override(from.timeline, fix(v.timeline), log)
                end
            end
        end
    end
end

return DialogKit
