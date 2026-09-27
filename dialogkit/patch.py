"""Патч диалога (формат dialogkit/1) и его применение к дереву .lsx бинарного диалога (и таймлайна).

Патч только ДОПОЛНЯЕТ диалог: добавляет узлы, говорящих и ссылки на новые узлы. Существующие узлы,
переходы и флаги не меняются и не удаляются. Каждый новый узел делается «по образцу» (like) — узлу
того же диалога: у него те же дети (исходы), те же флаги и то же одобрение, если патч не задаёт другое;
новая ветка обязана заканчиваться в существующих узлах (без тупиков). Формат — README.md.
"""
import copy
import json
import uuid
from pathlib import Path

from . import lsx
from .lsx import ET

FORMAT = "dialogkit/1"
NS = uuid.UUID("5d1a6c3e-7f0b-4b8e-9c41-2a7e5d9f1b60")   # пространство имён DialogKit для uuid5
PLAYER_CHOICES = ("TagQuestion", "ActiveRoll", "PassiveRoll")
COMPANION_SCENE_ACTOR = "4"   # тип места в сцене (<имя>_Scene.lsx, TLActor/ActorType) для спутников


class PatchError(Exception):
    pass


class Patch:
    def __init__(self, data, origin="?"):
        if data.get("format") != FORMAT:
            raise PatchError(f"{origin}: format должен быть {FORMAT}")
        for k in ("id", "mod", "dialog", "ops"):
            if k not in data:
                raise PatchError(f"{origin}: нет поля {k}")
        self.data, self.origin = data, origin
        self.id, self.mod, self.dialog, self.ops = data["id"], data["mod"], data["dialog"], data["ops"]

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_text(encoding="utf-8")), str(path))

    def uid(self, key):
        return str(uuid.uuid5(NS, f"{self.id}:{self.dialog}:{key}"))

    def needs_timeline(self):
        return any(o["op"] == "add_speaker" or (o["op"] == "add_node" and o.get("voice")) for o in self.ops)


# ── вспомогательное: узлы диалога ────────────────────────────────────────────
class Dialog:
    def __init__(self, tree):
        self.tree = tree
        self.root = tree.getroot().find("region/node")
        self.nodes_root = lsx.kid(self.root, "nodes").find("children")
        self.by_id = {lsx.value(n, "UUID"): n for n in self.nodes_root.findall("node") if n.get("id") == "node"}
        self.speakers = lsx.kid(self.root, "speakerlist")

    def node(self, nid):
        n = self.by_id.get(nid)
        if n is None:
            raise PatchError(f"узла {nid} нет в диалоге")
        return n

    @staticmethod
    def child_refs(n):
        lst = lsx.kid(n, "children")
        lst = lst.find("children") if lst is not None else None
        return lst

    def children_of(self, n):
        lst = self.child_refs(n)
        return [lsx.value(c, "UUID") for c in (lst if lst is not None else [])]

    def parents_of(self, nid, exclude=()):
        return [p for i, p in self.by_id.items() if i not in exclude and nid in self.children_of(p)]

    def roots(self):
        return [r for r in self.nodes_root.findall("node") if r.get("id") == "RootNodes"]

    def add_ref(self, parent, child_id, after=None):
        """Ссылка parent → child_id (после after, иначе в конец). Существующие ссылки не трогаются."""
        lst = self.child_refs(parent)
        if lst is None:
            holder = lsx.kid(parent, "children", create=True)
            lst = lsx.children(holder, create=True)
        ids = [lsx.value(c, "UUID") for c in lst]
        if child_id in ids:
            return
        ref = lsx.element("child", attrs=[("UUID", "FixedString", child_id)])
        pos = ids.index(after) + 1 if after in ids else len(ids)
        lst.insert(pos, ref)

    def slots(self):
        """{индекс слота: узел speaker}."""
        out = {}
        for sl in lsx.kids(self.speakers, "speaker") if self.speakers is not None else []:
            out[int(lsx.value(sl, "index"))] = sl
        return out


