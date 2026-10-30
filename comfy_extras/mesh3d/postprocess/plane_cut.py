"""
Horizontal plane cut with planar cap triangulation (pure NumPy, CPU).

Keeps the y >= height half of a closed, outward-facing manifold triangle mesh and
caps the open section with downward-facing triangles. Concave section outlines and
inner holes are preserved, disjoint sections are triangulated independently.
"""
import numpy as np


def _signed_area_xz(points):
    x = points[:, 0]
    z = points[:, 1]
    return 0.5 * (np.dot(x, np.roll(z, -1)) - np.dot(np.roll(x, -1), z))


def _ray_hits_xz(ids, xz, mx, mz):
    """Edges of the id loop that cross the +x ray from (mx, mz); half-open vertex
    convention so the two edges meeting on the ray count once. Returns (px, index)."""
    hits = []
    k = len(ids)
    for j in range(k):
        x1, z1 = xz[ids[j]]
        x2, z2 = xz[ids[(j + 1) % k]]
        d1, d2 = z1 - mz, z2 - mz
        if (d1 > 0.0 and d2 <= 0.0) or (d2 > 0.0 and d1 <= 0.0):
            px = x1 + (x2 - x1) * d1 / (d1 - d2)
            if px >= mx:
                hits.append((px, j))
    return hits


def _ear_clip(order, xz, tol):
    """Triangulate a CCW weakly-simple polygon (outer loop with holes bridged in).
    Vertex ids may repeat (bridge endpoints); coincident points sit on edges and do
    not block an ear. Returns CCW (x,z) triangles, whose 3D normal on y=h is -Y."""
    n = len(order)
    if n < 3:
        return []
    coords = np.array([xz[i] for i in order], dtype=np.float64)
    prev = np.arange(n) - 1
    nxt = np.arange(n) + 1
    prev[0] = n - 1
    nxt[-1] = 0
    alive = np.ones(n, dtype=bool)
    count = n
    head = 0
    tris = []
    while count >= 3:
        ear = -1
        fallback = -1
        fallback_inside = None
        i = head
        while True:
            a, b, c = prev[i], i, nxt[i]
            pa, pb, pc = coords[a], coords[b], coords[c]
            cross = ((pb[0] - pa[0]) * (pc[1] - pa[1])
                     - (pb[1] - pa[1]) * (pc[0] - pa[0]))
            if cross >= -tol:
                pts = coords[alive]
                s1 = (pb[0] - pa[0]) * (pts[:, 1] - pa[1]) - (pb[1] - pa[1]) * (pts[:, 0] - pa[0])
                s2 = (pc[0] - pb[0]) * (pts[:, 1] - pb[1]) - (pc[1] - pb[1]) * (pts[:, 0] - pb[0])
                s0 = (pa[0] - pc[0]) * (pts[:, 1] - pc[1]) - (pa[1] - pc[1]) * (pts[:, 0] - pc[0])
                inside = int(np.count_nonzero((s1 > tol) & (s2 > tol) & (s0 > tol)))
                distinct = order[a] != order[b] and order[b] != order[c] and order[a] != order[c]
                if inside == 0 and distinct:
                    ear = i
                    break
                if fallback < 0 or inside < fallback_inside:
                    fallback, fallback_inside = i, inside
            i = nxt[i]
            if i == head:
                break
        if ear < 0:
            if fallback < 0:
                break  # malformed (all-reflex) contour; return what triangulated
            ear = fallback
        a, b, c = prev[ear], ear, nxt[ear]
        if order[a] != order[b] and order[b] != order[c] and order[a] != order[c]:
            tris.append((order[a], order[b], order[c]))
        nxt[a] = c
        prev[c] = a
        alive[ear] = False
        head = c
        count -= 1
    return tris


