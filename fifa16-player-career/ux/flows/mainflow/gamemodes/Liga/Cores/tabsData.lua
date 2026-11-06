local tabsData = {}
local mode = nil
tabsData.data = {}
tabsData.tabs = {}

local careerModeTabs    = { "Central", "Squad", "Transfers", "Office", "Customise" }
local tourneyModeTabs    = { "Central", "Squad", "Office", "Customise" }
local leagueModeTabs     = { "Central", "Squad", "Office", "Customise" }
-- Player Career: 4 tabs. No Team-Management edit (AI manager owns the squad),
-- no Transfers tab (the user only handles offers for THEIR player via the
-- "My Player" tab), no Budget (the user is a player, not a manager).
local playerCareerTabs   = { "Central", "My Player", "Office", "Customise" }

tabsData.MAX_TABS = 7
tabsData.tabs["career"]         = careerModeTabs
tabsData.tabs["tournament"]     = tourneyModeTabs
tabsData.tabs["league"]         = leagueModeTabs
tabsData.tabs["playerCareer"]   = playerCareerTabs

tabsData.data["career"] = {
	["Tab2"] = {
						[1] = {name = "Team Management",
								imgSrc = "$Icon_Team_Cup",
								subInfo = "",
								desc = "",
								event = "evt_squad"},						
						[2] = {name = "Squad Hub",
								imgSrc = "$Icon_Team_Cup",
								subInfo = "View your players",
								desc = "",
								event = "evt_teamhub"
								},
						[3] = {name = "Youth Academy",   -- the user's academy (PrismYouth)
								imgSrc = "$Icon_Team_Cup",
								subInfo = "Your academy prospects",
								desc = "",
								event = (function(self) local Y = rawget(_G, "PrismYouth"); if Y and Y.openAcademy then Y.openAcademy(self) end end)
								},
						[4] = {name = "Training",   -- the weekly training (PrismTraining, R98e)
								imgSrc = "$Icon_Team_Cup",
								subInfo = "Weekly sessions",
								desc = "",
								event = (function(self) local TR = rawget(_G, "PrismTraining"); if TR and TR.open then TR.open(self) end end)
								}
						
					},
	["Tab3"] = {
						[1] = {name = "Search Players",
								imgSrc = "$FooterIconSearch",
								subInfo = "",
								desc = "Search for a specific player you want to buy, loan or scout",
								event = "evt_searching"},
						[2] = {name = "Global Transfer Network",
								imgSrc = "$Enter_Scouts",
								subInfo = "",
								desc = "",
								displayStats = false,
								event = "evt_gtn"},
						[3] = {name = "Transfer Hub",
								imgSrc = "$THubIcon",
								subInfo = "View Team Transfer Activity",
								desc = "",
								event = "evt_transferhub"},
						[4] = {name = "Transfer History",
								imgSrc = "$THubIcon",
								subInfo = "Every move, season by season",
								desc = "",
								event = (function(self) local H = rawget(_G, "PrismHistory"); if H and H.open then H.open(self) end end)}
					},
     ["Tab4"] = {
						[1] = {name = "Calendar",
								imgSrc = "$calendaricon",
								subInfo = "",
								desc = "View your team's upcoming schedule",
								event = "evt_calendar"},
						[2] = {name = "Team Stats",
								imgSrc = "",
								subInfo = "View team stats",
								desc = "",
								displayStats = true,
								statType = "Team",
								event = "evt_table"},
					    [3] = {name = "Budget Overview",
								imgSrc = "",
								subInfo = "View team budget",
								desc = "",
								displayBudget = true,
								event = ""},
						[4] = {name = "Fixtures",
								imgSrc = "$fixturesicon",
								subInfo = "",
								desc = "",
								event = "evt_fixtures"}
					},	
    ["Tab5"] = {
						[1] = {name = "Settings",
									imgSrc = "$Icon_Setting_Cup",
									subInfo = "",
									desc = "",
									event = "evt_to_settings_customize"},
						[2] = {name = "Player Stats",
								imgSrc = "",
								subInfo = "View players stats",
								desc = "",
								displayStats = true,
								statType = "Player",
								event = "evt_goalscorer"},
								[3] = {name = "Save",
								imgSrc = "$icon_save",
								subInfo = "Save career progress",
								desc = "",
								event = (function(self) local PS = rawget(_G, "PrismSlots"); if PS and PS.saveFromHub then PS.saveFromHub(self) else self.serializer:saveProgress() end end)}
					}
	}
	
	tabsData.data["tournament"] = {
	["Tab2"] = {
						[1] = {name = "Team Management",
								imgSrc = "$Icon_Team_Cup",
								subInfo = "",
								desc = "",
								event = "evt_squad"},						
						[2] = {name = "Squad Hub",
								imgSrc = "$Icon_Team_Cup",
								subInfo = "View your players",
								desc = "",
								event = "evt_teamhub"
								}
						
					},		
     ["Tab3"] = {
						[1] = {name = "Calendar",
								imgSrc = "$calendaricon",
								subInfo = "",
								desc = "View your team's upcoming schedule",
								event = "evt_calendar"},
						[2] = {name = "Team Stats",
								imgSrc = "",
								subInfo = "View team stats",
								desc = "",
								displayStats = true,
								statType = "Team",
								event = "evt_table"},
						[3] = {name = "Fixtures",
								imgSrc = "$fixturesicon",
								subInfo = "",
								desc = "",
								event = "evt_fixtures"}
					},	
    ["Tab4"] = {
						[1] = {name = "Settings",
									imgSrc = "$Icon_Setting_Cup",
									subInfo = "",
									desc = "",
									event = "evt_to_settings_customize"},
						[2] = {name = "Player Stats",
								imgSrc = "",
								subInfo = "View players stats",
								desc = "",
								displayStats = true,
								statType = "Player",
								event = "evt_goalscorer"},
								[3] = {name = "Save",
								imgSrc = "$icon_save",
								subInfo = "Save career progress",
								desc = "",
								event = (function(o) local PS = rawget(_G, "PrismSlots"); if PS and PS.saveFromHub then PS.saveFromHub(o) else o.serializer:saveProgress() end end)}
					}
	}
	
