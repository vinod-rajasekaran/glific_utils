"""Layered left-to-right graph layout (a small Sugiyama layout), with no dependencies.

    layout(sizes, edges, layer_of=None) -> Layout

sizes     {node id: (width, height)}
edges     [(source id, target id)]; self-loops are ignored
layer_of  optional {node id: layer} for nodes whose layer is fixed by the caller
soft      edges that give way when they close a loop (drawn as a loop arc instead)

Steps: break cycles, give each node the layer after the longest chain that leads to it,
add a waypoint in every layer a long edge crosses, order each layer by the average
position of its neighbours (sweeping both ways), then set heights so each node sits
near its neighbours without overlapping. Edges come back as lists of points through
their waypoints, so they run in the gaps between nodes instead of through them.
"""
from collections import defaultdict
from dataclasses import dataclass, field

GAP_X = 72      # horizontal gap between layers
GAP_Y = 26      # vertical gap between nodes in a layer
LANE = 14       # height a waypoint takes in its layer
MARGIN = 24


@dataclass
class Layout:
    width: float = 0
    height: float = 0
    pos: dict = field(default_factory=dict)      # node id -> (x, y) of its top-left corner
    layer: dict = field(default_factory=dict)    # node id -> layer index
    paths: dict = field(default_factory=dict)    # (source, target) -> [(x, y), ...] from source's right to target's left
    reversed: set = field(default_factory=set)   # edges drawn against the layer order because they close a loop


def _acyclic(nodes, edges, soft=()):
    """Drop the edges that close a loop (found by depth-first search) so layers can be assigned.

    Soft edges are considered last, and only kept when they close no loop, so a loop is always
    broken at a soft edge when it has one.
    """
    soft = set(soft)
    hard = [e for e in edges if e not in soft]
    out = defaultdict(list)
    for a, b in hard:
        out[a].append(b)
    state, back = {}, set()
    for root in nodes:
        if root in state:
            continue
        stack = [(root, iter(out[root]))]
        state[root] = 1
        while stack:
            u, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                state[u] = 2
                stack.pop()
            elif state.get(nxt) == 1:
                back.add((u, nxt))
            elif nxt not in state:
                state[nxt] = 1
                stack.append((nxt, iter(out[nxt])))
    for a, b in [e for e in edges if e in soft]:
        seen, stack = set(), [b]
        while stack:   # does b already reach a?
            u = stack.pop()
            if u == a or u in seen:
                continue
            seen.add(u)
            stack += [v for v in out[u] if (u, v) not in back]
        if a in seen or a == b:
            back.add((a, b))
        else:
            out[a].append(b)
    return [e for e in edges if e not in back], back


