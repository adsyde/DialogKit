# DialogKit

Общий слой правок диалогов BG3 для нескольких модов: **Team Effort**, **SuccubusPlus** и любых
следующих. Моды только **дополняют** диалоги игры и друг друга, ничего не затирают, и каждый работает
один. Правки чужого мода, который сам подменяет диалоги (If Fate Chose Differently), сохраняются: наши
патчи накладываются поверх его версии.

Файлов игры и чужих модов в репозитории нет. Всё, что из них собрано, лежит в `cache/`, в `build/`
проекта и в его паке.

## Как игра находит диалог (проверено 2026-09-27 по пакам)

- **Банк диалогов** (`Public/<модуль>/Content/…/*.lsf`, регион `DialogBank`) хранит ресурс: `ID`,
  `Name`, `SourceFile` (`Mods/<модуль>/Story/Dialogs/<путь>.lsj`) и `SpeakerSlotsWithLines`
  (у каких слотов есть реплики). Игра грузит `Mods/<модуль>/Story/DialogsBinary/<путь>.lsf`.
- **Подмена мода.** Мод кладёт в свой банк ресурс с тем же `ID` и своим `SourceFile`. Так делает
  If Fate Chose Differently: `COL_EntranceDoor` — ID `a7ad5aaa-…`, как в банке игры. Внутренний UUID
  файла (`c01ce0af-…`) совпадает только потому, что файл — копия. Подмену по одному UUID проверяет
  эксперимент D.
- **Таймлайн** подменяется так же: `TimelineBank`, ресурс с `DialogResourceId` и `SourceFile`.
  Сцена `<имя>_Scene.lsf` лежит рядом с таймлайном: If Fate Chose Differently кладёт её в свою папку.
- **Голос.** Ответ NPC уже озвученной репликой из другой сцены — это узел с существующим хэндлом плюс
  в таймлайне фаза `Phase(Duration, DialogNodeId)`, компонент `TLVoice(StartTime, EndTime, PhaseIndex,
  DialogNodeId, Actor)` и запись `TimelinePhases` (узел → номер фазы). Так сделаны 8 новых реплик
  Уилла в `Wyll_InParty2_Nested_PostJudgement` у If Fate Chose Differently. Варианты игрока в игре не
  озвучены вовсе, и фаз у них нет.

## Как DialogKit подменяет

| Вариант | Что внутри | Где лежит в паке мода |
|---|---|---|
| `own` | свои патчи поверх игры | `Mods/<мод>/Story/DialogsBinary/…` + запись в **своём банке** |
| `all` | свои и патчи партнёров (другие моды на DialogKit) | `Mods/<мод>/DialogKit/all/…` |
| `own@<UUID>`, `all@<UUID>` | то же поверх версии мода-базы | `Mods/<мод>/DialogKit/own_at_<UUID>/…` |

- Без Script Extender работает `own`: наш банк победит банк игры.
- Остальное выбирает Lua при загрузке (`dialogkit/lua/DialogKit.lua`, сервер и клиент) через
  `Ext.IO.AddPathOverride`. Правила выбора:
  - **Два мода на DialogKit правят один диалог.** Подменяет ровно один — тот, что позже в порядке
    загрузки: его банк всё равно победит. Он берёт `all`, второй для этого диалога ничего не делает.
    Порядок патчей в `all` — по UUID мода, поэтому у обоих модов итог одинаковый.
  - **Диалог правит мод-база.** Такой диалог в наш банк не кладём, подменяем только из Lua: файл базы
    (если она включена) или файл игры. Если подмена не сработает, пропадут наши правки, а не правки
    базы.
- Проверки в игре ждут: работает ли `AddPathOverride` для файлов из банков, побеждает ли банк позже
  в порядке загрузки, подменяет ли игра диалог по UUID файла. Смотрите раздел «Эксперимент».

## Формат патча (`dialogkit/1`)

Один JSON — один диалог. Файлы патчей проекта лежат в его каталоге, например
`TeamEffort/data/patches/**.json`, `SuccubusPlus/dialogkit/patches/**.json`.

