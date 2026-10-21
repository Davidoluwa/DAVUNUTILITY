# FIFA 16 R98e: Player Career (v2)

Player Career for the R98e pt-BR build. You create your own player: name, body and **every part of the face, one by
one**. Or you play as a player from your club's squad. Your player develops, earns (or loses) the manager's trust, gets
transfer offers, and the whole career saves and loads.

v2 replaces v1's face picker. No more choosing from presets: you build the face part by part.

## Install

1. Install `FIFA16-V7-R98e-PlayerCareer-v2-SIGNED.apk` over your current app. It is signed with your V7 key (same
   certificate, SHA-256 `0acc3640…db1045`), so it installs as an update and keeps data, saves and the OBB. The only
   change inside is `lib/armeabi-v7a/libpv.so` (and the fresh signature); the other 268 files are byte-identical to
   R98e.
2. Copy `ux/` over your R98e `ux/` folder (same paths: 19 files replaced, 7 new).

v2 needs both. The UX on the old APK still runs, but the face isn't saved, and the hub says why.

## Create Your Player

**Main menu → Career tab → Player Career**, pick your club, then **Create Your Player**:

1. **First Name** and **Surname**. The career keyboard gives each word a capital, collapses spaces, and allows up to 20
   letters.
2. **The player** (live 3D model, whole body):
   - **Player**: Position (13), Age (16–30), Preferred Foot
   - **Ability**: Starting Level (45–80 OVR), Potential (65–95), **Height (155–205 cm)**, **Weight (55–100 kg)**
   - **Attack** / **Defence**: focus for Pace, Shooting, Passing, Dribbling, Defending, Physical (Weak … Elite)
3. **The face** (live 3D model, head and shoulders):
   - **Head**: Head Shape (186), Skin Tone (7), Skin Type (3), Eye Colour (10)
   - **Face**: Eyebrows (3), Sideburns (2), Facial Hair (clean shaven + 7 styles), Facial Hair Colour (5)
   - **Hair**: Hairstyle (122), Hair Colour (10, Black … White)
   - **Boots** (172)

Back always goes one step back (face → player → surname → first name → the question). The overall always equals the
Starting Level you chose, worked out with the game's own formula (`PlayerDev.formula`).

### How the face gets into the game

You can't add players to the game, so your player lives in a **body**: one of 13,224 real players from leagues
outside the career who have a name row. That player turns into you, and the change has two parts.

- **In the creator, right away**: libpv's preview takes an override for the body (`pro:look`). The 3D model rebuilds with
  the generic head, face texture, eyes, hair and boots you picked, on every change.
- **In matches**: the body's row in the game's database file is changed in place
  (`Android/data/com.ea.gp.fifaworld/data/db/fifa_ng_db.db`, the file your game loads). This covers his `players` row
  (high-quality head off, head type, every face code, hair, boots, height, weight, foot, position) and his
  `editedplayernames` row.
  - Only bits inside the existing records change. Nothing grows or moves.
  - The table's CRC is fixed (CRC-32/MPEG-2, the same as the game's).
  - Every table's CRC is checked before anything is written.
  - The file is written the R86 way: temp file, fsync, rename, read back.
  - The original is kept once as `fifa_ng_db.db.pro-original.bak`.

**Restart the game once** after creating your player. The game reads its database when it starts, so matches show the
new face from the next start, and the hub tells you so once. Every time the career loads, the file is checked again and
re-written if something else (another editor) put the old values back.

**Names** follow the database's own convention. In R98e every name row has an empty surname column, and the common name
is what the game shows ("A. Zickler"), with the jersey name "Zickler". So you become **"D. Oluwa"**, with "Oluwa" on the
shirt. Career screens show the full "Davun Oluwa".

**Undo**: copy `fifa_ng_db.db.pro-original.bak` back over `fifa_ng_db.db`.

### Known limits

- The preview doesn't tint hair (the style is right, the colour isn't). Matches show the colour.
- The keyboard has letters and a space only: no accents, hyphens or apostrophes.
- The face comes from the game's generic parts, like most players in the game: no photo heads.
- The OBB has 127 generic hairstyles, but five of them (203, 213, 500, 517, 519) don't fit the database's 7-bit
  hairstyle field, so a player can't wear them in matches. They aren't offered.

## In the career

- **AI manager picks the team** (existing `PlayerCareer.pickAISquad`). **Manager trust** (0–100) decides how often you
  start, within your own line only. Each match moves trust by your rating, man-of-the-match and red cards. Each month it
  drifts toward what your overall is worth in the squad. Rotation games give a fringe player his chance. Roles: Key
  Player, First Team, Rotation, Squad Player, Fringe Player.
- **Not in the XI?** The match is simulated (existing behaviour).
- **Stats**: apps, starts, minutes, goals, assists, MOTM, clean sheets and average rating. Kept for the career, the
  season, the last 10 matches, and one line per finished season.
- **Growth**: PlayerDev tracks you from day one. You grow, peak and decline like everyone else.
- **Offers for you**: asked on the hub when it goes idle. **Accept** moves you, **Reject** drops the offer, **Later**
  keeps it for the **My Offers** card.
- **My Player**: the Prism Player Profile screen on your player.
- **Retirement**: the season-end retirement roll never retires your player.
- **Saves**: written as `mode = "player"` plus a `pro` block (name, look, build, stats).

## Bugs fixed on the way

- Player-career saves were written as `mode = "manager"`, and the player was never stored.
- `PlayerCareer.pickAISquad` could drop a player from the squad completely when the bench was full.
- Nothing in the main menu opened Player Career.
- (v2, caught by the flow test before shipping) The created player's surname shared a key with the last-matches list,
  so the database would have been sent the name `D. table: 0x…`.

