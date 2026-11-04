"""Group the chat's parts into the things they belong to, and test two boxes for touching."""


ASSEMBLY_MIN = 3  # parts a group needs before its gaps are measured



def _tokens(name):
    base = name.rsplit(".", 1)[0] if name.rsplit(".", 1)[-1].isdigit() else name  # "Arm.001" is "Arm"
    return base.split("_")



def _plain(token):
    """A second name part that names a thing, not a number or a side such as L, R or A."""
    return not token.isdigit() and len(token) > 1



def _overlap(a, b, gap):
    return all(a[0][i] - gap <= b[1][i] and b[0][i] - gap <= a[1][i] for i in range(3))



def _label(key, how):
    return key + (" and its children" if how[key] == "parent" else "_*")



def _groups(parts):
    """``(groups, how)``: the parts of each group by its key, and how each group was found ("parent" or
    "name"); see ``loose_parts``."""
    by_name = {p["name"]: p for p in parts}
    parents = {p["parent"] for p in parts if p.get("parent") in by_name}

    def top(p):
        seen = set()
        while p.get("parent") in by_name and p["name"] not in seen:
            seen.add(p["name"])
            p = by_name[p["parent"]]
        return p["name"]

    groups, how, rest = {}, {}, []
    for p in parts:
        if p.get("parent") in by_name or p["name"] in parents:
            root = top(p)
            groups.setdefault(root, []).append(p)
            how[root] = "parent"
        else:
            rest.append(p)
    named = []  # (part, its whole name, its three-part start, its two-part start)
    copies = {}  # names that differ only by a last number ("Car_Tyre_1" to "_4") are copies, apart by design
    for p in rest:
        t = _tokens(p["name"])
        if len(t) >= 2 and t[-1].isdigit():
            copies["_".join(t[:-1])] = copies.get("_".join(t[:-1]), 0) + 1
    for p in rest:
        t = _tokens(p["name"])
        if len(t) >= 2 and t[-1].isdigit() and copies["_".join(t[:-1])] > 1:
            continue
        named.append((p, "_".join(t), "_".join(t[:2]) if len(t) >= 3 else None,
                      t[0] if len(t) >= 2 and _plain(t[1]) else None))
    starts2 = {two for _p, _w, two, _o in named if two}
    starts1 = {one for _p, _w, _t, one in named if one}
    size2, size1 = {}, {}  # parts per name start; a part whose whole name is the start counts too ("Person_A")
    for _p, whole, two, one in named:
        for key in {two, whole if whole in starts2 else None} - {None}:
            size2[key] = size2.get(key, 0) + 1
        for key in {one, whole if whole in starts1 else None} - {None}:
            size1[key] = size1.get(key, 0) + 1
    for p, whole, two, one in named:
        candidates = [k for k in (two, whole, one) if k in how]  # a part named after a parent joins that group
        candidates += [k for k in (two, whole) if size2.get(k, 0) >= ASSEMBLY_MIN]
        candidates += [k for k in (one, whole) if size1.get(k, 0) >= ASSEMBLY_MIN]
        if not candidates:
            continue
        groups.setdefault(candidates[0], []).append(p)
        how.setdefault(candidates[0], "name")
    return groups, how