```json
{
  "format": "dialogkit/1",
  "id": "succubus-plus/lines",
  "mod": "a41f6c2e-9b37-4d58-b0e1-7c3d95f28e64",
  "dialog": "MOO_Raphael_Offer",
  "ops": [ … ]
}
```

- `id` — пространство имён для детерминированных UUID: `uuid5(NS, "<id>:<dialog>:<key>")`.
- `dialog` — имя файла диалога без расширения. Имя в банке бывает другим: у `Wyll_InParty2.lsj` оно
  `Wyll_InParty`.

### Операции

**`add_node`** — новый узел по образцу `like`, узлу того же диалога. Копируется всё: дети (исходы),
флаги, одобрение, условия. Меняется только то, что задано:

| Поле | Что |
|---|---|
| `key` | имя узла в патче; ссылка из других операций — `"@key"` |
| `like` | UUID образца (или `@key`) |
| `speaker` | слот говорящего (число или `@ключ` из `add_speaker`) |
| `text` | хэндл текста (`"h…"` или `{"handle", "version", "replace_all"}`); у образца должен быть один текст, а с `replace_all: true` все его варианты (например, «колдуну» и «остальным» с правилами по тегам) заменяются одним безусловным |
| `move_slot` | `[1, 8]` — условия и флаги узла со слота 1 перенести на слот 8 |
| `conditions_add` | добавить условия: `{"type": "Tag"/"Object"/"Global"/…, "flag": UUID, "value": bool, "slot": n}` |
| `conditions` | заменить условия целиком |
| `set_flags_add` | добавить флаги, которые узел ставит |
| `roll` | для образца `ActiveRoll`: `{"ability", "skill", "dc": DifficultyClassID, "advantage", "roll_type"}` |
| `approval` | `ApprovalRatingID` |
| `children` | новые дети: только новые узлы патча (`@key`) или исходы образца |
| `parents` | к чему подвесить: `[{"node": UUID, "after": UUID}]`; по умолчанию — ко всем родителям образца сразу после него (и в корни, если образец корневой) |
| `voice` | для ответа NPC существующей озвученной репликой: `{"length": сек}` (без `length` длина берётся из VoiceMeta игры); добавляет фазу и `TLVoice` в таймлайн |
| `derive` | `{"ns": UUID, "tag": "8"}` — UUID узла и LineId как `uuid5(ns, "<исходный id>:<tag>")` (совместимость со старыми id Team Effort) |
| `uuid` | явный UUID узла |

**`add_speaker`** — новый говорящий. Поля: `key`, `character` (UUID персонажа), при желании
`index` и `mapping` (SpeakerMappingId). Если персонаж уже есть в диалоге, берётся его слот. В таймлайн
добавляются номер говорящего и запись актёра на свободном месте спутника в сцене. Банк получает
`HasLines` для нового слота, а `DependencyCache` таймлайна — персонажа.

**`add_roll`** — проверка рядом с вариантом, у которого броска нет (например, «Торговать»). Узел
`ActiveRoll` строится по образцу варианта (текст, условия, флаги, говорящий), к нему — два новых `RollResult`.
По умолчанию оба исхода ведут туда же, куда вариант-образец: ход беседы не меняется, исходы различаются
флагами (например, скидку или наценку делает Lua мода).

```json
{"op": "add_roll", "key": "charm", "like": "<UUID варианта>", "text": "h…",
 "roll": {"ability": "Charisma", "skill": "", "dc": "<DifficultyClassID>", "advantage": 0,
          "target": 0, "show_once": true},
 "conditions_add": [{"type": "Tag", "flag": "<тег>", "value": true, "slot": 1}],
 "success": {"set_flags_add": [{"type": "Object", "flag": "<флаг>", "value": true, "slot": 0}]},
 "failure": {"set_flags_add": [...]}}
```

- `roll.target` — слот, против кого бросок (`RollTargetSpeaker`); по умолчанию — говорящий реплики, после
  которой стоит вариант. `roll_type` по умолчанию `SkillCheck` при заданном `skill`, иначе `RawAbility`.