def _triangulate_section(outer, holes, xz, add_bridge_vertex, tol):
    """One planar region: outer loop CCW in xz, each hole CW. Bridges every hole to
    the boundary (chaining through a sibling hole that blocks the bridge) then clips."""
    if _signed_area_xz(np.array([xz[i] for i in outer])) < 0.0:
        outer = outer[::-1]
    boundary = list(outer)
    remaining = []
    for hole in holes:
        if _signed_area_xz(np.array([xz[i] for i in hole])) > 0.0:
            hole = hole[::-1]
        remaining.append(list(hole))

    def splice(hole):
        nonlocal boundary
        # Start the hole walk at its rightmost vertex (max x, then max z).
        mi = max(range(len(hole)), key=lambda k: (xz[hole[k]][0], xz[hole[k]][1]))
        walk = hole[mi:] + hole[:mi]
        cycle = walk + [walk[0]]
        mx, mz = xz[walk[0]]
        while True:
            def ray_query(rz):
                bh = _ray_hits_xz(boundary, xz, mx, rz)
                nearest = None
                for other in remaining:
                    if other is hole:
                        continue
                    for px, _ in _ray_hits_xz(other, xz, mx, rz):
                        if nearest is None or px < nearest[0]:
                            nearest = (px, other)
                return bh, nearest

            # A ray exactly aligned with an edge sees it neither as a blocker nor
            # as a boundary, so also probe a hair above and below.
            coord_vals = [xz[i] for ids in [boundary] + remaining for i in ids]
            xs = [p[0] for p in coord_vals]
            zs = [p[1] for p in coord_vals]
            extent = max(max(xs) - min(xs), max(zs) - min(zs), 1.0)
            nudge = 1e-6 * extent
            probes = [ray_query(mz), ray_query(mz - nudge), ray_query(mz + nudge)]
            blocker = None
            for _, nearest in probes:
                if nearest is not None and (blocker is None or nearest[0] < blocker[0]):
                    blocker = nearest
            if blocker is not None:
                # A sibling hole lies between M and the boundary; absorb it first.
                splice(blocker[1])
                continue
            # Anchor strictly inside a boundary edge, never at a vertex: a vertex
            # anchor makes the doubled corridor collinear with the loop edge there
            # and the zero-width junction cannot be triangulated. Offset the ray
            # until the crossing is interior; the bridge vertex splits the matching
            # surface chord triangle (handled by the caller).
            anchor = None
            for scale in (1.0, 2.0, 4.0, 8.0, 16.0, 32.0):
                for rz0 in (mz, mz - nudge * scale, mz + nudge * scale):
                    bh = _ray_hits_xz(boundary, xz, mx, rz0)
                    if not bh:
                        continue
                    px0, j0 = min(bh, key=lambda hit: hit[0])
                    aa, bb = boundary[j0], boundary[(j0 + 1) % len(boundary)]
                    ax0, az0 = xz[aa]
                    bx0, bz0 = xz[bb]
                    if not (min(az0, bz0) < rz0 < max(az0, bz0)):
                        continue
                    tt = (rz0 - az0) / (bz0 - az0)
                    if 1e-9 < tt < 1.0 - 1e-9:
                        anchor = (j0, ax0 + tt * (bx0 - ax0), rz0, tt)
                        break
                if anchor is not None:
                    break
            if anchor is None:
                remaining.remove(hole)
                return
            j, px, pz, t = anchor
            a_id, b_id = boundary[j], boundary[(j + 1) % len(boundary)]
            p_id = add_bridge_vertex(a_id, b_id, px, pz, t)
            xz[p_id] = (px, pz)
            k = len(boundary)
            boundary = boundary[(j + 1) % k:] + boundary[:(j + 1) % k]
            boundary.extend([p_id] + cycle + [p_id])
            remaining.remove(hole)
            return

    for hole in list(remaining):
        if hole in remaining:
            splice(hole)

    return _ear_clip(boundary, xz, tol)


