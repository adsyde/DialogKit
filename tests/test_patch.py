"""Тесты DialogKit на выдуманном мини-диалоге (tests/fixtures), без файлов игры.

    python -m pytest tests
"""
import copy
import uuid
from pathlib import Path

import pytest

from dialogkit import lsx
from dialogkit.patch import Dialog, Patch, PatchError, apply_patches

FIX = Path(__file__).parent / "fixtures"
TE = "c226c99d-720c-4611-98c9-9ba1fe6df481"
REALLY_SH = "642d2aee-e3df-47e3-9f47-bbcd441bb9e0"
FLAG = "018440f2-8807-53d4-b844-1cde8a1c4e30"
Q1, Q2, R1, S1, S2, A1, A2, G1 = (f"00000000-0000-0000-0000-000000000{x}" for x in
                                  ("q01", "q02", "r01", "s01", "s02", "a01", "a02", "g01"))


def tree(name="mini_dialog.lsx"):
    return lsx.load(FIX / name)


def patch(ops, dialog="mini", pid="test/one", mod=TE):
    return Patch({"format": "dialogkit/1", "id": pid, "mod": mod, "dialog": dialog, "ops": ops})


def flags(node, key):
    out = []
    for block in lsx.kids(node, key):
        for fg in lsx.kids(block, "flaggroup"):
            for f in lsx.kids(fg, "flag"):
                out.append((lsx.value(fg, "type"), lsx.value(f, "UUID"), lsx.value(f, "value"), lsx.value(f, "paramval")))
    return out


def companion_copy(slot=2):
    """Как реплики спутников Team Effort: копия варианта «только для Шэдоухарт» со слотом спутника."""
    return {"op": "add_node", "like": Q2, "speaker": slot, "move_slot": [1, slot],
            "derive": {"ns": TE, "tag": str(slot)},
            "conditions_add": [{"type": "Tag", "flag": REALLY_SH, "value": False, "slot": 1},
                               {"type": "Global", "flag": FLAG, "value": True}]}


def test_companion_copy():
    t = tree()
    apply_patches(t, [patch([companion_copy()])], name="mini")
    d = Dialog(t)
    nid = str(uuid.uuid5(uuid.UUID(TE), f"{Q2}:2"))
    n = d.node(nid)
    assert lsx.value(n, "speaker") == "2"
    assert d.children_of(n) == [A1]                                   # исход тот же
    assert d.children_of(d.node(G1)) == [Q1, Q2, nid, R1]             # сразу после оригинала
    assert flags(n, "checkflags") == [("Tag", REALLY_SH, "True", "2"), ("Tag", REALLY_SH, "False", "1"),
                                      ("Global", FLAG, "True", None)]
    assert flags(n, "setflags") == [("Object", "00000000-0000-0000-0000-0000000000f2", "True", "2")]
    line = next(a for a in n.iter("attribute") if a.get("id") == "LineId").get("value")
    assert line == str(uuid.uuid5(uuid.UUID(TE), "00000000-0000-0000-0000-00000000l0q2:2"))
    # оригинал не тронут
    assert flags(d.node(Q2), "checkflags") == [("Tag", REALLY_SH, "True", "1")]


def test_deterministic():
    a, b = tree(), tree()
    p = [patch([companion_copy(), {"op": "add_node", "key": "x", "like": Q1, "text": "hNEW"}])]
    apply_patches(a, p, name="mini")
    apply_patches(b, p, name="mini")
    assert lsx.ET.tostring(a.getroot()) == lsx.ET.tostring(b.getroot())


def test_roll_mirrors_outcomes():
    t = tree()
    apply_patches(t, [patch([{"op": "add_node", "key": "charm", "like": R1, "text": "hCHARM",
                              "roll": {"skill": "Performance", "dc": "00000000-0000-0000-0000-0000000000d2"}}])],
                  name="mini")
    d = Dialog(t)
    n = d.node(patch([]).uid("charm"))
    assert d.children_of(n) == [S1, S2]                              # успех и провал — те же узлы
    assert lsx.value(n, "Skill") == "Performance" and lsx.value(n, "Ability") == "Charisma"
    assert lsx.value(n, "DifficultyClassID").endswith("d2")