- `success.children` / `failure.children` — только исходы образца или новые узлы патча (`@key`); по умолчанию —
  исходы образца. Ключи исходов в патче: `@<key>:success`, `@<key>:failure`.
- Образец-бросок (`ActiveRoll`) — ошибка: для него `add_node` с `roll`.

**`add_child`** — подвесить новый узел патча к существующему (`parent`, `child`, `after`).

### Правила, которые проверяет сборка

1. Существующие узлы, переходы и флаги не меняются и не удаляются. Операций удаления или переадресации нет.
2. Новый узел — всегда рядом с существующим. Его исходы — исходы образца. Бросок по образцу броска
   ведёт в те же узлы успеха и провала, со всеми их флагами.
3. Новая ветка обязана вернуться в узлы игры или закончиться, как кончается образец. Иначе ошибка
   «тупик» или «не возвращается».
4. Новый узел обязан быть к чему-то подвешен.
5. Озвучка — только существующими хэндлами. Новые реплики игрока не озвучиваются.

## Подключение к проекту

```python
import sys; sys.path.insert(0, "../DialogKit")
from dialogkit.game import Game
from dialogkit.build import Project, lua_manifest

game = Game(divine, game_dir, cache_dir)          # cache_dir — вне git
project = Project(game, MOD_UUID, ["dialogkit/patches"], Path("mod"),     # mod/ с папкой-заглушкой _MOD_
                  partners=[{"uuid": TE_UUID, "name": "Team Effort", "patches": "../TeamEffort/data/patches"}],
                  bases=[{"uuid": "8007e4f8-4cf1-4077-9953-3e67e456329c", "name": "If Fate Chose Differently",
                          "source": "MGNTN_WyllPactPoints"}])
manifest = project.build()
# в Lua проекта: dialogkit/lua/DialogKit.lua → Shared/DialogKit.lua, манифест → Shared/DialogKitManifest.lua
Path(".../Shared/DialogKitManifest.lua").write_text(lua_manifest(manifest, MOD_UUID), encoding="utf-8")
```

```lua
-- Shared/Dialogs.lua, из BootstrapServer.lua и BootstrapClient.lua
local DialogKit = Ext.Require("Shared/DialogKit.lua")
Ext.Require("Shared/DialogKitManifest.lua")
DialogKit.Apply("<UUID мода>", DialogKitManifest, function(fmt, ...) _P(string.format(fmt, ...)) end)
```

- **Сборка пака.** `.lsf.lsx` в `Story/DialogsBinary`, `DialogKit`, `Timeline`, `Content` превращаются
  в `.lsf` (Divine `convert-resource`); `_Scene.lsf` кладутся как есть.
- **Известные моды.** Team Effort `c226c99d-720c-4611-98c9-9ba1fe6df481` (патчи
  `TeamEffort/data/patches`), SuccubusPlus `a41f6c2e-9b37-4d58-b0e1-7c3d95f28e64` (патчи
  `SuccubusPlus/dialogkit/patches`), If Fate Chose Differently `8007e4f8-4cf1-4077-9953-3e67e456329c`
  (пак `MGNTN_WyllPactPoints` — база).

## Эксперимент в игре

`python probe/build_probe.py` собирает в `dist/` четыре крошечных мода. Все добавляют в беседу
с Астарионом в отряде (приветствие «Ну привет. Чем могу быть полезен?») последний вариант — надпись.
Какая надпись видна, такой файл и загрузила игра.

| № | Включить | Что увидим → вывод |
|---|---|---|
| 1 | только A | «A банк и подмена пути» → работают оба механизма; «A только банк» → банк да, `AddPathOverride` нет; ничего → банк мода не работает |
| 2 | только B | «B подмена файла игры» → `AddPathOverride` пути игры работает; ничего → нет |
| 3 | только D | «D совпадение UUID файла» → игра подменяет по UUID файла; ничего → нет, только по банку |
| 4 | A, потом C | «C банк C» → побеждает банк позже в порядке загрузки |
| 5 | C, потом A | «A …» → то же правило с другой стороны |

## Тесты

```
python -m pytest tests        # нужны pytest и lupa (Lua)
```
