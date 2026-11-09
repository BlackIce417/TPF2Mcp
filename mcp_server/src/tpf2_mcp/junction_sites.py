"""Candidate place grouping and review gates, separate from track connectivity.

Sites never add graph edges. A site is a reviewable collection of connected
switch groups, not a confirmed railway operating point.
"""
from collections import Counter


def build_sites(regions, quality, graph):
    by_id = {r['id']: r for r in regions}
    # Only reciprocal, unambiguous pairs may be considered. A-B-C proximity
    # chains must not silently collapse to one place.
    provisional = {}
    for region in regions:
        peers = region['parallel_peer_ids']
        if len(peers) == 1 and by_id[peers[0]]['parallel_peer_ids'] == [region['id']]:
            provisional[region['id']] = min(region['id'], peers[0])
    def destinations(region):
        return {provisional.get(g['destination'], g['destination']) for g in region['destination_groups']}

    paired = {}
    for region in regions:
        if region['id'] not in provisional:
            continue
        peer = by_id[region['parallel_peer_ids'][0]]
        ends = destinations(region)
        if len(ends) >= 2 and ends == destinations(peer):
            paired[region['id']] = peer['id']

    consumed, sites = set(), []
    for region in regions:
        if region['id'] in consumed:
            continue
        members = [region]
        if region['id'] in paired:
            members.append(by_id[paired[region['id']]])
        consumed.update(r['id'] for r in members)
        site_id = f"site-{min(n for r in members for n in r['switch_node_ids'])}"
        for r in members:
            r['site_id'] = site_id
        sites.append(dict(id=site_id, name=f"候选地点 {site_id[5:]}",
                          region_ids=sorted(r['id'] for r in members),
                          grouping_basis='PARALLEL_GEOMETRY_AND_MATCHING_DESTINATIONS' if len(members)>1 else 'SINGLE_CONNECTED_GROUP',
                          grouping_status='PROVISIONAL', creates_track_connections=False))

    for region in regions:
        # A long probe finding a dead end overrides a short geometric impression.
        ports = region['ports']
        ends = [p['destination'] for p in ports]
        known = [p for p in ports if p['destination']['key']]
        normalized = {}
        for p in known:
            key = p['destination']['key']
            key = by_id[key]['site_id'] if key in by_id else key
            normalized.setdefault(key, []).append(p['id'])
        region['normalized_destination_groups'] = [dict(destination=k, port_ids=v) for k,v in sorted(normalized.items())]
        incomplete = any(d['stop_reason']=='DISTANCE_LIMIT' or
                         (d['stop_reason'] in ('STATION_BOUNDARY','SWITCH') and not d['key']) for d in ends)
        region['trace_complete'] = not incomplete
        region['classification_basis'] = 'LOCAL_GEOMETRY_ONLY'
        if len(normalized) >= 3:
            region['classification'] = 'JUNCTION_CANDIDATE'
            region['classification_basis'] = 'DISTINCT_TOPOLOGICAL_ENDPOINTS'
        elif not incomplete:
            if len(normalized)==2 and len(known)>=4 and len(region['through_direction_groups'])==2:
                region['classification'] = 'CROSSOVER_CANDIDATE'
                region['classification_basis'] = 'TWO_ENDPOINTS_AND_PARALLEL_DIRECTIONS'
            elif any(d['stop_reason']=='DEPOT_CONNECTION' for d in ends):
                region['classification'] = 'DEPOT_ACCESS'
                region['classification_basis'] = 'DEPOT_ENDPOINT'
            elif any(d['stop_reason']=='DEAD_END' for d in ends):
                region['classification'] = 'SIDING_OR_UNFINISHED'
                region['classification_basis'] = 'DEAD_END_ENDPOINT'
            else:
                region['classification'] = 'UNRESOLVED_SWITCH_GROUP'
                region['classification_basis'] = 'INSUFFICIENT_ENDPOINT_SEPARATION'
        else:
            region['classification'] = 'UNRESOLVED_SWITCH_GROUP'
            region['flags'].append('INCOMPLETE_DESTINATION_TRACE')
        blockers = ['SIGNAL_BOUNDARY_NOT_VALIDATED', 'LEGAL_ROUTES_NOT_VALIDATED']
        if incomplete: blockers.append('INCOMPLETE_DESTINATION_TRACE')
        if quality['stations_without_core'] or quality['unresolved_throat_stations']:
            blockers.append('STATION_MASK_INCOMPLETE')
        if 'CLUSTER_SIZE_LIMIT' in region['flags']: blockers.append('CLUSTER_SIZE_LIMIT')
        if 'NEAR_STATION_BOUNDARY' in region['flags']: blockers.append('STATION_THROAT_BOUNDARY_REVIEW')
        internal = set(region['edge_ids'])
        members = set(region['switch_node_ids']) | {graph.edges[eid][k] for eid in internal for k in ('node0','node1')}
        expected = {(node,eid) for node in members for eid,_ in graph.adjacency[node] if eid not in internal}
        supplied = [(p['node_id'],p['outside_edge_id']) for p in ports]
        valid = set(supplied)==expected and len(supplied)==len(set(supplied))
        region['boundary_validation'] = dict(status='COMPLETE_TOPOLOGICAL_CUT' if valid else 'INVALID_TOPOLOGICAL_CUT',
                                            expected_interface_count=len(expected), reported_interface_count=len(supplied))
        if not valid: blockers.append('INVALID_TOPOLOGICAL_CUT')
        region['review'] = dict(status='NEEDS_REVIEW', planning_ready=False,
                                boundary_type='TOPOLOGICAL_INTERFACE_NOT_SIGNAL_LIMIT', blockers=blockers)

    for site in sites:
        members = [by_id[rid] for rid in site['region_ids']]
        types = sorted({r['classification'] for r in members})
        site['classification'] = types[0] if len(types)==1 else 'UNRESOLVED_SWITCH_GROUP'
        site['review'] = dict(status='NEEDS_REVIEW', planning_ready=False,
                             blockers=sorted({b for r in members for b in r['review']['blockers']} |
                                             ({'PARALLEL_GROUPING_PROVISIONAL'} if len(members)>1 else set())))
        site['ports'] = [dict(region_id=r['id'], port_id=p['id'], node_id=p['node_id'], outside_edge_id=p['outside_edge_id'])
                         for r in members for p in r['ports']]
    return sites, dict(Counter(r['classification'] for r in regions))