def test_new_branch_with_voiced_answer():
    t, tl = tree(), tree("mini_timeline.lsx")
    p = patch([
        {"op": "add_node", "key": "ans", "like": A1, "text": "hVOICED", "parents": [], "voice": {"length": 2.0}},
        {"op": "add_node", "key": "q", "like": Q1, "text": "hQ", "children": ["@ans"]},
    ])
    apply_patches(t, [p], timeline_tree=tl, name="mini")
    d = Dialog(t)
    ans, q = p.uid("ans"), p.uid("q")
    assert d.children_of(d.node(q)) == [ans]
    assert q in d.children_of(d.node(G1))
    content = tl.getroot().find("region/node")
    effect = lsx.kid(content, "Effect")
    phases = lsx.kids(lsx.kid(effect, "Phases"), "Phase")
    assert [lsx.value(ph, "DialogNodeId") for ph in phases] == [G1, ans]
    assert float(lsx.value(effect, "Duration")) == pytest.approx(7.3)
    voice = [c for c in lsx.kids(lsx.kid(effect, "EffectComponents"), "EffectComponent")
             if lsx.value(c, "DialogNodeId") == ans][0]
    assert (lsx.value(voice, "StartTime"), lsx.value(voice, "EndTime"), lsx.value(voice, "PhaseIndex")) == ("5.0", "7.0", "1")


def test_add_speaker_and_timeline_actor():
    t, tl, sc = tree(), tree("mini_timeline.lsx"), tree("mini_scene.lsx")
    wyll = "c774d764-4a17-48dc-b470-32ace9ce447d"
    p = patch([{"op": "add_speaker", "key": "wyll", "character": wyll},
               {"op": "add_node", "key": "w", "like": Q2, "speaker": "@wyll", "move_slot": [1, "@wyll"]}])
    p.ops[1]["move_slot"] = [1, 3]
    slots = apply_patches(t, [p], timeline_tree=tl, scene_tree=sc, name="mini")
    d = Dialog(t)
    assert lsx.value(d.slots()[3], "list") == wyll and 3 in slots
    content = tl.getroot().find("region/node")
    sp = [(lsx.value(o, "MapKey"), lsx.value(o, "MapValue")) for o in lsx.kids(lsx.kid(content, "TimelineSpeakers"), "Object")]
    assert sp[-1] == ("3", p.uid("speaker:wyll"))
    actors = lsx.kids(lsx.kid(lsx.kid(content, "TimelineActorData"), "TimelineActorData"), "Object")
    v = actors[-1].find("children/node")
    assert (lsx.value(v, "Speaker"), lsx.value(v, "SceneActorIndex")) == ("3", "1")


def test_existing_speaker_reused():
    t = tree()
    p = patch([{"op": "add_speaker", "key": "sh", "character": "3ed74f06-3c60-42dc-83f6-f034cb47c679"}])
    apply_patches(t, [p], name="mini")
    assert len(Dialog(t).slots()) == 3


@pytest.mark.parametrize("op, msg", [
    ({"op": "add_node", "key": "x", "like": Q1, "children": []}, "тупик"),
    ({"op": "add_node", "key": "x", "like": Q1, "parents": []}, "ни к чему не подвешен"),
    ({"op": "add_node", "key": "x", "like": "nope"}, "нет в диалоге"),
    ({"op": "add_node", "key": "x", "like": Q1, "roll": {"skill": "Arcana"}}, "ActiveRoll"),
    ({"op": "add_child", "parent": G1, "child": A1}, "только новые узлы"),
])
def test_rules(op, msg):
    with pytest.raises(PatchError, match=msg):
        apply_patches(tree(), [patch([op])], name="mini")


def test_patches_in_order_and_two_mods():
    t = tree()
    mine = patch([companion_copy()], pid="te/lines")
    theirs = patch([{"op": "add_node", "key": "succ", "like": R1, "text": "hSUCC", "roll": {"skill": "Performance"}}],
                   pid="succ/lines", mod="a41f6c2e-9b37-4d58-b0e1-7c3d95f28e64")
    apply_patches(t, [mine, theirs], name="mini")
    kids = Dialog(t).children_of(Dialog(t).node(G1))
    assert len(kids) == 5 and kids[:3] == [Q1, Q2, str(uuid.uuid5(uuid.UUID(TE), f"{Q2}:2"))]


def test_wrong_dialog():
    with pytest.raises(PatchError, match="патч для other"):
        apply_patches(tree(), [patch([], dialog="other")], name="mini")


# ── add_roll: проверка рядом с вариантом без броска (очарование торговца) ──────
F_OK, F_BAD = "00000000-0000-0000-0000-0000000000f5", "00000000-0000-0000-0000-0000000000f6"
DC = "00000000-0000-0000-0000-0000000000d7"


