-- mainMenuTabsData.lua
--
-- Tab/button data for the MainMenu. MAX_TABS matches the career mode
-- framework's original capacity (7) so the ButtonFrame, animation
-- indices, and axisXConfigs are all identical to the career screen.
--
--   Tab1 = Quick Match  — home tab, content is hardcoded in Tabs.layout's
--                         QuickMatchFrame panel, no button data needed here.
--   Tab2 = Career       — Career Mode tile (no save) OR, once a manager
--                         save is found, three tiles in order:
--                           1) Load Career   — resume the save
--                           2) stats panel   — read-only league position
--                           3) Career Mode   — start a brand new career
--   Tab3 = Tournaments  — same pattern, mirrored for tourney saves.
--   Tab4 = League       — single-league season branch with no finances.
--   Tab5 = Customize    — squad / player data editor.
--   Tab6 = Volta        — 5v5 street football. Same hardcoded QuickMatchFrame
--                         panel as Tab1 (team + kit pick), no button data. The
--                         match it launches is armed as Volta for that one
--                         match only (see MainHub.lua PlayMatch and
--                         ClassicMatch/PlayMatch/Match.lua setTeams).
--
-- Buttons 1 and 2 only ever exist together (both tied to the same save);
-- button 3 (or button 1 when there's no save) is always the plain,
-- unmodified mode tile so starting fresh is never one click away from
-- accidentally overwriting a save.
--
-- Dynamic refresh
-- ----------------
-- This used to be a fixed table built once at require time. It's now a
-- small builder (reset / applySave) that MainHub.lua calls every time it
-- checks /Save/Save.lua, so the buttons always reflect whatever's on disk
-- right now instead of whatever existed the moment this file first ran.
--
-- The two canonical tiles below (CareerModeBtn / TournamentModeBtn) are
-- never mutated in place — applySave() always builds fresh wrapper
-- tables around them — so calling reset()/applySave() repeatedly (e.g.
-- the player backs out to the main menu several times in one app
-- session) can never leave stale or duplicated entries behind.

local tabsData = {}
tabsData.data = {}
tabsData.tabs = {}

tabsData.MAX_TABS = 7

-- pt-BR (R98e): Career is the first tab, Quick Match the second (src/variants/pt-BR/patches/57-careerfirst.patch.js)
tabsData.tabs["default"] = { "Career", "Quick Match", "Tournaments", "League", "Customize", "Volta" }

-- Tabs that show the QuickMatchFrame panel instead of mode tiles.
tabsData.VOLTA_TAB = 6
tabsData.matchTabs = { [2] = true, [6] = true }
-- the tab that shows each mode's tiles (MainHub.lua puts the Load tiles of the other save slots there too)
tabsData.TAB_OF = { manager = "Tab1", player = "Tab1", tourney = "Tab3", league = "Tab4" }

local CareerModeBtn = {
    name    = "Career Mode",
    imgSrc  = "$Icon_Team_Cup",
    subInfo = "Manager Career",
    desc    = "Manage your club across the full career framework",
    start   = true,   -- a start-fresh tile: other modes' Load tiles go before it (MainHub.lua prismLoadTiles)
    event   = function(self) self.mainHub:enterCareerMode("manager") end
}

-- Player Career (PrismPro): create your player, or play as one of the club's squad. Shares the Career tab with the
-- manager career; its saves load from the same tab.
local PlayerCareerBtn = {
    name    = "Player Career",
    imgSrc  = "$Icon_Team_Cup",
    subInfo = "Be a Pro",
    desc    = "Create your player and build a career, one match at a time",
    start   = true,
    event   = function(self) self.mainHub:enterCareerMode("player") end
}

local TournamentModeBtn = {
    name    = "Tournament Mode",
    imgSrc  = "$Icon_Setting_Cup",
    subInfo = "Tournaments",
    desc    = "Pick a team and battle through a single tournament bracket",
    event   = function(self) self.mainHub:enterCareerMode("tourney") end
}

local CustomizeEditBtn = {
    name = "Edit Mode",
    imgSrc = "$Icon_Team_Cup",
    subInfo = "Squads / Player Data",
    desc = "Edit players, numbers, captain and club transfers",
    event = "evt_customize_edit"
}

-- Prism: entry tile for the new front-end layer. Opens a Prism screen as an
-- overlay through the same engine event the career team selector uses
-- (evt_show_overlay), so nothing in MainHub.nav changes. Remove this tile
-- (and its line in reset() below) to take Prism out of the menu again.
local PrismCareerBtn = {
    name    = "Career Hub",
    imgSrc  = "$Icon_Setting_Cup",
    subInfo = "New Prism UI",
    desc    = "FC-style career hub, squad hub and player profile built on the Prism UI layer",
    event   = function(self)
        local nav = self.nav or (self.mainHub and self.mainHub.nav)
        if nav then
            nav.Event(nil, "evt_show_overlay", {
                vvm  = "/flows/prism/screens/CareerHub/CareerHub.vvm",
                data = { nav = nav }
            })
        end
    end
}

local LeagueModeBtn = {
    name    = "League Mode",
    imgSrc  = "$Icon_Team_Cup",
    subInfo = "League",
    desc    = "Pick a league and club, then play a full league-only season",
    event   = function(self) self.mainHub:enterCareerMode("league") end
}

-- Button 1: resume tile. `info` is the lightweight save summary
-- MainHub.lua builds from /Save/Save.lua (see MainHub.lua's
-- validateSave/refreshSaveStatus).
local function buildLoadBtn(info, careerType)
    local label = careerType == "tourney" and "Tournament"
               or careerType == "league" and "League"
               or careerType == "player" and "Player Career"
               or "Career"
    return {
        name    = "Load " .. label,
        imgSrc  = { name = "$Crest", id = info.teamID },
        subInfo = (info.teamName and info.teamName ~= "") and info.teamName or "Continue",
        desc    = info.dateLabel and ("Resume from " .. tostring(info.dateLabel))
                  or ("Pick up your saved " .. label:lower() .. " right where you left off"),
        event   = function(self) self.mainHub:loadCareerMode(careerType) end
    }
end

-- Button 2: the dedicated stats tile. Kept separate from the Load tile
-- (button 1) and the start-fresh tile (button 3) so neither of those is
-- also doubling as the stats display. Still wired to load the save when
-- tapped, same as button 1, rather than being a dead button.
local function buildStatsBtn(info, careerType)
    local label = careerType == "tourney" and "Tournament" or "League"
    return {
        name         = "Your " .. label .. " Position",
        imgSrc       = {},
        subInfo      = (info.teamName and info.teamName ~= "") and info.teamName or "",
        displayStats = true,
        statType     = "Team",
        event        = function(self) self.mainHub:loadCareerMode(careerType) end
    }
end

-- Resets both tabs to their plain, no-save defaults (a single tile each).
function tabsData.reset()
    tabsData.data["default"] = {
        ["Tab1"] = { [1] = CareerModeBtn, [2] = PlayerCareerBtn },
        ["Tab3"] = { [1] = TournamentModeBtn },
        ["Tab4"] = { [1] = LeagueModeBtn },
        ["Tab5"] = { [1] = CustomizeEditBtn, [2] = PrismCareerBtn }
    }
end

-- Rebuilds Tab2/Tab3/Tab4 from scratch based on the current save status.
--   info == nil, or info.exists == false  -> both tabs reset to defaults.
--   info.mode == "manager" / "player"     -> the Career tab gets Load (#1) +
--                                             stats (#2) + Career Mode (#3) +
--                                             Player Career (#4);
--                                             Tab3 stays at its default.
--   info.mode == "tourney"                -> same, mirrored onto Tab3.
-- Only one save slot exists at a time, so exactly one tab ever shows the
-- Load/stats tiles; the other always shows just its plain default tile.
function tabsData.applySave(info)
    tabsData.reset()
    if not info or not info.exists then return end

    if info.mode == "manager" or info.mode == "player" then
        tabsData.data["default"]["Tab1"] = {
            [1] = buildLoadBtn(info, info.mode),
            [2] = buildStatsBtn(info, info.mode),
            [3] = CareerModeBtn,
            [4] = PlayerCareerBtn
        }
    elseif info.mode == "tourney" then
        tabsData.data["default"]["Tab3"] = {
            [1] = buildLoadBtn(info, "tourney"),
            [2] = buildStatsBtn(info, "tourney"),
            [3] = TournamentModeBtn
        }
    elseif info.mode == "league" then
        tabsData.data["default"]["Tab4"] = {
            [1] = buildLoadBtn(info, "league"),
            [2] = buildStatsBtn(info, "league"),
            [3] = LeagueModeBtn
        }
    end
end

tabsData.reset()

return tabsData
