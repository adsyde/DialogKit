"""Работа с .lsx (XML LSLib): узлы <node id=…>, атрибуты <attribute id=… type=… value=…>."""
import xml.etree.ElementTree as ET
from pathlib import Path


def load(path):
    return ET.parse(path)


def save(tree, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def attr(node, name):
    for a in node.findall("attribute"):
        if a.get("id") == name:
            return a
    return None


def value(node, name, default=None):
    a = attr(node, name)
    return a.get("value") if a is not None else default


def set_value(node, name, val, typ=None):
    """Ставит значение атрибута; если его нет — добавляет перед <children> (тогда нужен typ)."""
    a = attr(node, name)
    if a is None:
        if typ is None:
            raise KeyError(f"нет атрибута {name}, а тип не задан")
        a = ET.Element("attribute", {"id": name, "type": typ, "value": ""})
        node.insert(len(node.findall("attribute")), a)
    a.set("value", str(val))
    return a


def children(node, create=False):
    c = node.find("children")
    if c is None and create:
        c = ET.SubElement(node, "children")
    return c


def kids(node, name):
    c = node.find("children")
    return [k for k in (c if c is not None else []) if k.get("id") == name]


def kid(node, name, create=False):
    found = kids(node, name)
    if found:
        return found[0]
    if not create:
        return None
    return ET.SubElement(children(node, True), "node", {"id": name})


def element(tag_id, key=None, attrs=()):
    """Новый <node id=tag_id key=key> с атрибутами [(id, type, value), …]."""
    n = ET.Element("node", {"id": tag_id, **({"key": key} if key else {})})
    for i, t, v in attrs:
        ET.SubElement(n, "attribute", {"id": i, "type": t, "value": str(v)})
    return n