def _flaggroup(block, typ, create=True):
    for fg in lsx.kids(block, "flaggroup"):
        if lsx.value(fg, "type") == typ:
            return fg
    if not create:
        return None
    fg = ET.SubElement(lsx.children(block, create=True), "node", {"id": "flaggroup", "key": "type"})
    ET.SubElement(fg, "attribute", {"id": "type", "type": "FixedString", "value": typ})
    ET.SubElement(fg, "children")
    return fg


def _add_flags(node, key, flags):
    """flags: [{"type": "Tag", "flag": uuid, "value": bool, "slot": int|None}]"""
    block = lsx.kid(node, key, create=True)
    for f in flags:
        fg = _flaggroup(block, f["type"])
        attrs = [("UUID", "FixedString", f["flag"]), ("value", "bool", "True" if f.get("value", True) else "False")]
        if f.get("slot") is not None:
            attrs.append(("paramval", "int32", f["slot"]))
        lsx.children(fg, create=True).append(lsx.element("flag", "UUID", attrs))


def _move_slot(node, frm, to):
    for key in ("checkflags", "setflags"):
        for block in lsx.kids(node, key):
            for fg in lsx.kids(block, "flaggroup"):
                for f in lsx.kids(fg, "flag"):
                    pv = lsx.attr(f, "paramval")
                    if pv is not None and pv.get("value") == str(frm):
                        pv.set("value", str(to))


# ── операции ─────────────────────────────────────────────────────────────────
class Context:
    def __init__(self, patch, dialog, timeline, scene, game, name):
        self.patch, self.dlg, self.timeline, self.scene, self.game, self.name = patch, dialog, timeline, scene, game, name
        self.keys = {}          # @ключ → uuid узла
        self.speakers = {}      # @ключ говорящего → индекс
        self.new_nodes = []
        self.likes = {}         # новый узел → образец

    def ref(self, r):
        if isinstance(r, str) and r.startswith("@"):
            if r[1:] not in self.keys:
                raise PatchError(f"{self.patch.origin}: ссылка на неизвестный узел {r}")
            return self.keys[r[1:]]
        return r

    def slot(self, s):
        if isinstance(s, str) and s.startswith("@"):
            if s[1:] not in self.speakers:
                raise PatchError(f"{self.patch.origin}: неизвестный говорящий {s}")
            return self.speakers[s[1:]]
        return int(s)


def op_add_speaker(ctx, op):
    """Новый говорящий (спутник) в конце списка: копия последнего слота с другим персонажем."""
    slots = ctx.dlg.slots()
    for i, sl in slots.items():
        if lsx.value(sl, "list") == op["character"]:
            ctx.speakers[op["key"]] = i       # уже есть — берём его слот
            return
    index = op.get("index", max(slots) + 1)
    if index in slots:
        raise PatchError(f"{ctx.patch.origin}: слот {index} уже занят")
    mapping = op.get("mapping") or ctx.patch.uid(f"speaker:{op['key']}")
    s = copy.deepcopy(lsx.kids(ctx.dlg.speakers, "speaker")[-1])   # последний в файле
    lsx.set_value(s, "index", index)
    lsx.set_value(s, "list", op["character"])
    lsx.set_value(s, "SpeakerMappingId", mapping)
    lsx.children(ctx.dlg.speakers).append(s)
    ctx.speakers[op["key"]] = index
    if op.get("timeline", "companion") and ctx.timeline is not None:
        _timeline_actor(ctx, index, mapping)


