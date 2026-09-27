"""Сборка правок диалогов для одного мода: базы, варианты, банки, манифест для Lua.

Мод-проект (Team Effort, SuccubusPlus, …) даёт свои патчи и знает о партнёрах (другие моды на DialogKit,
их патчи лежат на диске) и о «базах» — чужих модах, которые сами подменяют диалоги игры (If Fate Chose
Differently). Для каждого диалога из своих патчей собираются варианты:

  own            свои патчи поверх игры — по умолчанию, работает без Script Extender (наш банк);
  all            свои + патчи партнёров (если партнёр тоже правит этот диалог);
  own@<UUID>     свои поверх версии базы-мода, all@<UUID> — все поверх неё.

Порядок патчей в «all» — по UUID мода, одинаковый в сборке любого партнёра, поэтому итог совпадает.
Какой вариант включить, решает Lua при загрузке (dialogkit/lua/DialogKit.lua): если партнёр включён и
стоит позже в порядке загрузки — подменяет он (его банк всё равно победит), мы ничего не делаем.
"""
import copy
import shutil
from pathlib import Path

from . import lsx
from .game import VANILLA
from .patch import Patch, apply_patches


def load_patches(dirs):
    out = {}
    for d in dirs:
        for f in sorted(Path(d).rglob("*.json")):
            p = Patch.load(f)
            out.setdefault(p.dialog, []).append(p)
    return out


def sub_path(source_file):
    """'Mods/GustavDev/Story/Dialogs/Act2/Town/X.lsj' → 'Act2/Town/X'."""
    return source_file.split("/Story/Dialogs/", 1)[1][:-4]


