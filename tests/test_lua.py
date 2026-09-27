"""Выбор варианта в Lua (dialogkit/lua/DialogKit.lua) на заглушках Script Extender. Нужен пакет lupa."""
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")

LUA = (Path(__file__).parent.parent / "dialogkit/lua/DialogKit.lua").read_text(encoding="utf-8")
TE, SUCC, IFCD = "te-uuid", "succ-uuid", "ifcd-uuid"
MANIFEST = """
M = {
  { name = "Shared", partners = {"succ-uuid"}, bases = {},
    variants = { own = { dialog = "Mods/{MOD}/Story/DialogsBinary/A/Shared.lsf" },
                 all = { dialog = "Mods/{MOD}/DialogKit/all/A/Shared.lsf" } } },
  { name = "Wyll", bank = false, vanilla = { dialog = "Mods/GustavDev/Story/DialogsBinary/C/Wyll.lsf" },
    partners = {}, bases = { ["ifcd-uuid"] = { dialog = "Mods/IFCD/Story/DialogsBinary/C/Wyll.lsf" } },
    variants = { own = { dialog = "Mods/{MOD}/Story/DialogsBinary/C/Wyll.lsf" },
                 ["own@ifcd-uuid"] = { dialog = "Mods/{MOD}/DialogKit/own_at_ifcd/C/Wyll.lsf" } } },
  { name = "Solo", partners = {}, bases = {},
    variants = { own = { dialog = "Mods/{MOD}/Story/DialogsBinary/A/Solo.lsf" } } },
}
"""


def run(order):
    L = lupa.LuaRuntime()
    L.execute("""
        overrides = {}
        LOADED = {}
        Ext = { Mod = {}, IO = {} }
        function Ext.Mod.GetLoadOrder() return ORDER end
        function Ext.Mod.IsModLoaded(u) return LOADED[u] == true end
        function Ext.Mod.GetMod(u) return { Info = { Directory = "TE_Folder" } } end
        function Ext.IO.AddPathOverride(a, b) overrides[a] = b end
    """)
    L.execute("ORDER = {" + ",".join(f'"{u}"' for u in order) + "}")
    for u in order:
        L.execute(f'LOADED["{u}"] = true')
    L.execute(MANIFEST)
    dk = L.execute(LUA)
    dk.Apply(TE, L.globals().M, None)
    return dict(L.globals().overrides.items())


def test_alone():
    # всё из нашего банка; диалог базы (не в нашем банке) — через подмену файла игры
    assert run([TE]) == {"Mods/GustavDev/Story/DialogsBinary/C/Wyll.lsf": "Mods/TE_Folder/Story/DialogsBinary/C/Wyll.lsf"}


def test_partner_earlier_we_serve_all():
    o = run([SUCC, TE])
    assert o["Mods/TE_Folder/Story/DialogsBinary/A/Shared.lsf"] == "Mods/TE_Folder/DialogKit/all/A/Shared.lsf"


def test_partner_later_we_do_nothing_for_shared():
    assert "Mods/TE_Folder/Story/DialogsBinary/A/Shared.lsf" not in run([TE, SUCC])   # общий подменяет партнёр


@pytest.mark.parametrize("order", [[IFCD, TE], [TE, IFCD]])
def test_base_any_order_we_override_its_file(order):
    o = run(order)
    assert o == {"Mods/IFCD/Story/DialogsBinary/C/Wyll.lsf": "Mods/TE_Folder/DialogKit/own_at_ifcd/C/Wyll.lsf"}