def _timeline_actor(ctx, index, mapping):
    """Актёр нового говорящего в таймлайне: копия записи другого спутника на свободном месте спутника в сцене."""
    content = ctx.timeline.getroot().find("region[@id='TimelineContent']/node")
    speakers = lsx.children(lsx.kid(content, "TimelineSpeakers"), create=True)
    actors = lsx.children(lsx.kid(lsx.kid(content, "TimelineActorData"), "TimelineActorData"))
    val = lambda o: o.find("children/node")
    comp = [o for o in actors if lsx.value(val(o), "SceneActorType") == COMPANION_SCENE_ACTOR]
    places = 0
    if ctx.scene is not None:
        places = sum(1 for a in ctx.scene.getroot().iter("node")
                     if a.get("id") == "TLActor" and lsx.value(a, "ActorType") == COMPANION_SCENE_ACTOR)
    used = {int(lsx.value(val(o), "SceneActorIndex", "0")) for o in comp}
    free = [i for i in range(places) if i not in used]
    if not comp or not free:
        raise PatchError(f"{ctx.name}: в сцене нет свободного места спутника (или не с кого копировать актёра)")
    speakers.append(lsx.element("Object", "MapKey", [("MapKey", "int32", index), ("MapValue", "guid", mapping)]))
    a = copy.deepcopy(comp[0])
    lsx.set_value(a, "MapKey", mapping)
    v = val(a)
    lsx.set_value(v, "Speaker", index, "int32")
    lsx.set_value(v, "SceneActorIndex", free[0], "int32")
    for snap in v.iter("node"):
        if snap.get("id") == "CompiledNodeSnapshots":
            cm = snap.find("children/node")
            if cm is not None and cm.find("children") is not None:
                cm.remove(cm.find("children"))
    actors.append(a)


def op_add_node(ctx, op):
    like = ctx.dlg.node(ctx.ref(op["like"]))
    like_id = lsx.value(like, "UUID")
    derive = op.get("derive")    # {"ns": uuid, "tag": str}: uuid5(ns, f"{исходный id}:{tag}") — для старых id
    if op.get("uuid"):
        nid = op["uuid"]
    elif derive:
        nid = str(uuid.uuid5(uuid.UUID(derive["ns"]), f"{like_id}:{derive['tag']}"))
    else:
        nid = ctx.patch.uid(op["key"])
    if nid in ctx.dlg.by_id:
        raise PatchError(f"{ctx.patch.origin}: узел {nid} уже есть")
    n = copy.deepcopy(like)
    lsx.set_value(n, "UUID", nid)
    if "speaker" in op:
        lsx.set_value(n, "speaker", ctx.slot(op["speaker"]), "int32")
    if "constructor" in op and op["constructor"] != lsx.value(n, "constructor"):
        raise PatchError(f"{ctx.patch.origin}: образец {like_id} — {lsx.value(n, 'constructor')}, а не {op['constructor']}")
    for a in n.iter("attribute"):
        if a.get("id") == "LineId":
            a.set("value", str(uuid.uuid5(uuid.UUID(derive["ns"]), f"{a.get('value')}:{derive['tag']}"))
                  if derive else ctx.patch.uid(f"{op.get('key', nid)}:line:{a.get('value')}"))
    if "text" in op:
        texts = [a for a in n.iter("attribute") if a.get("id") == "TagText"]
        if len(texts) != 1:
            raise PatchError(f"{ctx.patch.origin}: у образца {like_id} {len(texts)} текстов — задайте образец с одним")
        t = op["text"] if isinstance(op["text"], dict) else {"handle": op["text"]}
        texts[0].set("handle", t["handle"])
        texts[0].set("version", str(t.get("version", 1)))
    if "move_slot" in op:
        _move_slot(n, *op["move_slot"])
    if "roll" in op:
        if lsx.value(n, "constructor") != "ActiveRoll":
            raise PatchError(f"{ctx.patch.origin}: roll только по образцу ActiveRoll")
        names = {"ability": ("Ability", "string"), "skill": ("Skill", "string"),
                 "dc": ("DifficultyClassID", "guid"), "advantage": ("Advantage", "uint8"),
                 "roll_type": ("RollType", "string")}
        for k, v in op["roll"].items():
            lsx.set_value(n, names[k][0], v, names[k][1])
    if "approval" in op:
        lsx.set_value(n, "ApprovalRatingID", op["approval"], "guid")
    if "conditions" in op:                       # заменить условия целиком
        for block in lsx.kids(n, "checkflags"):
            lsx.children(n).remove(block)
        _add_flags(n, "checkflags", op["conditions"])
    _add_flags(n, "checkflags", op.get("conditions_add", []))
    _add_flags(n, "setflags", op.get("set_flags_add", []))
    if "children" in op:                         # новая ветка: дети — новые узлы патча или исходы образца
        holder = lsx.kid(n, "children", create=True)
        lst = lsx.children(holder, create=True)
        for c in list(lst):
            lst.remove(c)
        for c in op["children"]:
            lst.append(lsx.element("child", attrs=[("UUID", "FixedString", ctx.ref(c))]))
    ctx.dlg.nodes_root.insert(list(ctx.dlg.nodes_root).index(like) + 1, n)
    ctx.dlg.by_id[nid] = n
    if "key" in op:
        ctx.keys[op["key"]] = nid
    ctx.new_nodes.append(nid)
    ctx.likes[nid] = like_id
    # куда подвесить: по умолчанию — ко всем родителям образца сразу после него (и в корни, если он корневой)
    parents = op.get("parents", "like")
    if parents == "like":
        for p in ctx.dlg.parents_of(like_id, exclude=set(ctx.new_nodes)):   # родители — только узлы базы
            if lsx.value(p, "UUID") != nid:
                ctx.dlg.add_ref(p, nid, after=like_id)
        for r in ctx.dlg.roots():
            if lsx.value(r, "RootNodes") == like_id:
                ref = copy.deepcopy(r)
                lsx.set_value(ref, "RootNodes", nid)
                ctx.dlg.nodes_root.insert(list(ctx.dlg.nodes_root).index(r) + 1, ref)
    else:
        for p in parents:
            ctx.dlg.add_ref(ctx.dlg.node(ctx.ref(p["node"])), nid, after=ctx.ref(p.get("after")))
    if op.get("voice"):
        _voice_phase(ctx, n, op["voice"])


