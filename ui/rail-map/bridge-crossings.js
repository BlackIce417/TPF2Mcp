(function publishRailBridgeCrossings(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.RailBridgeCrossings = api;
}(typeof globalThis !== 'undefined' ? globalThis : window, () => {
  let renderSequence = 0;
  const cross = (a, b) => a.x * b.y - a.y * b.x;
  const distance = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
  const canonicalDirection = value => {
    const length = Math.hypot(value.x, value.y);
    if (length <= 1e-9) return {x: 1, y: 0};
    let x = value.x / length;
    let y = value.y / length;
    if (x < 0 || (Math.abs(x) <= 1e-9 && y < 0)) {
      x = -x;
      y = -y;
    }
    return {x, y};
  };
  const nodePosition = value => value?.position || value;
  const cubicPoint = (edge, a, b, u) => {
    const fallback = {x: b.x - a.x, y: b.y - a.y, z: (b.z || 0) - (a.z || 0)};
    const t0 = edge.tangent0 || fallback;
    const t1 = edge.tangent1 || fallback;
    const h00 = 2 * u ** 3 - 3 * u ** 2 + 1;
    const h10 = u ** 3 - 2 * u ** 2 + u;
    const h01 = -2 * u ** 3 + 3 * u ** 2;
    const h11 = u ** 3 - u ** 2;
    return {
      x: h00 * a.x + h10 * (t0.x || 0) + h01 * b.x + h11 * (t1.x || 0),
      y: h00 * a.y + h10 * (t0.y || 0) + h01 * b.y + h11 * (t1.y || 0),
      z: h00 * (a.z || 0) + h10 * (t0.z || 0) + h01 * (b.z || 0) + h11 * (t1.z || 0),
    };
  };
  const segmentIntersection = (left, right, minimumAngleSin) => {
    const r = {x: left.b.x - left.a.x, y: left.b.y - left.a.y};
    const s = {x: right.b.x - right.a.x, y: right.b.y - right.a.y};
    const denominator = cross(r, s);
    const lengths = Math.hypot(r.x, r.y) * Math.hypot(s.x, s.y);
    if (lengths <= 1e-9 || Math.abs(denominator) / lengths <= Math.max(minimumAngleSin, 1e-9)) return null;
    const delta = {x: right.a.x - left.a.x, y: right.a.y - left.a.y};
    const leftRatio = cross(delta, s) / denominator;
    const rightRatio = cross(delta, r) / denominator;
    const epsilon = 1e-7;
    if (leftRatio < -epsilon || leftRatio > 1 + epsilon || rightRatio < -epsilon || rightRatio > 1 + epsilon) return null;
    const aRatio = Math.max(0, Math.min(1, leftRatio));
    const bRatio = Math.max(0, Math.min(1, rightRatio));
    return {
      x: left.a.x + r.x * aRatio,
      y: left.a.y + r.y * aRatio,
      leftZ: left.a.z + (left.b.z - left.a.z) * aRatio,
      rightZ: right.a.z + (right.b.z - right.a.z) * bRatio,
      leftDirection: canonicalDirection(r),
      rightDirection: canonicalDirection(s),
    };
  };
  const detect = (edges, nodeById, options = {}) => {
    const settings = {
      cellSizeM: options.cellSizeM || 20,
      samples: options.samples || 8,
      maximumSamples: options.maximumSamples || 24,
      minClearanceM: options.minClearanceM ?? .75,
      // Only reject an intersection effectively coincident with a disconnected
      // edge endpoint. TPF2 commonly splits parallel tracks at slightly
      // different positions; a 1.5 m guard dropped legitimate crossings on
      // one rail of a double-track bridge while retaining the other.
      minEndpointDistanceM: options.minEndpointDistanceM ?? .25,
      minimumAngleSin: Math.sin((options.minimumAngleDegrees ?? 0) * Math.PI / 180),
    };
    const getNode = id => nodePosition(nodeById instanceof Map ? nodeById.get(id) : nodeById[id]);
    const segments = [];
    (edges || []).forEach(edge => {
      const a = getNode(edge.node0);
      const b = getNode(edge.node1);
      if (!a || !b) return;
      const chordLength = distance(a, b);
      const sampleCount = Math.min(settings.maximumSamples, Math.max(settings.samples, Math.ceil(chordLength / 25)));
      let previous = cubicPoint(edge, a, b, 0);
      for (let index = 1; index <= sampleCount; index += 1) {
        const current = cubicPoint(edge, a, b, index / sampleCount);
        if (distance(previous, current) > 1e-6) segments.push({edge, a: previous, b: current, endpoint0: a, endpoint1: b});
        previous = current;
      }
    });

    const buckets = new Map();
    const crossingsByPair = new Map();
    segments.forEach((segment, segmentIndex) => {
      const minCellX = Math.floor(Math.min(segment.a.x, segment.b.x) / settings.cellSizeM);
      const maxCellX = Math.floor(Math.max(segment.a.x, segment.b.x) / settings.cellSizeM);
      const minCellY = Math.floor(Math.min(segment.a.y, segment.b.y) / settings.cellSizeM);
      const maxCellY = Math.floor(Math.max(segment.a.y, segment.b.y) / settings.cellSizeM);
      const compared = new Set();
      for (let cellX = minCellX; cellX <= maxCellX; cellX += 1) {
        for (let cellY = minCellY; cellY <= maxCellY; cellY += 1) {
          const key = `${cellX}:${cellY}`;
          const bucket = buckets.get(key) || [];
          bucket.forEach(otherIndex => {
            if (compared.has(otherIndex)) return;
            compared.add(otherIndex);
            const other = segments[otherIndex];
            const leftId = Number(segment.edge.entity_id);
            const rightId = Number(other.edge.entity_id);
            if (leftId === rightId) return;
            if (segment.edge.node0 === other.edge.node0 || segment.edge.node0 === other.edge.node1 ||
                segment.edge.node1 === other.edge.node0 || segment.edge.node1 === other.edge.node1) return;
            const pairKey = leftId < rightId ? `${leftId}:${rightId}` : `${rightId}:${leftId}`;
            if (crossingsByPair.has(pairKey)) return;
            const hit = segmentIntersection(segment, other, settings.minimumAngleSin);
            if (!hit) return;
            const endpoints = [segment.endpoint0, segment.endpoint1, other.endpoint0, other.endpoint1];
            if (Math.min(...endpoints.map(endpoint => distance(hit, endpoint))) < settings.minEndpointDistanceM) return;
            const clearance = Math.abs(hit.leftZ - hit.rightZ);
            if (clearance < settings.minClearanceM) return;
            const leftIsUpper = hit.leftZ > hit.rightZ;
            crossingsByPair.set(pairKey, {
              position: {x: hit.x, y: hit.y},
              upper_z: leftIsUpper ? hit.leftZ : hit.rightZ,
              lower_z: leftIsUpper ? hit.rightZ : hit.leftZ,
              clearance_m: clearance,
              upper_edge_id: leftIsUpper ? leftId : rightId,
              lower_edge_id: leftIsUpper ? rightId : leftId,
              upper_node_ids: leftIsUpper
                ? [Number(segment.edge.node0), Number(segment.edge.node1)]
                : [Number(other.edge.node0), Number(other.edge.node1)],
              lower_node_ids: leftIsUpper
                ? [Number(other.edge.node0), Number(other.edge.node1)]
                : [Number(segment.edge.node0), Number(segment.edge.node1)],
              upper_direction: leftIsUpper ? hit.leftDirection : hit.rightDirection,
              lower_direction: leftIsUpper ? hit.rightDirection : hit.leftDirection,
              source: 'ENGINE_XYZ_TOPOLOGY_DERIVED',
            });
          });
          bucket.push(segmentIndex);
          buckets.set(key, bucket);
        }
      }
    });
    return [...crossingsByPair.values()].sort((a, b) => a.position.x - b.position.x || a.position.y - b.position.y);
  };
  const sampleEdge = (edge, nodeById, options = {}) => {
    const getNode = id => nodePosition(nodeById instanceof Map ? nodeById.get(Number(id)) : nodeById[id]);
    const a = getNode(edge?.node0);
    const b = getNode(edge?.node1);
    if (!a || !b) return [];
    const sampleCount = Math.min(
      options.maximumSamples || 32,
      Math.max(options.samples || 8, Math.ceil(distance(a, b) / (options.sampleSpacingM || 12))),
    );
    return Array.from({length: sampleCount + 1}, (_, index) => {
      const point = cubicPoint(edge, a, b, index / sampleCount);
      return {x: point.x, y: point.y};
    });
  };
  const polylineLength = points => (points || []).slice(1).reduce((sum, point, index) => sum + distance(points[index], point), 0);
  const joinPolylines = (values, toleranceM = 1) => {
    const source = (values || []).filter(points => points?.length >= 2).map(points => points.map(point => ({...point})));
    const alignment = (left, right) => {
      const denominator = Math.hypot(left.x, left.y) * Math.hypot(right.x, right.y);
      return denominator <= 1e-9 ? -1 : (left.x * right.x + left.y * right.y) / denominator;
    };
    const traced = source.map((seed, seedIndex) => {
      let chain = seed.map(point => ({...point}));
      const used = new Set([seedIndex]);
      while (true) {
        const candidates = [];
        source.forEach((candidate, index) => {
          if (used.has(index)) return;
          [candidate, [...candidate].reverse()].forEach(oriented => {
            const appendGap = distance(chain[chain.length - 1], oriented[0]);
            if (appendGap <= toleranceM) {
              const incoming = {x: chain[chain.length - 1].x - chain[chain.length - 2].x, y: chain[chain.length - 1].y - chain[chain.length - 2].y};
              const outgoing = {x: oriented[1].x - oriented[0].x, y: oriented[1].y - oriented[0].y};
              candidates.push({index, oriented, mode: 'append', gap: appendGap, alignment: alignment(incoming, outgoing)});
            }
            const prependGap = distance(chain[0], oriented[oriented.length - 1]);
            if (prependGap <= toleranceM) {
              const incoming = {x: oriented[oriented.length - 1].x - oriented[oriented.length - 2].x, y: oriented[oriented.length - 1].y - oriented[oriented.length - 2].y};
              const outgoing = {x: chain[1].x - chain[0].x, y: chain[1].y - chain[0].y};
              candidates.push({index, oriented, mode: 'prepend', gap: prependGap, alignment: alignment(incoming, outgoing)});
            }
          });
        });
        if (!candidates.length) break;
        const best = candidates.sort((left, right) => right.alignment - left.alignment || left.gap - right.gap)[0];
        chain = best.mode === 'append'
          ? [...chain, ...best.oriented.slice(1)]
          : [...best.oriented.slice(0, -1), ...chain];
        used.add(best.index);
      }
      return chain;
    });
    const unique = new Map();
    traced.forEach(chain => {
      const endpoints = [chain[0], chain[chain.length - 1]]
        .map(point => `${point.x.toFixed(2)},${point.y.toFixed(2)}`).sort().join('|');
      const key = `${endpoints}:${polylineLength(chain).toFixed(1)}`;
      if (!unique.has(key)) unique.set(key, chain);
    });
    return [...unique.values()];
  };
  const polylineProjection = (points, target) => {
    let best = {distance: Infinity, along: 0, across: 0, direction: {x: 1, y: 0}, point: points[0]};
    let traversed = 0;
    for (let index = 0; index + 1 < points.length; index += 1) {
      const left = points[index];
      const right = points[index + 1];
      const delta = {x: right.x - left.x, y: right.y - left.y};
      const length = Math.hypot(delta.x, delta.y);
      if (length <= 1e-9) continue;
      const direction = {x: delta.x / length, y: delta.y / length};
      const ratio = Math.max(0, Math.min(1, ((target.x - left.x) * delta.x + (target.y - left.y) * delta.y) / length ** 2));
      const point = {x: left.x + delta.x * ratio, y: left.y + delta.y * ratio};
      const difference = {x: target.x - point.x, y: target.y - point.y};
      const candidateDistance = Math.hypot(difference.x, difference.y);
      if (candidateDistance < best.distance) {
        best = {
          distance: candidateDistance,
          along: traversed + length * ratio,
          across: -direction.y * difference.x + direction.x * difference.y,
          direction,
          point,
        };
      }
      traversed += length;
    }
    return best;
  };
  const pointAtPolylineDistance = (points, target) => {
    const total = polylineLength(points);
    if (target <= 0) {
      const direction = canonicalDirection({x: points[1].x - points[0].x, y: points[1].y - points[0].y});
      const sign = direction.x * (points[1].x - points[0].x) + direction.y * (points[1].y - points[0].y) < 0 ? -1 : 1;
      return {x: points[0].x + direction.x * sign * target, y: points[0].y + direction.y * sign * target};
    }
    if (target >= total) {
      const last = points.length - 1;
      const raw = {x: points[last].x - points[last - 1].x, y: points[last].y - points[last - 1].y};
      const length = Math.hypot(raw.x, raw.y) || 1;
      return {x: points[last].x + raw.x / length * (target - total), y: points[last].y + raw.y / length * (target - total)};
    }
    let traversed = 0;
    for (let index = 0; index + 1 < points.length; index += 1) {
      const segmentLength = distance(points[index], points[index + 1]);
      if (traversed + segmentLength >= target) {
        const ratio = (target - traversed) / segmentLength;
        return {
          x: points[index].x + (points[index + 1].x - points[index].x) * ratio,
          y: points[index].y + (points[index + 1].y - points[index].y) * ratio,
        };
      }
      traversed += segmentLength;
    }
    return {...points[points.length - 1]};
  };
  const slicePolyline = (points, start, end) => {
    const result = [pointAtPolylineDistance(points, start)];
    let traversed = 0;
    for (let index = 0; index + 1 < points.length; index += 1) {
      traversed += distance(points[index], points[index + 1]);
      if (traversed > start + 1e-7 && traversed < end - 1e-7) result.push({...points[index + 1]});
    }
    result.push(pointAtPolylineDistance(points, end));
    return result.filter((point, index) => !index || distance(point, result[index - 1]) > 1e-7);
  };
  const offsetPolyline = (points, offset) => points.map((point, index) => {
    const before = points[Math.max(0, index - 1)];
    const after = points[Math.min(points.length - 1, index + 1)];
    const raw = {x: after.x - before.x, y: after.y - before.y};
    const length = Math.hypot(raw.x, raw.y) || 1;
    return {x: point.x - raw.y / length * offset, y: point.y + raw.x / length * offset};
  });
  const corridorQuads = (points, acrossMin, acrossMax, overlapM = .35) => (points || []).slice(1).map((right, index) => {
    const left = points[index];
    const raw = {x: right.x - left.x, y: right.y - left.y};
    const length = Math.hypot(raw.x, raw.y) || 1;
    const direction = {x: raw.x / length, y: raw.y / length};
    const normal = {x: -direction.y, y: direction.x};
    const start = {x: left.x - direction.x * overlapM, y: left.y - direction.y * overlapM};
    const end = {x: right.x + direction.x * overlapM, y: right.y + direction.y * overlapM};
    const shifted = (point, across) => ({x: point.x + normal.x * across, y: point.y + normal.y * across});
    return [shifted(start, acrossMin), shifted(start, acrossMax), shifted(end, acrossMax), shifted(end, acrossMin)];
  });
  const curvedDeckGeometry = (members, positionedMembers, straightFrame, upperPolylines, project, options = {}) => {
    const chains = joinPolylines(upperPolylines, options.upperJoinToleranceM ?? 1);
    if (!chains.length) return null;
    // Expansion may contain a continuation through a nearby switch.  Only a
    // chain which actually passes one of this structure's measured crossings
    // is allowed to define the deck.  Otherwise a nearby branch can pull the
    // white bridge outline away from the real upper track.
    const memberBindingToleranceM = options.upperMemberBindingToleranceM ?? 2.5;
    const deckChains = chains.filter(chain => members.some(
      member => polylineProjection(chain, member.position).distance <= memberBindingToleranceM,
    ));
    const referenceCandidates = deckChains.length ? deckChains : chains;
    const reference = referenceCandidates.map(points => ({
      points,
      score: members.reduce((sum, member) => sum + Math.min(polylineProjection(points, member.position).distance, 50), 0),
    })).sort((left, right) => left.score - right.score || polylineLength(right.points) - polylineLength(left.points))[0].points;
    if (reference.length < 2) return null;
    const referenceDirection = {
      x: reference[reference.length - 1].x - reference[0].x,
      y: reference[reference.length - 1].y - reference[0].y,
    };
    const expectedDirection = straightFrame.direction;
    if (referenceDirection.x * expectedDirection.x + referenceDirection.y * expectedDirection.y < 0) reference.reverse();
    const memberPositions = positionedMembers.map(value => ({
      ...value,
      curveAlong: polylineProjection(reference, value.item.position).along,
    }));
    const leftMember = memberPositions.reduce((best, value) => value.along < best.along ? value : best);
    const rightMember = memberPositions.reduce((best, value) => value.along > best.along ? value : best);
    const leftPaddingM = leftMember.along - straightFrame.deckStart;
    const rightPaddingM = straightFrame.deckEnd - rightMember.along;
    const curveStart = leftMember.curveAlong - leftPaddingM;
    const curveEnd = rightMember.curveAlong + rightPaddingM;
    if (!(curveEnd > curveStart)) return null;
    const spine = slicePolyline(reference, curveStart, curveEnd);
    if (spine.length < 2) return null;

    const upperClearanceM = options.upperShortEdgeClearanceM ?? 3;
    const offsets = [0];
    referenceCandidates.forEach(chain => chain.forEach(point => {
      const projection = polylineProjection(reference, point);
      if (projection.along >= curveStart - 3 && projection.along <= curveEnd + 3 && projection.distance <= 30) {
        offsets.push(projection.across);
      }
    }));
    members.forEach(member => offsets.push(polylineProjection(reference, member.position).across));
    const acrossMin = Math.min(...offsets) - upperClearanceM;
    const acrossMax = Math.max(...offsets) + upperClearanceM;
    const boundDeckChains = deckChains.length ? deckChains : [reference];
    const upperShortEdgeViolationCount = boundDeckChains.filter(chain => {
      const range = chain.map(point => polylineProjection(reference, point).along);
      return Math.min(...range) > curveStart + 1e-6 || Math.max(...range) < curveEnd - 1e-6;
    }).length;
    const sideMinWorld = offsetPolyline(spine, acrossMin);
    const sideMaxWorld = offsetPolyline(spine, acrossMax);
    const deckWorld = [...sideMinWorld, ...[...sideMaxWorld].reverse()];
    const maskPaddingM = options.bridgeMaskPaddingM ?? 1.25;
    const maskSpine = slicePolyline(reference, curveStart - maskPaddingM, curveEnd + maskPaddingM);
    const maskWorld = [
      ...offsetPolyline(maskSpine, acrossMin - maskPaddingM),
      ...offsetPolyline(maskSpine, acrossMax + maskPaddingM).reverse(),
    ];
    const maskDecksWorld = corridorQuads(
      maskSpine, acrossMin - maskPaddingM, acrossMax + maskPaddingM, maskPaddingM,
    );
    const wingComponentM = options.bridgeWingComponentM ?? 2;
    const virtualSpine = slicePolyline(reference, curveStart - wingComponentM, curveEnd + wingComponentM);
    const virtualWorld = [
      ...offsetPolyline(virtualSpine, acrossMin - wingComponentM),
      ...offsetPolyline(virtualSpine, acrossMax + wingComponentM).reverse(),
    ];
    const startRaw = {x: spine[1].x - spine[0].x, y: spine[1].y - spine[0].y};
    const endRaw = {
      x: spine[spine.length - 1].x - spine[spine.length - 2].x,
      y: spine[spine.length - 1].y - spine[spine.length - 2].y,
    };
    const unit = value => {
      const length = Math.hypot(value.x, value.y) || 1;
      return {x: value.x / length, y: value.y / length};
    };
    const startDirection = unit(startRaw);
    const endDirection = unit(endRaw);
    const wing = (point, direction, alongSign, acrossSign) => [point, {
      x: point.x + direction.x * wingComponentM * alongSign - direction.y * wingComponentM * acrossSign,
      y: point.y + direction.y * wingComponentM * alongSign + direction.x * wingComponentM * acrossSign,
    }];
    const bridgeWingsWorld = [
      wing(sideMinWorld[0], startDirection, -1, -1),
      wing(sideMaxWorld[0], startDirection, -1, 1),
      wing(sideMinWorld[sideMinWorld.length - 1], endDirection, 1, -1),
      wing(sideMaxWorld[sideMaxWorld.length - 1], endDirection, 1, 1),
    ];
    return {
      deck: deckWorld.map(project),
      maskDeck: maskWorld.map(project),
      maskDecks: maskDecksWorld.map(polygon => polygon.map(project)),
      virtualDeck: virtualWorld.map(project),
      virtualDeckWorld: virtualWorld,
      bridgeSides: [sideMinWorld.map(project), sideMaxWorld.map(project)],
      bridgeWings: bridgeWingsWorld.map(pair => pair.map(project)),
      curvedSpine: spine.map(project),
      upperShortEdgeClearanceM: upperClearanceM,
      upperDeckTrackCount: boundDeckChains.length,
      upperShortEdgeViolationCount,
      geometrySource: 'ENGINE_UPPER_TRACK_CURVE_SWEPT_DECK',
    };
  };
  const meanDirection = (items, key) => {
    const reference = items[0][key];
    const total = items.reduce((result, item) => {
      const direction = item[key];
      const sign = reference.x * direction.x + reference.y * direction.y < 0 ? -1 : 1;
      return {x: result.x + direction.x * sign, y: result.y + direction.y * sign};
    }, {x: 0, y: 0});
    return canonicalDirection(total);
  };
  const directionDifferenceDegrees = (left, right) => {
    const a = canonicalDirection(left || {x: 1, y: 0});
    const b = canonicalDirection(right || {x: 1, y: 0});
    const cosine = Math.max(-1, Math.min(1, Math.abs(a.x * b.x + a.y * b.y)));
    return Math.acos(cosine) * 180 / Math.PI;
  };
  const sharesTrackChain = (left, right, level) => {
    if (Number(left[`${level}_edge_id`]) === Number(right[`${level}_edge_id`])) return true;
    const leftNodes = new Set((left[`${level}_node_ids`] || []).map(Number));
    return (right[`${level}_node_ids`] || []).some(nodeId => leftNodes.has(Number(nodeId)));
  };
  const sameUpperDeck = (left, right, options = {}) => {
    if (sharesTrackChain(left, right, 'upper')) return true;
    return distance(left.position, right.position) <= (options.upperDeckLaneDistanceM ?? 15)
      && Math.abs(Number(left.upper_z) - Number(right.upper_z)) <= (options.upperDeckHeightToleranceM ?? 1.5)
      && directionDifferenceDegrees(left.upper_direction, right.upper_direction)
        <= (options.upperDeckDirectionToleranceDegrees ?? 15);
  };
  const structureFromMembers = members => ({
    position: {
      x: members.reduce((sum, item) => sum + item.position.x, 0) / members.length,
      y: members.reduce((sum, item) => sum + item.position.y, 0) / members.length,
    },
    upper_z: members.reduce((sum, item) => sum + item.upper_z, 0) / members.length,
    lower_z: members.reduce((sum, item) => sum + item.lower_z, 0) / members.length,
    upper_direction: meanDirection(members, 'upper_direction'),
    lower_direction: meanDirection(members, 'lower_direction'),
    upper_edge_ids: [...new Set(members.map(item => item.upper_edge_id))],
    lower_edge_ids: [...new Set(members.map(item => item.lower_edge_id))],
    members,
    source: 'ENGINE_XYZ_TOPOLOGY_BRIDGE_CLUSTER',
  });
  const cluster = (crossings, options = {}) => {
    const values = crossings || [];
    const parent = values.map((_, index) => index);
    const find = value => {
      let current = value;
      while (parent[current] !== current) {
        parent[current] = parent[parent[current]];
        current = parent[current];
      }
      return current;
    };
    const unite = (left, right) => {
      const leftRoot = find(left);
      const rightRoot = find(right);
      if (leftRoot !== rightRoot) parent[rightRoot] = leftRoot;
    };
    const radiusM = options.clusterRadiusM || 25;
    for (let left = 0; left < values.length; left += 1) {
      for (let right = left + 1; right < values.length; right += 1) {
        const a = values[left];
        const b = values[right];
        if (distance(a.position, b.position) > radiusM) continue;
        if (!sameUpperDeck(a, b, options)) continue;
        unite(left, right);
      }
    }
    const groups = new Map();
    values.forEach((value, index) => {
      const rootIndex = find(index);
      const members = groups.get(rootIndex) || [];
      members.push(value);
      groups.set(rootIndex, members);
    });
    return [...groups.values()].map(structureFromMembers);
  };
  const geometry = (crossing, project, options = {}) => {
    const members = crossing.members || [crossing];
    const laneSegments = (directionKey, paddingM, fixedRange = null) => {
      const direction = meanDirection(members, directionKey);
      const normal = {x: -direction.y, y: direction.x};
      const laneToleranceM = options.laneToleranceM || 2.5;
      const projected = members.map(member => ({
        member,
        along: member.position.x * direction.x + member.position.y * direction.y,
        across: member.position.x * normal.x + member.position.y * normal.y,
      })).sort((left, right) => left.across - right.across);
      const lanes = [];
      projected.forEach(item => {
        const lane = lanes[lanes.length - 1];
        const laneAcross = lane ? lane.reduce((sum, value) => sum + value.across, 0) / lane.length : null;
        if (!lane || Math.abs(item.across - laneAcross) > laneToleranceM) lanes.push([item]);
        else lane.push(item);
      });
      return lanes.map(lane => {
        const across = lane.reduce((sum, item) => sum + item.across, 0) / lane.length;
        const start = fixedRange ? fixedRange.start : Math.min(...lane.map(item => item.along)) - paddingM;
        const end = fixedRange ? fixedRange.end : Math.max(...lane.map(item => item.along)) + paddingM;
        return [
          project({x: direction.x * start + normal.x * across, y: direction.y * start + normal.y * across}),
          project({x: direction.x * end + normal.x * across, y: direction.y * end + normal.y * across}),
        ];
      });
    };
    const upperDirection = crossing.upper_direction || meanDirection(members, 'upper_direction');
    const upperNormal = {x: -upperDirection.y, y: upperDirection.x};
    // All bridge dimensions below are computed in the top-down XY plane. Z is
    // used only by detection to choose the upper deck and is never cosine-
    // corrected into the displayed bridge length.
    const positionedMembers = members.map(item => ({
      item,
      along: item.position.x * upperDirection.x + item.position.y * upperDirection.y,
      across: item.position.x * upperNormal.x + item.position.y * upperNormal.y,
    }));
    const upperAlong = positionedMembers.map(value => value.along);
    const upperAcross = positionedMembers.map(value => value.across);
    const bridgeSidePaddingM = options.bridgeSidePaddingM || 3.5;
    const crossingBounds = {
      left: Math.min(...upperAlong),
      right: Math.max(...upperAlong),
      bottom: Math.min(...upperAcross),
      top: Math.max(...upperAcross),
    };
    const observedBridgeLengthM = crossingBounds.right - crossingBounds.left;
    const minimumBridgeLengthM = options.minimumBridgeLengthM || 20;
    const bridgeCoreLengthM = Math.max(observedBridgeLengthM, minimumBridgeLengthM);
    const bridgeExtensionRatio = options.bridgeExtensionRatio ?? .15;
    const bridgeLengthM = bridgeCoreLengthM * (1 + bridgeExtensionRatio * 2);
    const bridgeCenter = (crossingBounds.left + crossingBounds.right) / 2;
    const baseBridgeStart = bridgeCenter - bridgeLengthM / 2;
    const baseBridgeEnd = bridgeCenter + bridgeLengthM / 2;
    const bridgeAcrossMin = crossingBounds.bottom - bridgeSidePaddingM;
    const bridgeAcrossMax = crossingBounds.top + bridgeSidePaddingM;
    const wingComponentM = options.bridgeWingComponentM ?? 2;
    // A corner belongs to both an end cap and a longitudinal side. Treat it as
    // an end-cap hit: a valid underpass entry must sit strictly inside the long
    // side, with this inset on both ends, before extension can stop.
    const virtualLongSideInsetM = options.virtualLongSideInsetM ?? 2;
    const virtualAcrossMin = bridgeAcrossMin - wingComponentM;
    const virtualAcrossMax = bridgeAcrossMax + wingComponentM;
    let requiredVirtualStart = baseBridgeStart - wingComponentM;
    let requiredVirtualEnd = baseBridgeEnd + wingComponentM;
    const lowerLineVirtualIntersections = [];
    positionedMembers.forEach(value => {
      const lowerDirection = canonicalDirection(value.item.lower_direction || crossing.lower_direction || {x: 0, y: 1});
      const alongRate = lowerDirection.x * upperDirection.x + lowerDirection.y * upperDirection.y;
      const acrossRate = lowerDirection.x * upperNormal.x + lowerDirection.y * upperNormal.y;
      if (Math.abs(acrossRate) <= 1e-9) return;
      const atAcross = across => value.along + (across - value.across) * alongRate / acrossRate;
      const entries = [atAcross(virtualAcrossMin), atAcross(virtualAcrossMax)];
      const minimumAlong = Math.min(...entries);
      const maximumAlong = Math.max(...entries);
      requiredVirtualStart = Math.min(requiredVirtualStart, minimumAlong - virtualLongSideInsetM);
      requiredVirtualEnd = Math.max(requiredVirtualEnd, maximumAlong + virtualLongSideInsetM);
      lowerLineVirtualIntersections.push({
        lower_edge_id: value.item.lower_edge_id,
        along: entries,
      });
    });
    // The wing endpoints are the virtual rectangle's vertices. Extend only the
    // longitudinal bridge sides until every underpass enters through one of
    // the virtual edges parallel to the visible white sides, never an end cap.
    const bridgeStart = requiredVirtualStart + wingComponentM;
    const bridgeEnd = requiredVirtualEnd - wingComponentM;
    const worldPoint = (along, across) => ({
      x: upperDirection.x * along + upperNormal.x * across,
      y: upperDirection.y * along + upperNormal.y * across,
    });

    // The underpass must be erased across the complete bridge deck, not merely
    // around the mathematical centre-line intersection.  Projecting all four
    // deck corners onto the lower-track axis also works for oblique crossings.
    const lowerDirection = crossing.lower_direction || meanDirection(members, 'lower_direction');
    const deckCorners = [
      worldPoint(bridgeStart, bridgeAcrossMin), worldPoint(bridgeStart, bridgeAcrossMax),
      worldPoint(bridgeEnd, bridgeAcrossMin), worldPoint(bridgeEnd, bridgeAcrossMax),
    ];
    const lowerProjection = deckCorners.map(point => point.x * lowerDirection.x + point.y * lowerDirection.y);
    const gapEndClearanceM = options.gapEndClearanceM ?? 3;
    const gapRange = {
      start: Math.min(...lowerProjection) - gapEndClearanceM,
      end: Math.max(...lowerProjection) + gapEndClearanceM,
    };

    // Conventional schematic bridge outline: an opaque rectangular deck with
    // only its two longitudinal edges visible, plus four 45-degree wings.
    const wingLengthM = Math.hypot(wingComponentM, wingComponentM);
    const deck = [
      project(worldPoint(bridgeStart, bridgeAcrossMin)),
      project(worldPoint(bridgeStart, bridgeAcrossMax)),
      project(worldPoint(bridgeEnd, bridgeAcrossMax)),
      project(worldPoint(bridgeEnd, bridgeAcrossMin)),
    ];
    const maskPaddingM = options.bridgeMaskPaddingM ?? 1.25;
    const maskDeck = [
      project(worldPoint(bridgeStart - maskPaddingM, bridgeAcrossMin - maskPaddingM)),
      project(worldPoint(bridgeStart - maskPaddingM, bridgeAcrossMax + maskPaddingM)),
      project(worldPoint(bridgeEnd + maskPaddingM, bridgeAcrossMax + maskPaddingM)),
      project(worldPoint(bridgeEnd + maskPaddingM, bridgeAcrossMin - maskPaddingM)),
    ];
    const bridgeSides = [
      {across: bridgeAcrossMin, sign: -1},
      {across: bridgeAcrossMax, sign: 1},
    ].map(side => [
      project(worldPoint(bridgeStart, side.across)),
      project(worldPoint(bridgeEnd, side.across)),
    ]);
    const bridgeWings = [
      [worldPoint(bridgeStart, bridgeAcrossMin), worldPoint(bridgeStart - wingComponentM, bridgeAcrossMin - wingComponentM)],
      [worldPoint(bridgeStart, bridgeAcrossMax), worldPoint(bridgeStart - wingComponentM, bridgeAcrossMax + wingComponentM)],
      [worldPoint(bridgeEnd, bridgeAcrossMin), worldPoint(bridgeEnd + wingComponentM, bridgeAcrossMin - wingComponentM)],
      [worldPoint(bridgeEnd, bridgeAcrossMax), worldPoint(bridgeEnd + wingComponentM, bridgeAcrossMax + wingComponentM)],
    ].map(pair => pair.map(project));
    const virtualDeckWorld = [
      worldPoint(bridgeStart - wingComponentM, bridgeAcrossMin - wingComponentM),
      worldPoint(bridgeStart - wingComponentM, bridgeAcrossMax + wingComponentM),
      worldPoint(bridgeEnd + wingComponentM, bridgeAcrossMax + wingComponentM),
      worldPoint(bridgeEnd + wingComponentM, bridgeAcrossMin - wingComponentM),
    ];
    const result = {
      gaps: laneSegments('lower_direction', 0, gapRange),
      uppers: laneSegments('upper_direction', options.upperPaddingM || 8),
      deck,
      maskDeck,
      virtualDeck: virtualDeckWorld.map(project),
      virtualDeckWorld,
      crossingBounds,
      approachExtensions: {
        left: baseBridgeStart - bridgeStart,
        right: bridgeEnd - baseBridgeEnd,
      },
      lowerLineVirtualIntersections,
      virtualLongSideInsetM,
      wingComponentM,
      wingLengthM,
      worldFrame: {
        direction: upperDirection,
        normal: upperNormal,
        start: bridgeStart - maskPaddingM,
        end: bridgeEnd + maskPaddingM,
        acrossMin: bridgeAcrossMin - maskPaddingM,
        acrossMax: bridgeAcrossMax + maskPaddingM,
      },
      bridgeSides,
      bridgeWings,
      geometrySource: 'ENGINE_UPPER_DIRECTION_RECTANGLE_FALLBACK',
    };
    // The railway itself is redrawn from the engine's exact Hermite curve,
    // but a schematic bridge symbol is an oriented rectangle.  Sweeping the
    // white sides along every sampled curve made throat bridges kink and made
    // near-node crossings look as if the bridge belonged to the wrong edge.
    // Keep curved outlines as an explicit diagnostic option only.
    const curved = options.curvedBridgeOutline === true ? curvedDeckGeometry(
      members,
      positionedMembers,
      {direction: upperDirection, deckStart: bridgeStart, deckEnd: bridgeEnd},
      options.upperPolylines,
      project,
      options,
    ) : null;
    return curved ? {...result, ...curved} : result;
  };
  const polygonsOverlap = (left, right) => {
    const axes = [];
    [left, right].forEach(polygon => {
      for (let index = 0; index < polygon.length; index += 1) {
        const start = polygon[index];
        const end = polygon[(index + 1) % polygon.length];
        const edge = {x: end.x - start.x, y: end.y - start.y};
        const axisLength = Math.hypot(edge.x, edge.y);
        if (axisLength > 1e-9) axes.push({x: -edge.y / axisLength, y: edge.x / axisLength});
      }
    });
    const epsilon = 1e-7;
    return axes.every(axis => {
      const leftProjection = left.map(point => point.x * axis.x + point.y * axis.y);
      const rightProjection = right.map(point => point.x * axis.x + point.y * axis.y);
      return Math.max(...leftProjection) >= Math.min(...rightProjection) - epsilon &&
        Math.max(...rightProjection) >= Math.min(...leftProjection) - epsilon;
    });
  };
  const resolveStructures = (crossings, options = {}) => {
    let structures = cluster(crossings, options);
    // Merging changes the mean bridge axis and therefore its virtual rectangle.
    // Recompute and repeat until an entire pass produces no overlap.
    while (structures.length > 1) {
      const shapes = structures.map(structure => geometry(structure, point => point, options));
      const parent = structures.map((_, index) => index);
      const find = value => {
        let current = value;
        while (parent[current] !== current) {
          parent[current] = parent[parent[current]];
          current = parent[current];
        }
        return current;
      };
      let merged = false;
      for (let left = 0; left < structures.length; left += 1) {
        for (let right = left + 1; right < structures.length; right += 1) {
          if (!polygonsOverlap(shapes[left].virtualDeckWorld, shapes[right].virtualDeckWorld)) continue;
          if (!structures[left].members.some(a => structures[right].members.some(b => sameUpperDeck(a, b, options)))) continue;
          const leftRoot = find(left);
          const rightRoot = find(right);
          if (leftRoot === rightRoot) continue;
          parent[rightRoot] = leftRoot;
          merged = true;
        }
      }
      if (!merged) break;
      const groups = new Map();
      structures.forEach((structure, index) => {
        const rootIndex = find(index);
        const members = groups.get(rootIndex) || [];
        members.push(...structure.members);
        groups.set(rootIndex, members);
      });
      structures = [...groups.values()].map(structureFromMembers);
    }
    return structures;
  };
  const expandUpperEdgeIds = (crossing, shape, edgeById, nodeById, edgeIdsByNode, options = {}) => {
    const seeds = [...new Set(crossing.upper_edge_ids || [crossing.upper_edge_id])].map(Number).filter(Number.isFinite);
    if (!(edgeById instanceof Map) || !(nodeById instanceof Map) || !(edgeIdsByNode instanceof Map) || !shape?.worldFrame) return seeds;
    const frame = shape.worldFrame;
    const nodeInsideDeck = nodeId => {
      const value = nodeById.get(Number(nodeId));
      const point = value?.position || value;
      if (!point) return false;
      const along = point.x * frame.direction.x + point.y * frame.direction.y;
      const across = point.x * frame.normal.x + point.y * frame.normal.y;
      return along >= frame.start && along <= frame.end && across >= frame.acrossMin && across <= frame.acrossMax;
    };
    const result = new Set(seeds.map(Number));
    const queue = [...result];
    const positionForNode = nodeId => nodePosition(nodeById.get(Number(nodeId)));
    const awayDirection = (edge, nodeId) => {
      const atStart = Number(edge.node0) === Number(nodeId);
      const here = positionForNode(nodeId);
      const other = positionForNode(atStart ? edge.node1 : edge.node0);
      if (!here || !other) return null;
      const tangent = atStart ? edge.tangent0 : edge.tangent1;
      const raw = tangent
        ? {x: (tangent.x || 0) * (atStart ? 1 : -1), y: (tangent.y || 0) * (atStart ? 1 : -1)}
        : {x: other.x - here.x, y: other.y - here.y};
      const length = Math.hypot(raw.x, raw.y);
      return length > 1e-9 ? {x: raw.x / length, y: raw.y / length} : null;
    };
    const continuationAngle = (edge, neighbor, nodeId) => {
      const left = awayDirection(edge, nodeId);
      const right = awayDirection(neighbor, nodeId);
      if (!left || !right) return Infinity;
      // At a continuous joint the two vectors pointing away from the shared
      // node face opposite directions, hence the leading minus sign.
      const cosine = Math.max(-1, Math.min(1, -(left.x * right.x + left.y * right.y)));
      return Math.acos(cosine) * 180 / Math.PI;
    };
    const maximumContinuationAngle = options.upperContinuationAngleDegrees ?? 30;
    const continuationTieDegrees = options.upperContinuationTieDegrees ?? 2;
    const expandContinuations = () => {
      while (queue.length) {
        const edgeId = queue.shift();
        const edge = edgeById.get(Number(edgeId));
        if (!edge) continue;
        [edge.node0, edge.node1].forEach(nodeId => {
          if (!nodeInsideDeck(nodeId)) return;
          const candidates = (edgeIdsByNode.get(Number(nodeId)) || [])
            .map(Number)
            .filter(neighborId => neighborId !== Number(edgeId))
            .map(neighborId => ({
              neighborId,
              neighbor: edgeById.get(neighborId),
            }))
            .filter(value => value.neighbor)
            .map(value => ({...value, angle: continuationAngle(edge, value.neighbor, nodeId)}))
            .filter(value => value.angle <= maximumContinuationAngle)
            .sort((left, right) => left.angle - right.angle);
          if (!candidates.length) return;
          const bestAngle = candidates[0].angle;
          candidates
            .filter(value => value.angle <= bestAngle + continuationTieDegrees)
            .forEach(({neighborId}) => {
              if (result.has(neighborId)) return;
              result.add(neighborId);
              queue.push(neighborId);
            });
        });
      }
    };
    expandContinuations();

    return [...result];
  };
  const renderSvg = (crossings, project, createElement, parent, options = {}) => {
    const linePath = pair => `M${pair[0].x.toFixed(2)},${pair[0].y.toFixed(2)}L${pair[1].x.toFixed(2)},${pair[1].y.toFixed(2)}`;
    const pointsPath = points => points.map((point, index) => `${index ? 'L' : 'M'}${point.x.toFixed(2)},${point.y.toFixed(2)}`).join('');
    const polygonPath = points => `${pointsPath(points)}Z`;
    const structures = resolveStructures(crossings, options);
    const rendered = structures.map((crossing, bridgeIndex) => {
      const preliminaryShape = geometry(crossing, project, options);
      const upperEdgeIds = options.upperEdgeIdsForBridge?.(crossing, preliminaryShape) || crossing.upper_edge_ids || [];
      const uniqueUpperEdgeIds = [...new Set(upperEdgeIds)];
      const upperPolylines = uniqueUpperEdgeIds.map(edgeId => options.upperPointsForEdge?.(edgeId)).filter(points => points?.length >= 2);
      return {
        crossing,
        bridgeIndex,
        upperEdgeIds: uniqueUpperEdgeIds,
        shape: geometry(crossing, project, {...options, upperPolylines}),
      };
    }).sort((left, right) => Number(left.crossing.upper_z) - Number(right.crossing.upper_z));
    const clipPrefix = `rail-bridge-clip-${++renderSequence}`;
    const definitions = createElement('defs', {}, '', parent);
    rendered.forEach(({shape, bridgeIndex}) => {
      const clip = createElement('clipPath', {id: `${clipPrefix}-${bridgeIndex}`}, '', definitions);
      (shape.maskDecks || [shape.maskDeck]).forEach(deck => createElement('path', {d: polygonPath(deck)}, '', clip));
    });

    // Each bridge is composited from low Z to high Z. Its opaque footprint
    // removes every lower rail; only this deck's own highest rail group is
    // restored before a still-higher bridge can cover it in turn.
    rendered.forEach(({shape, bridgeIndex, upperEdgeIds}) => {
      (shape.maskDecks || [shape.maskDeck]).forEach(deck => createElement('path', {
          d: polygonPath(deck), fill: options.background || '#070c12', stroke: 'none', 'pointer-events': 'none',
          'data-bridge-role': 'bridge-deck-mask', 'data-bridge-index': bridgeIndex,
        }, '', parent));
      const exactPaths = upperEdgeIds
        .map(edgeId => options.upperPathForEdge?.(edgeId))
        .filter(Boolean);
      const paths = exactPaths.length ? exactPaths : shape.uppers.map(linePath);
      paths.forEach(path => createElement('path', {
          d: path, fill: 'none', stroke: options.trackColor || '#83a9bd', 'stroke-width': options.trackStrokeWidth || 1.4,
          'vector-effect': 'non-scaling-stroke', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'pointer-events': 'none',
          'clip-path': `url(#${clipPrefix}-${bridgeIndex})`,
          'data-bridge-role': 'upper-track', 'data-bridge-index': bridgeIndex,
        }, '', parent));
      shape.bridgeSides.forEach(pair => createElement('path', {
        d: pointsPath(pair), fill: 'none', stroke: options.markerColor || '#dce7ef', 'stroke-width': options.markerStrokeWidth || 1.1,
        'vector-effect': 'non-scaling-stroke', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'pointer-events': 'none',
        'data-bridge-role': 'bridge-side', 'data-bridge-index': bridgeIndex,
      }, '', parent));
      shape.bridgeWings.forEach(pair => createElement('path', {
        d: linePath(pair), fill: 'none', stroke: options.markerColor || '#dce7ef', 'stroke-width': options.markerStrokeWidth || 1.1,
        'vector-effect': 'non-scaling-stroke', 'stroke-linecap': 'round', 'pointer-events': 'none',
        'data-bridge-role': 'bridge-wing', 'data-bridge-index': bridgeIndex,
      }, '', parent));
    });
    return structures.length;
  };
  return {detect, sampleEdge, cluster, geometry, resolveStructures, expandUpperEdgeIds, renderSvg};
}));
