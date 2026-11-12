"""Three dimensional physical rail geometry; no game or filesystem access."""
from collections import defaultdict
import math

AXES = ('x', 'y', 'z')


def vector(p):
    v = tuple(float(p.get(k, 0)) for k in AXES)
    if not all(math.isfinite(x) for x in v):
        raise ValueError('nonfinite rail coordinate')
    return v


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


class RailGraph:
    def __init__(self, network):
        self.nodes = {n['entity_id']: vector(n['position']) for n in network['nodes']}
        self.edges = {e['entity_id']: e for e in network['edges']}
        if len(self.edges) != len(network['edges']):
            raise ValueError('duplicate rail edge')
        self.incident, self.grid, self.fine_grid = defaultdict(list), defaultdict(set), defaultdict(set)
        self.curves, self.lengths, self.samples, self.sample_points = {}, {}, {}, {}
        for eid, e in self.edges.items():
            a, b = self.nodes[e['node0']], self.nodes[e['node1']]
            delta = tuple(y-x for x, y in zip(a, b))
            u, v = vector(e['tangent0']) if e.get('tangent0') else delta, vector(e['tangent1']) if e.get('tangent1') else delta
            self.curves[eid] = (a, b, u, v)
            for key in ('node0', 'node1'):
                self.incident[e[key]].append(eid)
            # A cubic Bezier lies within its control polygon: no sampled-bounds holes.
            controls = [a, b, tuple(x+y/3 for x, y in zip(a, u)), tuple(x-y/3 for x, y in zip(b, v))]
            for ix in range(math.floor(min(p[0] for p in controls)/100), math.floor(max(p[0] for p in controls)/100)+1):
                for iy in range(math.floor(min(p[1] for p in controls)/100), math.floor(max(p[1] for p in controls)/100)+1):
                    self.grid[ix, iy].add(eid)
            # Sixteen Bezier control boxes still contain the exact curve, but
            # avoid returning every long/curved edge in a 100 m map cell when
            # live vehicle bodies are projected several times per second.
            pieces = [tuple(controls)]
            for _ in range(4):
                split = []
                for p0, p1, p2, p3 in pieces:
                    p01 = tuple((x+y)/2 for x, y in zip(p0, p1))
                    p12 = tuple((x+y)/2 for x, y in zip(p1, p2))
                    p23 = tuple((x+y)/2 for x, y in zip(p2, p3))
                    p012 = tuple((x+y)/2 for x, y in zip(p01, p12))
                    p123 = tuple((x+y)/2 for x, y in zip(p12, p23))
                    middle = tuple((x+y)/2 for x, y in zip(p012, p123))
                    split.extend(((p0, p01, p012, middle), (middle, p123, p23, p3)))
                pieces = split
            for piece in pieces:
                for ix in range(math.floor(min(p[0] for p in piece)/25), math.floor(max(p[0] for p in piece)/25)+1):
                    for iy in range(math.floor(min(p[1] for p in piece)/25), math.floor(max(p[1] for p in piece)/25)+1):
                        self.fine_grid[ix, iy].add(eid)
            pts = [self.point(eid, i/32) for i in range(33)]
            self.sample_points[eid] = pts
            distances = [0.0]
            for p, q in zip(pts, pts[1:]):
                distances.append(distances[-1]+math.dist(p, q))
            self.samples[eid] = distances
            self.lengths[eid] = distances[-1]

    def point(self, eid, t, derivative=False):
        a, b, u, v = self.curves[eid]
        weights = (6*t*t-6*t, -6*t*t+6*t, 3*t*t-4*t+1, 3*t*t-2*t) if derivative else (
            2*t**3-3*t*t+1, -2*t**3+3*t*t, t**3-2*t*t+t, t**3-t*t)
        return tuple(sum(w*p[k] for w, p in zip(weights, (a, b, u, v))) for k in range(3))

    def along(self, eid, t):
        scaled = min(1, max(0, t))*32
        i = min(31, int(scaled))
        d = self.samples[eid]
        return d[i]+(d[i+1]-d[i])*(scaled-i)

    def project(self, eid, position):
        p = vector(position) if isinstance(position, dict) else position
        def cost(t):
            return sum((a-b)**2 for a, b in zip(self.point(eid, t), p))
        values = [cost(i/32) for i in range(33)]
        candidates = [(values[0], 0.), (values[-1], 1.)]
        for i in range(33):
            if values[i] > values[max(0, i-1)] or values[i] > values[min(32, i+1)]:
                continue
            lo, hi = max(0, (i-1)/32), min(1, (i+1)/32)
            for _ in range(35):
                t1, t2 = lo+(hi-lo)/3, hi-(hi-lo)/3
                if cost(t1) <= cost(t2): hi = t2
                else: lo = t1
            t = (lo+hi)/2
            candidates.append((cost(t), t))
        distance2, t = min(candidates)
        return t, self.point(eid, t), math.sqrt(distance2)

    def approximate_project(self, eid, position):
        """Cheap polyline projection used only to shortlist exact curves."""
        p = vector(position) if isinstance(position, dict) else position
        best = None
        points = self.sample_points[eid][::4]
        for i, (a, b) in enumerate(zip(points, points[1:])):
            delta = tuple(y-x for x, y in zip(a, b))
            length2 = dot(delta, delta)
            u = 0. if not length2 else min(1., max(0., dot(tuple(x-y for x, y in zip(p, a)), delta)/length2))
            q = tuple(x+u*d for x, d in zip(a, delta))
            distance2 = sum((x-y)**2 for x, y in zip(p, q))
            value = (distance2, (i+u)/(len(points)-1), q)
            if best is None or value[0] < best[0]: best = value
        return best[1], best[2], math.sqrt(best[0])

    def near(self, p, radius):
        found = set()
        for ix in range(math.floor((p[0]-radius)/100), math.floor((p[0]+radius)/100)+1):
            for iy in range(math.floor((p[1]-radius)/100), math.floor((p[1]+radius)/100)+1):
                found.update(self.grid.get((ix, iy), ()))
        return sorted(found)

    def near_precise(self, p, radius):
        """Return a tight, no-chord-shortcut set of curves around an XY point."""
        found = set()
        for ix in range(math.floor((p[0]-radius)/25), math.floor((p[0]+radius)/25)+1):
            for iy in range(math.floor((p[1]-radius)/25), math.floor((p[1]+radius)/25)+1):
                found.update(self.fine_grid.get((ix, iy), ()))
        return sorted(found)