def plane_cut_mesh(vertices, faces, height, colors=None):
    """Cut a single closed outward-facing manifold mesh at y=height, keep y>=height
    and cap the section with outward (-Y) triangles.

    vertices (N,3) float, faces (M,3) int, colors (N,C) float or None. Returns
    (out_vertices f32, out_faces i32, out_colors f32 or None). The caller handles
    planes below/above the mesh; this assumes height is inside the vertex range."""
    v = np.asarray(vertices, dtype=np.float64)
    f = np.asarray(faces)
    has_colors = colors is not None
    col = np.asarray(colors, dtype=np.float64) if has_colors else None
    h = float(height)

    span = float((v.max(axis=0) - v.min(axis=0)).max()) or 1.0
    eps = 1e-9 * span

    y = v[:, 1].copy()
    on = np.abs(y - h) <= eps
    y[on] = h
    inside = y >= h

    old_to_new = np.full(v.shape[0], -1, dtype=np.int64)
    kept = np.flatnonzero(inside)
    old_to_new[kept] = np.arange(kept.shape[0])
    pos_parts = [v[kept].copy()]
    pos_parts[0][on[kept], 1] = h
    plane_parts = [on[kept]]
    col_parts = [col[kept].copy()] if has_colors else []
    interp_ids = {}

    def add_vertex(position, is_plane, color=None):
        gid = sum(p.shape[0] for p in pos_parts)
        pos_parts.append(np.asarray(position, dtype=np.float64).reshape(1, 3))
        plane_parts.append(np.array([is_plane], dtype=bool))
        if has_colors:
            col_parts.append(np.asarray(color, dtype=np.float64).reshape(1, -1))
        return gid

    def edge_plane_vertex(a, b):
        # Intersection of a strictly crossing edge (one endpoint below, one above).
        key = (a, b) if a < b else (b, a)
        gid = interp_ids.get(key)
        if gid is not None:
            return gid
        t = (h - y[a]) / (y[b] - y[a])
        p = v[a] * (1.0 - t) + v[b] * t
        p[1] = h
        c = (col[a] * (1.0 - t) + col[b] * t) if has_colors else None
        gid = add_vertex(p, True, c)
        interp_ids[key] = gid
        return gid

    def edge_point(a, b):
        if on[a]:
            return int(old_to_new[a])
        if on[b]:
            return int(old_to_new[b])
        return edge_plane_vertex(a, b)

    surf_faces = []
    plane_pairs = []
    for tri in f:
        a, b, c = int(tri[0]), int(tri[1]), int(tri[2])
        poly = []
        for s, e in ((a, b), (b, c), (c, a)):
            s_in, e_in = y[s] >= h, y[e] >= h
            if s_in:
                poly.append(int(old_to_new[s]))
            if s_in != e_in:
                poly.append(edge_point(s, e))
        k = len(poly)
        if k:
            deduped = [poly[0]]
            for x in poly[1:]:
                if x != deduped[-1]:
                    deduped.append(x)
            if len(deduped) > 1 and deduped[0] == deduped[-1]:
                deduped.pop()
            poly = deduped
            k = len(poly)
        if k >= 3 and len(set(poly)) >= 3:
            for q in range(1, k - 1):
                t0, t1, t2 = poly[0], poly[q], poly[q + 1]
                if t0 != t1 and t1 != t2 and t0 != t2:
                    surf_faces.append((t0, t1, t2))
            for q in range(k):
                p0, p1 = poly[q], poly[(q + 1) % k]
                if p0 != p1:
                    plane_pairs.append((p0, p1) if p0 < p1 else (p1, p0))

    # Section boundary = plane edges used by exactly one clipped surface face.
    boundary_edges = []
    if plane_pairs:
        pair_count = {}
        for pair in plane_pairs:
            pair_count[pair] = pair_count.get(pair, 0) + 1
        boundary_edges = [pair for pair, count in pair_count.items() if count == 1]

    cap_faces = []
    bridge_splits = []
    if boundary_edges:
        pos = np.concatenate(pos_parts, axis=0)
        cols = np.concatenate(col_parts, axis=0) if has_colors else None
        extra_pos = {}
        extra_col = {}

        def pos_of(gid):
            return pos[gid] if gid < pos.shape[0] else extra_pos[gid]

        def add_bridge(a_id, b_id, px, pz, t):
            p = pos_of(a_id) * (1.0 - t) + pos_of(b_id) * t
            p[0], p[1], p[2] = px, h, pz
            color = None
            if has_colors:
                color = (cols[a_id] if a_id < cols.shape[0] else extra_col[a_id]) * (1.0 - t) \
                    + (cols[b_id] if b_id < cols.shape[0] else extra_col[b_id]) * t
            gid = pos.shape[0] + len(extra_pos)
            extra_pos[gid] = p
            pos_parts.append(p.reshape(1, 3))
            plane_parts.append(np.array([True]))
            if has_colors:
                extra_col[gid] = color
                col_parts.append(color.reshape(1, -1))
            bridge_splits.append((gid, a_id, b_id))
            return gid

        adjacency = {}
        unused = set()
        for u, vv in boundary_edges:
            adjacency.setdefault(u, []).append(vv)
            adjacency.setdefault(vv, []).append(u)
            unused.add((u, vv))

        # Trace section loops; at saddle vertices (degree > 2) take the straightest
        # continuation so figure-eight crossings stay separated.
        loops = []
        while unused:
            u0, v0 = unused.pop()
            loop = [u0]
            prev_v, cur = u0, v0
            while True:
                loop.append(cur)
                candidates = [w for w in adjacency[cur]
                              if w != prev_v and ((cur, w) if cur < w else (w, cur)) in unused]
                if not candidates:
                    break
                if len(candidates) == 1:
                    nxt_v = candidates[0]
                else:
                    din = pos[cur] - pos[prev_v]
                    nxt_v = max(candidates,
                                key=lambda w: float(np.dot(din, pos[w] - pos[cur])))
                unused.discard((cur, nxt_v) if cur < nxt_v else (nxt_v, cur))
                prev_v, cur = cur, nxt_v
                if cur == u0:
                    break
            if len(loop) >= 3:
                loops.append(loop)

        if loops:
            xz = {i: (float(pos[i, 0]), float(pos[i, 2]))
                  for loop in loops for i in loop}
            tol = 1e-11 * span * span

            loop_pts = [np.array([xz[i] for i in loop]) for loop in loops]
            areas = [_signed_area_xz(pts) for pts in loop_pts]
            reps = np.array([pts[0] for pts in loop_pts])
            L = len(loops)
            contains = np.zeros((L, L), dtype=bool)
            for j, pts in enumerate(loop_pts):
                z1 = pts[:, 1]
                z2 = np.roll(z1, -1)
                x1 = pts[:, 0]
                x2 = np.roll(x1, -1)
                d1 = z1[None, :] - reps[:, 1, None]
                d2 = z2[None, :] - reps[:, 1, None]
                cross = ((d1 > 0.0) & (d2 <= 0.0)) | ((d2 > 0.0) & (d1 <= 0.0))
                denom = np.where(d1 == d2, 1.0, d1 - d2)
                px = x1[None, :] + (x2[None, :] - x1[None, :]) * d1 / denom
                contains[:, j] = (cross & (reps[:, 0, None] < px)).sum(axis=1) % 2 == 1
            np.fill_diagonal(contains, False)
            depth = contains.sum(axis=1)
            parent = np.full(L, -1, dtype=np.int64)
            for i in range(L):
                containers = np.flatnonzero(contains[i])
                if containers.size:
                    parent[i] = min(containers, key=lambda j: (-int(depth[j]), abs(areas[j])))
            for i in range(L):
                if depth[i] % 2 == 1:
                    continue
                holes = [loops[j] for j in range(L) if parent[j] == i]
                cap_faces.extend(_triangulate_section(
                    loops[i], holes, xz, add_bridge, tol))

    # Every bridge vertex splits a section edge; split the matching clipped
    # surface face along that edge so the new cap boundary edges pair up.
    if bridge_splits:
        boundary_set = set(boundary_edges)
        edge_face = {}
        for face in surf_faces:
            for q in range(3):
                e0, e1 = face[q], face[(q + 1) % 3]
                key = (e0, e1) if e0 < e1 else (e1, e0)
                if key in boundary_set:
                    edge_face[key] = face
        alive_faces = set(surf_faces)
        for p, a, b in bridge_splits:
            key = (a, b) if a < b else (b, a)
            face = edge_face.pop(key)
            ia, ib = face.index(a), face.index(b)
            assert (ib - ia) % 3 == 1
            w = face[3 - ia - ib]
            f1, f2 = (a, p, w), (p, b, w)
            alive_faces.discard(face)
            alive_faces.add(f1)
            alive_faces.add(f2)
            edge_face[(a, p) if a < p else (p, a)] = f1
            edge_face[(p, b) if p < b else (b, p)] = f2
        surf_faces = list(alive_faces)

    out_v = np.concatenate(pos_parts, axis=0).astype(np.float32)
    out_f = np.array(surf_faces + cap_faces, dtype=np.int32).reshape(-1, 3)
    out_c = np.concatenate(col_parts, axis=0).astype(np.float32) if has_colors else None

    # Sliver cap triangles can lose their sign when positions round to float32.
    # The cap is known to face -Y; flip winding in float32 so every cap face does.
    # Vertex sets (and therefore edge sets) stay unchanged, so the mesh stays closed.
    if cap_faces:
        cap = out_f[len(surf_faces):]
        p = out_v[cap]
        cy = ((p[:, 1, 2] - p[:, 0, 2]) * (p[:, 2, 0] - p[:, 0, 0])
              - (p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 2] - p[:, 0, 2]))
        flip = cy >= 0.0
        if np.any(flip):
            idx = np.flatnonzero(flip)
            out_f[len(surf_faces) + idx, 1:3] = out_f[len(surf_faces) + idx, 2:0:-1]
    return out_v, out_f, out_c
