"""Доступ к данным игры и установленных модов: паки, банки диалогов и таймлайнов, бинарные диалоги.

Как игра находит диалог (проверено 2026-09-27 по пакам игры и MGNTN_WyllPactPoints): банк диалогов
(`Public/<модуль>/Content/…/*.lsf`, регион DialogBank) хранит ресурс с ID и SourceFile
(`Mods/<модуль>/Story/Dialogs/<путь>.lsj`), а игра грузит `Story/DialogsBinary/<путь>.lsf`. Мод подменяет
диалог, кладя в свой банк ресурс с тем же ID и своим SourceFile; побеждает мод позже в порядке загрузки.
Таймлайн — так же: TimelineBank, ресурс с DialogResourceId и SourceFile на .lsf таймлайна.
Внутренний UUID файла диалога игра для этого не использует (у мода он совпадает, потому что файл — копия).
"""
import os
import pickle
import re
import subprocess
from pathlib import Path

from . import lsx

VANILLA = ["Shared.pak", "Gustav.pak", "GustavX.pak", "Patch8_HotFix9.pak"]   # в порядке загрузки
VOICEMETA = "Localization/VoiceMeta.pak"


class Game:
    def __init__(self, divine, game_dir, cache_dir, mods_dir=None):
        self.divine = str(divine)
        self.data = Path(game_dir) / "Data"
        self.cache = Path(cache_dir)
        self.mods = Path(mods_dir) if mods_dir else \
            Path(os.environ["LOCALAPPDATA"]) / "Larian Studios" / "Baldur's Gate 3" / "Mods"
        self._banks = {}

    # ── Divine ───────────────────────────────────────────────────────────────
    def run(self, *args):
        r = subprocess.run([self.divine, "-g", "bg3", *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise RuntimeError(f"Divine {' '.join(map(str, args))}:\n{r.stdout}\n{r.stderr}")
        return r.stdout

    def extract(self, pak, pattern, key):
        """Распаковать файлы пака по шаблону в кэш (один раз). Возвращает корень распаковки."""
        root = self.cache / key
        stamp = root / (".done_" + re.sub(r"[^A-Za-z0-9]+", "_", pattern))
        if not stamp.exists():
            root.mkdir(parents=True, exist_ok=True)
            self.run("-a", "extract-package", "-s", Path(pak).resolve(), "-d", root.resolve(), "-x", pattern)
            stamp.write_text("ok")
        return root

    def to_lsx(self, lsf):
        lsf = Path(lsf)
        out = lsf.with_name(lsf.name + ".lsx")
        if not out.exists():
            self.run("-a", "convert-resource", "-s", lsf.resolve(), "-d", out.resolve())
        return out

    # ── Источники: игра и моды ───────────────────────────────────────────────
    def pak_path(self, source):
        """source: пак игры ('Gustav.pak') или пак мода в папке Mods (имя файла без .pak, можно начало)."""
        p = self.data / source
        if p.exists():
            return p
        exact = self.mods / f"{source}.pak"
        if exact.exists():
            return exact
        for pak in sorted(self.mods.glob("*.pak")):
            if pak.stem.startswith(source + "_"):
                return pak
        raise FileNotFoundError(f"пак {source} не найден ни в игре, ни в {self.mods}")

    def mod_info(self, source):
        """(Folder, UUID, Version64) из meta.lsx пака мода."""
        pak = self.pak_path(source)
        root = self.extract(pak, "Mods/*/meta.lsx", f"meta/{pak.stem}")
        t = next(root.glob("Mods/*/meta.lsx")).read_text(encoding="utf-8-sig", errors="replace")
        info = t[t.index('id="ModuleInfo"'):]
        get = lambda k: re.search(rf'id="{k}" type="[^"]+" value="([^"]*)"', info).group(1)
        return get("Folder"), get("UUID"), get("Version64")

    def banks(self, source):
        """Банки источника: {'dialogs': {ID: xml Resource}, 'timelines': {DialogResourceId: xml Resource}}."""
        if source in self._banks:
            return self._banks[source]
        pak = self.pak_path(source)
        cache = self.cache / "banks" / f"{pak.stem}.pkl"
        if cache.exists() and cache.stat().st_mtime >= pak.stat().st_mtime:
            self._banks[source] = pickle.loads(cache.read_bytes())
            return self._banks[source]
        root = self.extract(pak, "Public/*/Content/*", f"banks/{pak.stem}")
        out = {"dialogs": {}, "timelines": {}}
        for f in sorted(root.rglob("*.lsf")):
            for region in lsx.load(self.to_lsx(f)).getroot().findall("region"):   # регионов бывает несколько
                kind = region.get("id")
                if kind not in ("DialogBank", "TimelineBank"):
                    continue
                for res in lsx.kids(region.find("node"), "Resource"):
                    key = lsx.value(res, "ID") if kind == "DialogBank" else lsx.value(res, "DialogResourceId")
                    out["dialogs" if kind == "DialogBank" else "timelines"][key] = \
                        lsx.ET.tostring(res, encoding="unicode")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(pickle.dumps(out))
        self._banks[source] = out
        return out

    def dialog_resource(self, sources, name):
        """Ресурс диалога по имени файла (…/<name>.lsj; если нет — по Name банка), позже в sources — главнее."""
        by_file = by_name = None
        for s in sources:
            for xml in self.banks(s)["dialogs"].values():
                if name not in xml:
                    continue
                res = lsx.ET.fromstring(xml)
                if lsx.value(res, "SourceFile", "").endswith(f"/{name}.lsj"):
                    by_file = (s, res)
                elif lsx.value(res, "Name") == name:
                    by_name = (s, res)
        return by_file or by_name

    def dialog_by_id(self, sources, rid):
        found = None
        for s in sources:
            xml = self.banks(s)["dialogs"].get(rid)
            if xml:
                found = (s, lsx.ET.fromstring(xml))
        return found

    def timeline_by_dialog(self, sources, rid):
        found = None
        for s in sources:
            xml = self.banks(s)["timelines"].get(rid)
            if xml:
                found = (s, lsx.ET.fromstring(xml))
        return found

    def listing(self, source):
        pak = self.pak_path(source)
        cache = self.cache / "listing" / f"{pak.stem}.txt"
        if not cache.exists() or cache.stat().st_mtime < pak.stat().st_mtime:
            files = [l.split("\t")[0] for l in self.run("-a", "list-package", "-s", pak.resolve()).splitlines() if "\t" in l]
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text("\n".join(files), encoding="utf-8")
        return set(cache.read_text(encoding="utf-8").splitlines())

    def find(self, sources, inner):
        """Последний (главный) источник, в паке которого есть файл inner."""
        for s in reversed(list(sources)):
            if inner in self.listing(s):
                return s
        raise FileNotFoundError(f"{inner} нет ни в одном из {list(sources)}")

    def file(self, source, inner):
        """Файл из пака источника (распаковка в кэш) → путь к .lsx (для .lsf) или к самому файлу.
        source может быть списком источников — тогда берётся последний, где файл есть."""
        if isinstance(source, (list, tuple)):
            source = self.find(source, inner)
        pak = self.pak_path(source)
        root = self.extract(pak, inner, f"files/{pak.stem}")
        p = root / inner
        if not p.exists():
            raise FileNotFoundError(f"{inner} нет в {pak.name}")
        return self.to_lsx(p) if p.suffix == ".lsf" else p

    def voice_length(self, speaker, handle):
        """Длина озвученной реплики (сек) для персонажа speaker (UUID) по VoiceMeta игры; None — не озвучена."""
        key = speaker.replace("-", "")
        root = self.extract(self.data / VOICEMETA, f"*/Soundbanks/{key}.lsf", "voicemeta")
        files = list(root.rglob(f"{key}.lsf"))
        for f in files:
            t = self.to_lsx(f).read_text(encoding="utf-8-sig", errors="replace")
            m = re.search(rf'value="{handle}" />\s*<children>\s*<node id="MapValue">(.*?)</node>', t, re.S)
            if m:
                return float(re.search(r'id="Length" type="float" value="([^"]+)"', m.group(1)).group(1))
        return None

    @staticmethod
    def binary_path(source_file):
        """SourceFile банка (.lsj в Story/Dialogs) → путь бинарного диалога, который грузит игра."""
        return source_file.replace("/Story/Dialogs/", "/Story/DialogsBinary/", 1)[:-4] + ".lsf"