class Project:
    """mod: UUID этого мода; folder: папка модуля (Name_UUID); out: корень раскладки пака (как mod/ проекта,
    вместо папки модуля пишется placeholder, по умолчанию _MOD_); partners: [{"uuid", "name", "patches"}];
    bases: [{"uuid", "name", "source"}] — source: пак мода в папке Mods."""

    def __init__(self, game, mod, patches, out, partners=(), bases=(), placeholder="_MOD_"):
        self.game, self.mod, self.out, self.ph = game, mod, Path(out), placeholder
        self.own = load_patches(patches if isinstance(patches, (list, tuple)) else [patches])
        self.partners = [dict(p, patches=load_patches([p["patches"]]) if Path(p["patches"]).exists() else {})
                         for p in partners]
        self.bases = list(bases)
        for p in self.own.values():
            for x in p:
                if x.mod != mod:
                    raise ValueError(f"{x.origin}: патч мода {x.mod}, а собирается {mod}")

    # ── пути в паке ──────────────────────────────────────────────────────────
    def own_dialog(self, sub):
        return f"Mods/{self.ph}/Story/DialogsBinary/{sub}.lsf"

    def variant_dialog(self, variant, sub):
        return f"Mods/{self.ph}/DialogKit/{variant.replace('@', '_at_')}/{sub}.lsf"

    def own_timeline(self, name):
        return f"Public/{self.ph}/Timeline/Generated/{name}.lsf"

    def variant_timeline(self, variant, name):
        return f"Public/{self.ph}/DialogKit/{variant.replace('@', '_at_')}/{name}.lsf"

    # ── сборка ───────────────────────────────────────────────────────────────
    def base_files(self, name, base):
        """Бинарный диалог, таймлайн и сцена базы: [(источник, путь внутри пака)], Resource диалога и таймлайна."""
        sources = VANILLA + ([base["source"]] if base else [])
        found = self.game.dialog_resource(VANILLA, name)
        if not found:
            raise ValueError(f"диалога {name} нет в банках игры")
        rid = lsx.value(found[1], "ID")
        src, res = self.game.dialog_by_id(sources, rid)
        tl = self.game.timeline_by_dialog(sources, rid)
        return src, res, tl

    def build_variant(self, name, patches, base):
        src, res, tl = self.base_files(name, base)
        files = VANILLA if src in VANILLA else [src]     # исправления игры лежат в более поздних паках
        dlg_tree = lsx.load(self.game.file(files, self.game.binary_path(lsx.value(res, "SourceFile"))))
        timeline = scene = None
        need_tl = any(p.needs_timeline() for p in patches)
        if need_tl:
            if not tl:
                raise ValueError(f"{name}: у диалога нет таймлайна, а патчи его требуют")
            tl_src, tl_res = tl
            tl_file = lsx.value(tl_res, "SourceFile")
            tl_files = VANILLA if tl_src in VANILLA else [tl_src]
            timeline = lsx.load(self.game.file(tl_files, tl_file))
            try:
                scene = lsx.load(self.game.file(tl_files, tl_file[:-4] + "_Scene.lsx"))
            except FileNotFoundError:
                scene = None
        slots = apply_patches(dlg_tree, patches, timeline, scene, self.game, name)
        return {"source": src, "resource": res, "dialog": dlg_tree, "timeline": timeline, "slots": slots,
                "timeline_resource": tl[1] if need_tl else None, "timeline_source": tl[0] if need_tl else None}

    def build(self):
        """Собирает все варианты в self.out. Возвращает манифест (для Lua) и записи банков."""
        manifest, dialog_bank, timeline_bank, copies = [], [], [], []
        for name, own in sorted(self.own.items()):
            partner_patches = [(p["uuid"], x) for p in self.partners for x in p["patches"].get(name, [])]
            sets = {"own": own}
            if partner_patches:
                everyone = [(self.mod, x) for x in own] + partner_patches
                sets["all"] = [x for _, x in sorted(everyone, key=lambda t: (t[0], t[1].id))]
            bases = [b for b in self.bases if self._base_has(b, name)]
            # Диалог, который подменяет мод-база, в наш банк не кладём: подмена только из Lua. Если она не
            # сработает, пропадут наши правки, а не правки базы (не затираем чужое).
            entry = {"name": name, "partners": sorted({u for u, _ in partner_patches}), "bases": {}, "variants": {},
                     "bank": not bases}
            for base in [None] + bases:
                for set_name, patches in sets.items():
                    variant = set_name + (f"@{base['uuid']}" if base else "")
                    r = self.build_variant(name, patches, base)
                    sub = sub_path(lsx.value(r["resource"], "SourceFile"))
                    default = variant == "own"
                    dpath = self.own_dialog(sub) if default else self.variant_dialog(variant, sub)
                    lsx.save(r["dialog"], self.out / (dpath + ".lsx"))
                    v = {"dialog": dpath.replace(self.ph, "{MOD}")}
                    if r["timeline"] is not None:
                        tpath = self.own_timeline(name) if default else self.variant_timeline(variant, name)
                        lsx.save(r["timeline"], self.out / (tpath + ".lsx"))
                        v["timeline"] = tpath.replace(self.ph, "{MOD}")
                        if default:   # сцена рядом с нашим таймлайном — её ищут по имени рядом с ним
                            copies.append((r["timeline_source"],
                                           lsx.value(r["timeline_resource"], "SourceFile")[:-4] + "_Scene.lsf",
                                           tpath[:-4] + "_Scene.lsf"))
                    entry["variants"][variant] = v
                    if default:
                        entry["vanilla"] = {"dialog": self.game.binary_path(lsx.value(r["resource"], "SourceFile"))}
                        if r["timeline_resource"] is not None:
                            entry["vanilla"]["timeline"] = lsx.value(r["timeline_resource"], "SourceFile")
                        if entry["bank"]:
                            dialog_bank.append(self._dialog_resource(r, sub))
                            if r["timeline"] is not None:
                                timeline_bank.append(self._timeline_resource(r, name, own))
                    if base and set_name == "own":
                        bres = r["resource"]
                        entry["bases"][base["uuid"]] = {"dialog": self.game.binary_path(lsx.value(bres, "SourceFile"))}
                        if r["timeline_resource"] is not None:
                            entry["bases"][base["uuid"]]["timeline"] = lsx.value(r["timeline_resource"], "SourceFile")
            entry["own"] = entry["variants"]["own"]
            manifest.append(entry)
        for src, inner, dst in copies:
            path = self.game.file(VANILLA if src in VANILLA else [src], inner)   # .lsf → .lsx в кэше; кладём исходный .lsf как есть
            raw = Path(str(path)[:-4]) if str(path).endswith(".lsf.lsx") else path
            (self.out / dst).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(raw, self.out / dst)
        self._write_bank("DialogBank", dialog_bank,
                         f"Public/{self.ph}/Content/Assets/Dialogs/[PAK]_DialogKit/DialogKit_Dialogs.lsf.lsx")
        self._write_bank("TimelineBank", timeline_bank,
                         f"Public/{self.ph}/Content/Generated/[PAK]_DialogKit/DialogKit_Timelines.lsf.lsx")
        return manifest

    def _base_has(self, base, name):
        found = self.game.dialog_resource(VANILLA, name)
        return bool(found) and lsx.value(found[1], "ID") in self.game.banks(base["source"])["dialogs"]

    def _dialog_resource(self, r, sub):
        res = copy.deepcopy(r["resource"])
        lsx.set_value(res, "SourceFile", f"Mods/{self.ph}/Story/Dialogs/{sub}.lsj")
        lines = lsx.kids(res, "SpeakerSlotsWithLines")
        count = len(r["dialog"].getroot().find("region/node").find(".//node[@id='speakerlist']/children")
                    .findall("node"))
        while len(lines) < count:    # новые слоты
            n = lsx.element("SpeakerSlotsWithLines", attrs=[("HasLines", "bool", "False")])
            lsx.children(res, create=True).append(n)
            lines = lsx.kids(res, "SpeakerSlotsWithLines")
        for i in r["slots"]:
            if 0 <= i < len(lines):
                lsx.set_value(lines[i], "HasLines", "True")
        return res

    def _timeline_resource(self, r, name, patches):
        res = copy.deepcopy(r["timeline_resource"])
        lsx.set_value(res, "SourceFile", self.own_timeline(name))
        deps = {lsx.value(d, "Object") for d in lsx.kids(res, "DependencyCache")}
        for p in patches:
            for op in p.ops:
                if op["op"] == "add_speaker" and op["character"] not in deps:
                    lsx.children(res, create=True).append(
                        lsx.element("DependencyCache", attrs=[("Object", "guid", op["character"])]))
        return res

    def _write_bank(self, region, resources, rel):
        if not resources:
            return
        root = lsx.ET.Element("save")
        lsx.ET.SubElement(root, "version", {"major": "4", "minor": "0", "revision": "9", "build": "0"})
        reg = lsx.ET.SubElement(root, "region", {"id": region})
        bank = lsx.ET.SubElement(reg, "node", {"id": region})
        ch = lsx.ET.SubElement(bank, "children")
        for res in resources:
            ch.append(res)
        lsx.save(lsx.ET.ElementTree(root), self.out / rel)