def charm_roll(**extra):
    op = {"op": "add_roll", "key": "charm", "like": Q1, "text": "hCHARM",
          "roll": {"ability": "Charisma", "dc": DC},
          "conditions_add": [{"type": "Tag", "flag": REALLY_SH, "value": True, "slot": 1}],
          "success": {"set_flags_add": [{"type": "Object", "flag": F_OK, "value": True, "slot": 0}]},
          "failure": {"set_flags_add": [{"type": "Object", "flag": F_BAD, "value": True, "slot": 0}]}}
    op.update(extra)
    return op


def test_add_roll_both_outcomes_lead_where_option_leads():
    t = tree()
    p = patch([charm_roll()])
    apply_patches(t, [p], name="mini")
    d = Dialog(t)
    n, rs, rf = d.node(p.uid("charm")), d.node(p.uid("charm:success")), d.node(p.uid("charm:failure"))
    assert lsx.value(n, "constructor") == "ActiveRoll"
    assert (lsx.value(n, "Ability"), lsx.value(n, "Skill"), lsx.value(n, "RollType")) == ("Charisma", "", "RawAbility")
    assert (lsx.value(n, "DifficultyClassID"), lsx.value(n, "RollTargetSpeaker"), lsx.value(n, "speaker")) == (DC, "0", "1")
    assert d.children_of(n) == [p.uid("charm:success"), p.uid("charm:failure")]
    assert (lsx.value(rs, "Success"), lsx.value(rf, "Success")) == ("True", "False")
    assert d.children_of(rs) == [A1] and d.children_of(rf) == [A1]           # оба исхода — туда же, куда вариант
    assert flags(rs, "setflags") == [("Object", F_OK, "True", "0")]
    assert flags(rf, "setflags") == [("Object", F_BAD, "True", "0")]
    assert flags(n, "checkflags") == [("Tag", REALLY_SH, "True", "1")]
    assert d.children_of(d.node(G1)) == [Q1, p.uid("charm"), Q2, R1]         # сразу после варианта
    text = [a for a in n.iter("attribute") if a.get("id") == "TagText"][0]
    assert text.get("handle") == "hCHARM"
    line = next(a for a in n.iter("attribute") if a.get("id") == "LineId").get("value")
    assert line != "00000000-0000-0000-0000-00000000l0q1"
    assert lsx.value(d.node(Q1), "constructor") == "TagQuestion" and d.children_of(d.node(Q1)) == [A1]


def test_add_roll_deterministic():
    a, b = tree(), tree()
    apply_patches(a, [patch([charm_roll()])], name="mini")
    apply_patches(b, [patch([charm_roll()])], name="mini")
    assert lsx.ET.tostring(a.getroot()) == lsx.ET.tostring(b.getroot())


@pytest.mark.parametrize("extra, msg", [
    ({"like": R1}, "уже бросок"),
    ({"roll": {"ability": "Charisma"}}, "roll.dc"),
    ({"failure": {"children": [A2]}}, "можно только в исходы образца"),
])
def test_add_roll_rules(extra, msg):
    with pytest.raises(PatchError, match=msg):
        apply_patches(tree(), [patch([charm_roll(**extra)])], name="mini")


# ── text.replace_all: образец с несколькими вариантами текста ────────────────
def two_texts_tree():
    t = tree()
    q = Dialog(t).node(Q1)
    holder = lsx.kid(q, "TaggedTexts")
    extra = copy.deepcopy(lsx.kids(holder, "TaggedText")[0])
    rg = lsx.kid(extra, "RuleGroup", create=True)
    rules = lsx.kid(rg, "Rules", create=True)
    lsx.children(rules, create=True).append(lsx.element("Rule"))
    lsx.children(holder).append(extra)
    return t


def test_text_replace_all():
    t = two_texts_tree()
    with pytest.raises(PatchError, match="replace_all"):
        apply_patches(copy.deepcopy(t), [patch([{"op": "add_node", "key": "x", "like": Q1, "text": "hX"}])], name="mini")
    p = patch([{"op": "add_node", "key": "x", "like": Q1, "text": {"handle": "hX", "replace_all": True}}])
    apply_patches(t, [p], name="mini")
    n = Dialog(t).node(p.uid("x"))
    texts = [a.get("handle") for a in n.iter("attribute") if a.get("id") == "TagText"]
    assert texts == ["hX"]
    assert not list(n.iter("Rule")) and not [x for x in n.iter("node") if x.get("id") == "Rule"]
    q = Dialog(t).node(Q1)                                                  # оригинал — с двумя текстами
    assert len([a for a in q.iter("attribute") if a.get("id") == "TagText"]) == 2