-- League Mode deliberately gets its own data branch instead of aliasing the
-- tournament table. The surface is tournament-like (no Transfers/Budget), while
-- MatchSelect/Fixtures continue to use normal League match records underneath.
local function cloneModeData(value)
    if type(value) ~= "table" then return value end
    local copy = {}
    for k, v in pairs(value) do copy[k] = cloneModeData(v) end
    return copy
end

tabsData.data["league"] = cloneModeData(tabsData.data["tournament"])

-- ── Player Career tab data ────────────────────────────────────────────────
-- Reuses the same button shape (name / imgSrc / subInfo / desc / event) as
-- the career / tournament blocks. Events that don't exist yet in the nav
-- (evt_myplayer, evt_myoffers) are added to MatchSelect.nav by the player
-- career patch. Events that already exist (evt_calendar, evt_fixtures,
-- evt_goalscorer, evt_to_settings_customize, save) are reused as-is.
tabsData.data["playerCareer"] = {
    ["Tab2"] = {
        -- PrismPro: the Player Profile on your player, and the offers for him (the stock
        -- events evt_myplayer / evt_myoffers stay the fallback without the module)
        [1] = { name     = "My Player",
                imgSrc   = "$Icon_Team_Cup",
                subInfo  = "View your player profile",
                desc     = "",
                event    = function(o)
                    local PRO = rawget(_G, "PrismPro")
                    local ok, shown = false, false
                    if PRO and PRO.openProfile then ok, shown = pcall(PRO.openProfile, o) end
                    if not (ok and shown) then o.nav.Event(nil, "evt_myplayer") end
                end },
        [2] = { name     = "My Offers",
                imgSrc   = "$THubIcon",
                subInfo  = "Transfer offers for your player",
                desc     = "",
                event    = function(o)
                    local PRO = rawget(_G, "PrismPro")
                    if PRO and PRO.offers then pcall(PRO.offers, o) else o.nav.Event(nil, "evt_myoffers") end
                end },
        [3] = { name     = "Squad Hub",
                imgSrc   = "$Icon_Team_Cup",
                subInfo  = "View your team's players",
                desc     = "",
                event    = "evt_teamhub" },
    },
    ["Tab3"] = {
        [1] = { name     = "Calendar",
                imgSrc   = "$calendaricon",
                subInfo  = "",
                desc     = "View your team's upcoming schedule",
                event    = "evt_calendar" },
        [2] = { name     = "Team Stats",
                imgSrc   = "",
                subInfo  = "View team stats",
                desc     = "",
                displayStats = true,
                statType = "Team",
                event    = "evt_table" },
        [3] = { name     = "Fixtures",
                imgSrc   = "$fixturesicon",
                subInfo  = "",
                desc     = "",
                event    = "evt_fixtures" },
    },
    ["Tab4"] = {
        [1] = { name     = "Settings",
                imgSrc   = "$Icon_Setting_Cup",
                subInfo  = "",
                desc     = "",
                event    = "evt_to_settings_customize" },
        [2] = { name     = "Player Stats",
                imgSrc   = "",
                subInfo  = "View players stats",
                desc     = "",
                displayStats = true,
                statType = "Player",
                event    = "evt_goalscorer" },
        [3] = { name     = "Save",
                imgSrc   = "$icon_save",
                subInfo  = "Save career progress",
                desc     = "",
                event    = (function(o) local PS = rawget(_G, "PrismSlots"); if PS and PS.saveFromHub then PS.saveFromHub(o) else o.serializer:saveProgress() end end) },
    },
}

return tabsData