def lua_manifest(manifest, mod, table="DialogKitManifest"):
    """Манифест как Lua-таблица. {MOD} в путях Lua подставляет сам (папка модуля)."""
    def s(x):
        return '"' + x.replace("\\", "/") + '"'

    lines = [f"-- Сгенерировано DialogKit. Мод {mod}.", f"{table} = {{"]
    for e in manifest:
        lines.append(f"    {{ name = {s(e['name'])}, bank = {'true' if e['bank'] else 'false'},")
        v = e.get("vanilla", {})
        lines.append(f"      vanilla = {{ dialog = {s(v['dialog'])}" +
                     (f", timeline = {s(v['timeline'])}" if v.get("timeline") else "") + " },")
        lines.append("      partners = {" + ", ".join(s(p) for p in e["partners"]) + "},")
        lines.append("      bases = {")
        for u, b in sorted(e["bases"].items()):
            lines.append(f"        [{s(u)}] = {{ dialog = {s(b['dialog'])}" +
                         (f", timeline = {s(b['timeline'])}" if b.get("timeline") else "") + " },")
        lines.append("      },")
        lines.append("      variants = {")
        for v, f in sorted(e["variants"].items()):
            lines.append(f"        [{s(v)}] = {{ dialog = {s(f['dialog'])}" +
                         (f", timeline = {s(f['timeline'])}" if f.get("timeline") else "") + " },")
        lines.append("      },")
        lines.append("    },")
    lines.append("}")
    return "\n".join(lines) + "\n"