## Files

| File | Change |
|---|---|
| `Liga/Data/PrismPro.lua` | **new**: the module (creator, look, trust, stats, offers, save) |
| `Liga/Data/PrismProLook.lua` | **new**: the game's generic face parts and the bodies, made by `tools/pro_look.py` from the OBB and your DB |
| `Liga/Screens/ProName/*` | **new**: the name keyboard (the career keyboard on a VM of its own) |
| `Liga/Data/PrismYouth.lua` | `Y.adoptPro`, `Y.setProClub`; your player skips the retirement roll |
| `Liga/Data/CareerDev.lua` | hooks: match recorded, month tick, season end |
| `Liga/Data/PlayerCareer.lua` | trust in the team sheet; full-bench bug fix |
| `Liga/Data/Serializer.lua`, `LoadSave.lua` | `mode = "player"`, the `pro` block |
| `Liga/Cores/tabsData.lua` | My Player / My Offers cards |
| `Liga/PremierLeague/TeamSelect/TeamSelect.lua`, `.lreq` | the new-career step (`PrismPro.start`) |
| `Liga/PremierLeague/MatchSelect/MatchSelect*.lua`, `.lreq` | `PrismPro.bind` / `PrismPro.step` |
| `MainHub.lua`, `MainHub__MainHub.lua`, `MainHub/Cores/mainMenuTabsData.lua` | Player Career tile, player saves, shared-tab Load tiles |
| `flows/prism/skins/Popup/Popup.skin.lua` | setup mode: any spec, title/buttons, the 3D place body or face |
| `flows/prism/skins/Keyboard/Keyboard.skin.lua` | two passed bindings (title, crumb) |
| `prism/skins/Popup.pn`, `Keyboard.pn` | bindings, info panel, 3D places `cs_player3d_4` / `csface_player3d_4` (by `tools/pro_scenes.py`) |
| `lua/prism/PrismI18nData.lua` | pt-BR for every new string |

libpv (`libpv/`): `src/f16_pro.c` and `src/f16_pro.h` are new (the `pro:` commands, the preview override, the database
writer). `f16_db.c` applies the override and loads generic hair for it, `f16_service.c` routes `pro:`, and the build
script compiles `f16_pro.c`. `patches/libpv-player-career.diff` is that change against your libpv source, and
`patches/ux-r98e-player-career.diff` is the UX change against R98e.

Tools: `tools/obb_list.py` (BIG4 OBB lister), `tools/pro_look.py` (makes `PrismProLook.lua`), `tools/pro_scenes.py`
(the scene edits, idempotent), and `tools/repack_apk.sh`, which puts a libpv into the app and signs it with your key
(v1 + v2, like the original).

## Tests

```
sh tests/run_tests.sh /path/to/lua5.1 /path/to/full/ux
test_prismpro      94102 passed, 0 failed
test_popup_setup   43 passed, 0 failed
test_flow          184 passed, 0 failed
lua5.1 tests/creator_values.lua /path/to/full/ux | ./test_pro_values fifa_ng_db.db 243893
700 looks, 0 refused; CRCs valid

gcc -DF16_HOST -Isrc -fsanitize=address,undefined tests-f16service/test_pro_host.c src/f16_pro.c src/f16_store.c
./a.out fifa_ng_db.db /tmp 243893
47 passed, 0 failed
```

What they cover:
- **libpv on your real `fifa_ng_db.db`**: CRCs check, set/get round trip, only his row and the CRC change, ranges
  refused (height 216 / 149), names, the router on a file copy, the backup kept once, the preview override.
- **The keyboard VM**: capitals, spaces, the 20-letter limit, Back, finalize.
- **Both creator pages driven tap by tap** through the real Popup skin, with the 3D commands checked (override →
  show → rebuild).
- **The whole way in**: question → first name → surname → player page → face page, with every Back. Then the hub, the
  database writes (once per session, re-written when the look changes, refused writes and an old libpv explained), the
  restart notice shown once, PlayerDev, the match override table, the AI team sheet, save/load, and the season end.
- **Every value the creator can produce** (700: each row's every value on top of the defaults) goes through the real
  C writer on your database. None are refused, and every CRC is still right afterwards
  (`tests/creator_values.lua | test_pro_values`). This is what caught the five hairstyles above.
- **The 3D preview pack**, built on the host by libpv's own pack builder from the OBB, for body 243893 with a full
  creator look. It loads `head_2004_1`, the face texture `face_0_1_0_2_1_3_5_1_9` (eyebrows, sideburns, beard colour,
  beard, skin type and tone exactly as picked), `eyes_4`, `hair_44` and `shoe_55`. Two-thirds of the pack's bytes
  differ from the body's stock pack. The first and last value of every list also build.
- pt-BR for every creator string.

This hasn't run on a phone yet. The native screen layout and the 3D framing (body / face) need an on-device look.

## Not done: Player Lock on your player

`fifa:f16lock:1` locks you to a **random** player. From the shipped `libfifa.so` (read-only disassembly):

- The receiver (`0x2c38d20`) stores the value under key `0xeb6154c6` and zeroes the per-side slot keys `0xcff6c26e` and
  `0xcf7c4977`.
- The picker (`0x2dbc000`) locks onto the player whose `[player+0x34]` equals the side key − 1, and only picks at random
  when the key is 0.

Smallest fix: `f16lock:N` with N ≥ 2 → lock on, both side keys = N − 1. This needs your libfifa patch builder
(`build_r56.py`) and one on-device check that `[player+0x34]` is the lineup slot.