def layout(sizes, edges, layer_of=None, soft=()):
    nodes = list(sizes)
    edges = list(dict.fromkeys((a, b) for a, b in edges if a != b and a in sizes and b in sizes))
    forward, back = _acyclic(nodes, edges, soft)
    fixed = dict(layer_of or {})

    # Layers: longest path from the sources, with fixed layers taken as given
    preds = defaultdict(list)
    for a, b in forward:
        preds[b].append(a)
    layer = {}
    def assign(u, seen=()):
        if u in layer:
            return layer[u]
        if u in fixed:
            layer[u] = fixed[u]
        else:
            layer[u] = max((assign(p, seen + (u,)) + 1 for p in preds[u] if p not in seen), default=0)
        return layer[u]
    for u in nodes:
        assign(u)

    # Edges whose target is not to the right (loops, or fixed layers) are drawn as reversed
    draw = []
    rev = set()
    for a, b in edges:
        if layer[b] > layer[a]:
            draw.append((a, b))
        else:
            rev.add((a, b))

    # Waypoints for edges that span more than one layer
    chain = {}
    sizes = dict(sizes)
    for a, b in draw:
        pts = []
        for L in range(layer[a] + 1, layer[b]):
            d = ("~", a, b, L)
            sizes[d] = (0, LANE)
            layer[d] = L
            pts.append(d)
        chain[(a, b)] = [a] + pts + [b]
    nbr_up, nbr_down = defaultdict(list), defaultdict(list)
    for c in chain.values():
        for x, y in zip(c, c[1:]):
            nbr_down[x].append(y)
            nbr_up[y].append(x)

    # Order within layers: start from first-seen order, then barycentre sweeps
    n_layers = max(layer.values(), default=0) + 1
    rows = [[] for _ in range(n_layers)]
    seen = set()
    def visit(u):
        if u in seen:
            return
        seen.add(u)
        rows[layer[u]].append(u)
        for v in nbr_down[u]:
            visit(v)
    for u in sorted(sizes, key=lambda u: (layer[u], isinstance(u, tuple))):
        visit(u)

    def idx():
        return {u: i for r in rows for i, u in enumerate(r)}

    def crossings():
        at, total = idx(), 0
        for L in range(n_layers - 1):
            es = [(at[u], at[v]) for u in rows[L] for v in nbr_down[u]]
            total += sum(1 for i, (a1, b1) in enumerate(es) for a2, b2 in es[i + 1:] if (a1 - a2) * (b1 - b2) < 0)
        return total

    best, best_x = [list(r) for r in rows], crossings()
    for sweep in range(12):
        at = idx()
        order = range(1, n_layers) if sweep % 2 == 0 else range(n_layers - 2, -1, -1)
        for L in order:
            nb = nbr_up if sweep % 2 == 0 else nbr_down
            def key(u):
                ns = [at[v] for v in nb[u]]
                return (sum(ns) / len(ns)) if ns else at[u]
            rows[L].sort(key=key)
            at = idx()
        x = crossings()
        if x < best_x:
            best, best_x = [list(r) for r in rows], x
    rows = best

    # Heights: stack each layer, then pull nodes towards their neighbours' centres
    y = {}
    for r in rows:
        top = 0
        for u in r:
            y[u] = top
            top += sizes[u][1] + GAP_Y
    def centre(u):
        return y[u] + sizes[u][1] / 2
    for it in range(30):
        down = it % 2 == 0
        for r in (rows if down else rows[::-1]):
            want = {}
            for u in r:
                ns = nbr_up[u] + nbr_down[u]
                want[u] = (sum(centre(v) for v in ns) / len(ns) - sizes[u][1] / 2) if ns else y[u]
            # keep the order, push apart where they would overlap, then centre the block on the wishes
            placed = []
            for u in r:
                lo = placed[-1][1] if placed else float("-inf")
                top = max(want[u], lo)
                placed.append((u, top + sizes[u][1] + GAP_Y))
                y[u] = top
            shift = sum(want[u] - y[u] for u in r) / len(r) if r else 0
            if shift < 0:
                # move the block up as far as the wishes allow without breaking the spacing
                for u in r:
                    y[u] += shift
    # Close empty bands: where no real node sits at some height in any layer, pull everything
    # below up, so long edges do not leave a hole in the middle of the picture
    real = sorted((y[u], y[u] + sizes[u][1]) for u in y if not isinstance(u, tuple))
    cuts, reach = [], None
    for top, bottom in real:
        if reach is not None and top - reach > 3 * GAP_Y:
            cuts.append((reach, top - reach - 3 * GAP_Y))
        reach = bottom if reach is None else max(reach, bottom)
    if cuts:
        def moved(v):
            return v - sum(min(size, max(0.0, v - start)) for start, size in cuts)
        for u in y:
            y[u] = moved(y[u])
    low = min(y.values(), default=0)
    for u in y:
        y[u] += MARGIN - low

    # x: each layer as wide as its widest node
    widths = [max((sizes[u][0] for u in r), default=0) for r in rows]
    lx, acc = [], MARGIN
    for w in widths:
        lx.append(acc)
        acc += w + GAP_X
    res = Layout()
    res.layer = {u: layer[u] for u in nodes}
    for u in nodes:
        L = layer[u]
        res.pos[u] = (lx[L] + (widths[L] - sizes[u][0]) / 2, y[u])

    # Ports: spread several edges leaving or entering one node over its height
    outs, ins = defaultdict(list), defaultdict(list)
    for (a, b), c in chain.items():
        outs[a].append(((a, b), centre(c[1])))
        ins[b].append(((a, b), centre(c[-2])))
    def ports(group, node):
        h = sizes[node][1]
        items = sorted(group, key=lambda t: t[1])
        n = len(items)
        span = min(h - 16, 12 * (n - 1))
        return {e: y[node] + h / 2 - span / 2 + (span * i / (n - 1) if n > 1 else 0) for i, (e, _) in enumerate(items)}
    out_y = {e: v for u, g in outs.items() for e, v in ports(g, u).items()}
    in_y = {e: v for u, g in ins.items() for e, v in ports(g, u).items()}

    for (a, b), c in chain.items():
        ax, ay = res.pos[a]
        bx, by = res.pos[b]
        pts = [(ax + sizes[a][0], out_y[(a, b)])]
        for d in c[1:-1]:
            L = layer[d]
            pts += [(lx[L], centre(d)), (lx[L] + widths[L], centre(d))]
        pts.append((bx, in_y[(a, b)]))
        res.paths[(a, b)] = pts
    for a, b in rev:
        ax, ay = res.pos[a]
        bx, by = res.pos[b]
        res.paths[(a, b)] = [(ax + sizes[a][0] / 2, ay + sizes[a][1]), (bx + sizes[b][0] / 2, by + sizes[b][1])]
    res.reversed = rev
    res.width = acc - GAP_X + MARGIN
    res.height = max((y[u] + sizes[u][1] for u in y), default=0) + MARGIN
    return res
