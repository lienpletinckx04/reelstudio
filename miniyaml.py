#!/usr/bin/env python3
"""
miniyaml.py — een kleine, afhankelijkheidsvrije lezer voor het storyboard.

Ondersteunt precies wat het storyboard nodig heeft:
  sleutel: waarde
  sleutel:
    - item
    - sleutel: waarde      (lijst van mappings)
      andere: waarde
  lijst: [a, b, c]          (inline lijst)
  "tekst met: dubbelpunt"   (aanhalingstekens)
  # commentaar

Waarden worden omgezet: getallen → int/float, ja/nee/true/false → bool,
leeg → None. Al de rest blijft tekst (ook tijden zoals 1:03 — die zet het
storyboard zelf om).
"""
import re


class YamlFout(Exception):
    pass


_NUM = re.compile(r"^-?\d+(\.\d+)?$")


def _strip_comment(line):
    out = []
    q = None
    for i, ch in enumerate(line):
        if q:
            out.append(ch)
            if ch == q:
                q = None
            continue
        if ch in ("'", '"'):
            q = ch
            out.append(ch)
            continue
        if ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).rstrip()


def _scalar(s):
    s = s.strip()
    if s == "" or s == "~" or s.lower() == "null":
        return None
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        parts, cur, q = [], "", None
        for ch in inner:
            if q:
                cur += ch
                if ch == q:
                    q = None
            elif ch in "\"'":
                q = ch
                cur += ch
            elif ch == ",":
                parts.append(cur)
                cur = ""
            else:
                cur += ch
        parts.append(cur)
        return [_scalar(p) for p in parts]
    if s.startswith("{") and s.endswith("}"):
        inner = s[1:-1].strip()
        out = {}
        if not inner:
            return out
        parts, cur, q = [], "", None
        for ch in inner:
            if q:
                cur += ch
                if ch == q:
                    q = None
            elif ch in "\"'":
                q = ch
                cur += ch
            elif ch == ",":
                parts.append(cur)
                cur = ""
            else:
                cur += ch
        parts.append(cur)
        for p in parts:
            if ":" not in p:
                raise YamlFout(f"inline mapping zonder dubbelpunt: {p}")
            k, v = p.split(":", 1)
            out[k.strip()] = _scalar(v)
        return out
    low = s.lower()
    if low in ("ja", "true", "yes"):
        return True
    if low in ("nee", "false", "no"):
        return False
    if _NUM.match(s):
        return float(s) if "." in s else int(s)
    return s


def _split_kv(content):
    """'sleutel: waarde' → (sleutel, waarde) of None als het geen mapping-regel is."""
    if content.startswith(("'", '"')):
        return None
    m = re.match(r"^([A-Za-z0-9_\-]+):(?:\s+(.*))?$", content)
    if not m:
        return None
    return m.group(1), (m.group(2) or "")


def loads(text):
    lines = []
    for n, raw in enumerate(text.splitlines(), 1):
        raw = raw.replace("\t", "    ")
        s = _strip_comment(raw)
        if not s.strip():
            continue
        indent = len(s) - len(s.lstrip(" "))
        lines.append((indent, s.strip(), n))
    pos = [0]

    def parse_block(indent):
        if pos[0] >= len(lines):
            return None
        ind, content, n = lines[pos[0]]
        if ind != indent:
            raise YamlFout(f"regel {n}: onverwachte inspringing")
        if content.startswith("- ") or content == "-":
            return parse_list(indent)
        return parse_map(indent)

    def parse_map(indent):
        out = {}
        while pos[0] < len(lines):
            ind, content, n = lines[pos[0]]
            if ind < indent:
                break
            if ind > indent:
                raise YamlFout(f"regel {n}: te diep ingesprongen")
            if content.startswith("- "):
                break
            kv = _split_kv(content)
            if not kv:
                raise YamlFout(f"regel {n}: verwacht 'sleutel: waarde', kreeg: {content}")
            key, val = kv
            pos[0] += 1
            if val.strip() == "":
                # geneste blok?
                if pos[0] < len(lines) and lines[pos[0]][0] > indent:
                    out[key] = parse_block(lines[pos[0]][0])
                else:
                    out[key] = None
            else:
                out[key] = _scalar(val)
        return out

    def parse_list(indent):
        out = []
        while pos[0] < len(lines):
            ind, content, n = lines[pos[0]]
            if ind < indent:
                break
            if ind > indent:
                raise YamlFout(f"regel {n}: te diep ingesprongen in lijst")
            if not (content.startswith("- ") or content == "-"):
                break
            item = content[2:].strip() if content != "-" else ""
            kv = _split_kv(item) if item else None
            if kv:
                # lijst-item dat een mapping is: herschrijf de regel als een
                # mapping-regel op indent+2 en lees de rest van het blok mee.
                lines[pos[0]] = (indent + 2, item, n)
                out.append(parse_map(indent + 2))
            elif item == "":
                pos[0] += 1
                if pos[0] < len(lines) and lines[pos[0]][0] > indent:
                    out.append(parse_block(lines[pos[0]][0]))
                else:
                    out.append(None)
            else:
                pos[0] += 1
                out.append(_scalar(item))
        return out

    if not lines:
        return {}
    result = parse_block(lines[0][0])
    if pos[0] < len(lines):
        ind, content, n = lines[pos[0]]
        raise YamlFout(f"regel {n}: kon dit niet plaatsen: {content}")
    return result


def load(path):
    with open(path, encoding="utf-8") as fh:
        return loads(fh.read())


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(load(sys.argv[1]), indent=2, ensure_ascii=False))
