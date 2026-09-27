#!/usr/bin/env python3
"""Эксперимент в игре: какой механизм подмены диалога работает и кто побеждает (docs → README, «Эксперимент»).

Собирает три крошечных мода в DialogKit/dist/ (в git не входят). Все правят одну беседу — Астарион в отряде,
приветствие «Ну привет. Чем могу быть полезен?» (Astarion_InParty2): в конец вариантов добавляется
вариант-маркер (по образцу «Уйти.»: без условий, беседа заканчивается). По надписи видно, чей файл загрузила игра.

  A  DialogKitProbe_A — свой банк диалогов + Lua: AddPathOverride(свой файл → вариант).
       «[DialogKit A] банк и подмена пути» — работают оба механизма;
       «[DialogKit A] только банк»        — банк работает, AddPathOverride нет.
  B  DialogKitProbe_B — без банка, Lua: AddPathOverride(файл игры → свой файл). Так подменял старый Team Effort.
       «[DialogKit B] подмена файла игры» — работает.
  C  DialogKitProbe_C — только свой банк (Lua нет). Вместе с A: побеждает тот, кто позже в порядке загрузки?
  D  DialogKitProbe_D — ни банка, ни Lua: только файл с тем же внутренним UUID в своей папке Story/DialogsBinary.
       «[DialogKit D] совпадение UUID файла» — игра подменяет диалог по UUID файла (гипотеза прошлой сессии).

  python probe/build_probe.py          # нужен config.json рядом (пути к Divine и игре) или переменные ниже
"""
import json
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dialogkit import lsx                      # noqa: E402
from dialogkit.build import Project            # noqa: E402
from dialogkit.game import Game, VANILLA       # noqa: E402

CFG = json.loads((ROOT / "probe" / "config.json").read_text(encoding="utf-8"))
NS = uuid.UUID("5d1a6c3e-7f0b-4b8e-9c41-2a7e5d9f1b61")
DIALOG = "Astarion_InParty2"
ROOT_GREETING = "05b247e0-98eb-4dbe-881e-7f4fa622af86"   # «Ну привет. Чем могу быть полезен?»
LEAVE = "0b9dd543-ed99-4f52-90b4-28cdafc14dbf"           # «Уйти.»
PROBES = {
    "A": {"bank": True, "lua": "own_to_variant",
          "own": "[DialogKit A] только банк", "variant": "[DialogKit A] банк и подмена пути"},
    "B": {"bank": False, "lua": "vanilla_to_own", "own": "[DialogKit B] подмена файла игры"},
    "C": {"bank": True, "lua": None, "own": "[DialogKit C] банк C"},
    "D": {"bank": False, "lua": None, "own": "[DialogKit D] совпадение UUID файла"},
}


def handle(key):
    u = uuid.uuid5(NS, key).hex
    return f"h{u[:8]}g{u[8:12]}g{u[12:16]}g{u[16:20]}g{u[20:]}"


def meta(name, folder, mod_uuid):
    v = 1 << 55
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<save>
    <version major="4" minor="8" revision="0" build="500"/>
    <region id="Config">
        <node id="root">
            <children>
                <node id="Conflicts"/>
                <node id="Dependencies"/>
                <node id="ModuleInfo">
                    <attribute id="Author" type="LSString" value="adsyde"/>
                    <attribute id="CharacterCreationLevelName" type="FixedString" value=""/>
                    <attribute id="Description" type="LSString" value="DialogKit experiment: which dialog override wins."/>
                    <attribute id="FileSize" type="uint64" value="0"/>
                    <attribute id="Folder" type="LSString" value="{folder}"/>
                    <attribute id="LobbyLevelName" type="FixedString" value=""/>
                    <attribute id="MD5" type="LSString" value=""/>
                    <attribute id="MenuLevelName" type="FixedString" value=""/>
                    <attribute id="Name" type="LSString" value="{name}"/>
                    <attribute id="NumPlayers" type="uint8" value="4"/>
                    <attribute id="PhotoBooth" type="FixedString" value=""/>
                    <attribute id="PublishHandle" type="uint64" value="0"/>
                    <attribute id="StartupLevelName" type="FixedString" value=""/>
                    <attribute id="Tags" type="LSString" value=""/>
                    <attribute id="Type" type="FixedString" value="Add-on"/>
                    <attribute id="UUID" type="FixedString" value="{mod_uuid}"/>
                    <attribute id="Version64" type="int64" value="{v}"/>
                    <children>
                        <node id="PublishVersion"><attribute id="Version64" type="int64" value="{v}"/></node>
                        <node id="Scripts"/>
                    </children>
                </node>
            </children>
        </node>
    </region>