def _voice_phase(ctx, n, voice):
    """Фаза таймлайна с голосом для нового ответа NPC существующей озвученной репликой (как If Fate Chose
    Differently): Phase(Duration, DialogNodeId) + TLVoice(StartTime, EndTime, PhaseIndex, актёр) +
    TimelinePhases(узел → номер фазы); длительность эффекта растёт на длину фазы."""
    if ctx.timeline is None:
        raise PatchError(f"{ctx.name}: для голоса нужен таймлайн")
    content = ctx.timeline.getroot().find("region[@id='TimelineContent']/node")
    effect = lsx.kid(content, "Effect")
    phases = lsx.children(lsx.kid(effect, "Phases"), create=True)
    slot = int(lsx.value(n, "speaker"))
    speaker = ctx.dlg.slots()[slot]
    mapping = lsx.value(speaker, "SpeakerMappingId")
    handle = next(a.get("handle") for a in n.iter("attribute") if a.get("id") == "TagText")
    length = voice.get("length")
    if length is None:
        if ctx.game is None:
            raise PatchError(f"{ctx.name}: длина реплики {handle} не задана, а данных игры нет")
        length = ctx.game.voice_length(lsx.value(speaker, "list").split(";")[0], handle)
        if length is None:
            raise PatchError(f"{ctx.name}: реплика {handle} не озвучена у говорящего слота {slot}")
    start = float(lsx.value(effect, "Duration", "0"))
    duration = round(length + voice.get("pad", 0.3), 4)
    index = len(lsx.kids(lsx.kid(effect, "Phases"), "Phase"))
    nid = lsx.value(n, "UUID")
    ph = lsx.element("Phase", attrs=[("Duration", "float", duration), ("PlayCount", "int32", 1),
                                     ("DialogNodeId", "guid", nid)])
    ET.SubElement(ET.SubElement(ph, "children"), "node", {"id": "QuestionHoldAutomation"})
    phases.append(ph)
    comps = lsx.children(lsx.kid(effect, "EffectComponents"), create=True)
    vc = lsx.element("EffectComponent", attrs=[
        ("Type", "LSString", "TLVoice"), ("ID", "guid", ctx.patch.uid(f"voice:{nid}")),
        ("StartTime", "float", round(start, 4)), ("EndTime", "float", round(start + length, 4)),
        ("PhaseIndex", "int64", index), ("DialogNodeId", "guid", nid), ("ReferenceId", "guid", nid),
        ("PerformanceFade", "double", 0), ("FadeIn", "double", 0), ("FadeOut", "double", 0)])
    ET.SubElement(ET.SubElement(vc, "children"), "node", {"id": "Actor"}).append(
        ET.Element("attribute", {"id": "UUID", "type": "guid", "value": mapping}))
    comps.append(vc)
    tp = lsx.kid(content, "TimelinePhases", create=True)
    obj = lsx.kid(tp, "Object", create=True)
    lsx.children(obj, create=True).append(
        lsx.element("Object", "MapKey", [("MapKey", "guid", nid), ("MapValue", "uint64", index)]))
    lsx.set_value(effect, "Duration", round(start + duration, 4), "float")