</save>
'''


def patch(mod_uuid, text_key):
    return {"format": "dialogkit/1", "id": f"dialogkit-probe/{text_key}", "mod": mod_uuid, "dialog": DIALOG,
            "ops": [{"op": "add_node", "key": "marker", "like": LEAVE, "text": handle(text_key),
                     "parents": [{"node": ROOT_GREETING, "after": LEAVE}]}]}


def main():
    game = Game(CFG["divine"], CFG["game_dir"], ROOT / "cache")
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    vanilla_path = game.binary_path(lsx.value(game.dialog_resource(VANILLA, DIALOG)[1], "SourceFile"))
    for key, p in PROBES.items():
        name = f"DialogKitProbe_{key}"
        mod_uuid = str(uuid.uuid5(NS, name))
        folder = f"{name}_{mod_uuid}"
        work = ROOT / "cache" / "probe" / key
        if work.exists():
            shutil.rmtree(work)
        pdir = work / "patches"
        pdir.mkdir(parents=True)
        (pdir / "own.json").write_text(json.dumps(patch(mod_uuid, f"{key}:own")), encoding="utf-8")
        out = work / "pak"
        project = Project(game, mod_uuid, [pdir], out, placeholder=folder)
        project.build()
        texts = {handle(f"{key}:own"): p["own"]}
        if p.get("variant"):          # вариант с другим текстом маркера — туда ведёт AddPathOverride
            vd = work / "vpatches"
            vd.mkdir()
            (vd / "v.json").write_text(json.dumps(patch(mod_uuid, f"{key}:variant")), encoding="utf-8")
            vout = work / "vpak"
            Project(game, mod_uuid, [vd], vout, placeholder=folder).build()
            src = next(vout.rglob(f"Story/DialogsBinary/**/{DIALOG}.lsf.lsx"))
            dst = out / f"Mods/{folder}/DialogKit/probe/{DIALOG}.lsf.lsx"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            texts[handle(f"{key}:variant")] = p["variant"]
        if not p["bank"]:
            shutil.rmtree(out / f"Public/{folder}/Content", ignore_errors=True)
        own_rel = next((out / "Mods" / folder / "Story" / "DialogsBinary").rglob(f"{DIALOG}.lsf.lsx"))
        own_path = own_rel.relative_to(out).as_posix()[:-4]
        (out / f"Mods/{folder}/meta.lsx").write_text(meta(name, folder, mod_uuid), encoding="utf-8")
        loc = out / f"Mods/{folder}/Localization"
        for lang in ("English", "Russian"):
            rows = "".join(f'  <content contentuid="{h}" version="1">{t}</content>\n' for h, t in texts.items())
            (loc / lang).mkdir(parents=True, exist_ok=True)
            (loc / lang / f"{name}_{lang[:2]}.xml").write_text(
                f'<?xml version="1.0" encoding="utf-8"?>\n<contentList>\n{rows}</contentList>\n', encoding="utf-8")
        if p["lua"]:
            se = out / f"Mods/{folder}/ScriptExtender"
            (se / "Lua").mkdir(parents=True, exist_ok=True)
            (se / "Config.json").write_text(json.dumps({"RequiredVersion": 4, "ModTable": name,
                                                        "FeatureFlags": ["Lua"]}), encoding="utf-8")
            if p["lua"] == "own_to_variant":
                a, b = own_path, f"Mods/{folder}/DialogKit/probe/{DIALOG}.lsf"
            else:
                a, b = vanilla_path, own_path
            code = (f'Ext.IO.AddPathOverride("{a}", "{b}")\n'
                    f'_P("[{name}] AddPathOverride {a} -> {b}")\n')
            for f in ("BootstrapServer.lua", "BootstrapClient.lua"):
                (se / "Lua" / f).write_text(code, encoding="utf-8")
        for f in sorted(out.rglob("*.lsf.lsx")):     # в бинарный вид, как ждёт игра
            game.run("-a", "convert-resource", "-s", f.resolve(), "-d", f.with_suffix("").resolve())
            f.unlink()
        pak = dist / f"{name}.pak"
        game.run("-a", "create-package", "-s", out.resolve(), "-d", pak.resolve())
        print(f"{pak.name}: UUID {mod_uuid}, банк {'да' if p['bank'] else 'нет'}, Lua {p['lua'] or 'нет'}")


if __name__ == "__main__":
    main()