def op_add_child(ctx, op):
    parent = ctx.dlg.node(ctx.ref(op["parent"]))
    child = ctx.ref(op["child"])
    ctx.dlg.node(child)
    if child not in ctx.new_nodes:
        raise PatchError(f"{ctx.patch.origin}: add_child может подвешивать только новые узлы патча")
    ctx.dlg.add_ref(parent, child, after=ctx.ref(op.get("after")))


OPS = {"add_speaker": op_add_speaker, "add_node": op_add_node, "add_child": op_add_child}


def _validate(ctx):
    """Новые ветки должны кончаться в существующих узлах; у нового узла — дети, если они были у образца."""
    new = set(ctx.new_nodes)
    for nid in ctx.new_nodes:
        n = ctx.dlg.by_id[nid]
        kids_ = ctx.dlg.children_of(n)
        like_kids = ctx.dlg.children_of(ctx.dlg.by_id[ctx.likes[nid]])
        if not kids_ and like_kids:
            raise PatchError(f"{ctx.name}: новый узел {nid} — тупик (у образца есть продолжение)")
        for k in kids_:
            if k not in ctx.dlg.by_id:
                raise PatchError(f"{ctx.name}: новый узел {nid} ссылается на несуществующий {k}")
        # от нового узла через новые узлы должен быть путь к старым
        seen, stack, reaches_old = set(), [nid], not kids_
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            xk = ctx.dlg.children_of(ctx.dlg.by_id[x])
            if not xk and not ctx.dlg.children_of(ctx.dlg.by_id[ctx.likes[x]]):
                reaches_old = True      # конец беседы, как у образца
            for k in xk:
                if k in new:
                    stack.append(k)
                else:
                    reaches_old = True
        if not reaches_old:
            raise PatchError(f"{ctx.name}: ветка от нового узла {nid} не возвращается в диалог игры")
        if not any(nid in ctx.dlg.children_of(p) for p in ctx.dlg.by_id.values()) and \
                not any(lsx.value(r, "RootNodes") == nid for r in ctx.dlg.roots()):
            raise PatchError(f"{ctx.name}: новый узел {nid} ни к чему не подвешен")


def apply_patches(dialog_tree, patches, timeline_tree=None, scene_tree=None, game=None, name="?"):
    """Применить патчи по порядку. Деревья меняются на месте. Возвращает {слот: True} — слоты с репликами."""
    dlg = Dialog(dialog_tree)
    before = set(dlg.by_id)
    for p in patches:
        if p.dialog != name and name != "?":
            raise PatchError(f"{p.origin}: патч для {p.dialog}, а собирается {name}")
        ctx = Context(p, dlg, timeline_tree, scene_tree, game, name)
        for op in p.ops:
            if op["op"] not in OPS:
                raise PatchError(f"{p.origin}: неизвестная операция {op['op']}")
            OPS[op["op"]](ctx, op)
        _validate(ctx)
    missing = before - set(dlg.by_id)
    if missing:
        raise PatchError(f"{name}: пропали узлы игры {sorted(missing)[:3]}")
    return sorted({int(lsx.value(n, "speaker")) for n in dlg.by_id.values()
                   if lsx.value(n, "speaker") not in (None, "-1", "-666")})
