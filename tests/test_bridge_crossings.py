import json
from pathlib import Path
import subprocess
import unittest

from tpf2_mcp.rail_crossings import detect_grade_separated_crossings


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "ui/rail-map/bridge-crossings.js"


def run_detector(nodes: list[dict], edges: list[dict]) -> list[dict]:
    script = r"""
const detector = require(process.argv[1]);
const input = JSON.parse(process.argv[2]);
const nodes = new Map(input.nodes.map(node => [node.entity_id, node.position]));
process.stdout.write(JSON.stringify(detector.detect(input.edges, nodes, {samples: 4})));
"""
    completed = subprocess.run(
        ["node", "-e", script, str(MODULE), json.dumps({"nodes": nodes, "edges": edges})],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return json.loads(completed.stdout)


def run_cluster(crossings: list[dict]) -> dict:
    script = r"""
const detector = require(process.argv[1]);
const crossings = JSON.parse(process.argv[2]);
const structures = detector.resolveStructures(crossings);
const shape = detector.geometry(structures[0], point => point);
process.stdout.write(JSON.stringify({structures: structures.length, members: structures[0].members.length,
  upperEdges: structures[0].upper_edge_ids.length, lowerEdges: structures[0].lower_edge_ids.length,
  gaps: shape.gaps.length, uppers: shape.uppers.length, bridgeSides: shape.bridgeSides.length,
  deckPoints: shape.deck.length, bridgeWings: shape.bridgeWings.length,
  sidePointCount: shape.bridgeSides[0].length,
  sideDirection: {x: shape.bridgeSides[0][1].x - shape.bridgeSides[0][0].x,
    y: shape.bridgeSides[0][1].y - shape.bridgeSides[0][0].y},
  wingDirection: {x: shape.bridgeWings[0][1].x - shape.bridgeWings[0][0].x,
    y: shape.bridgeWings[0][1].y - shape.bridgeWings[0][0].y},
  wingComponentM: shape.wingComponentM, wingLengthM: shape.wingLengthM,
  virtualLongSideInsetM: shape.virtualLongSideInsetM,
  approachExtensions: shape.approachExtensions,
  virtualDeck: shape.virtualDeck,
  lowerLineVirtualIntersections: shape.lowerLineVirtualIntersections,
  firstGap: shape.gaps[0]}));
"""
    completed = subprocess.run(
        ["node", "-e", script, str(MODULE), json.dumps(crossings)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return json.loads(completed.stdout)


def run_upper_edge_expansion() -> list[int]:
    script = r"""
const detector = require(process.argv[1]);
const crossing = {
  position: {x: 0, y: 0}, upper_z: 8, lower_z: 2,
  upper_edge_id: 10, lower_edge_id: 20,
  upper_direction: {x: 1, y: 0}, lower_direction: {x: 0, y: 1},
};
const structure = detector.cluster([crossing])[0];
const shape = detector.geometry(structure, point => point);
const edges = [
  {entity_id: 10, node0: 1, node1: 2},
  {entity_id: 11, node0: 2, node1: 3},
  {entity_id: 12, node0: 3, node1: 4},
  {entity_id: 13, node0: 2, node1: 5},
];
const edgeById = new Map(edges.map(edge => [edge.entity_id, edge]));
const nodeById = new Map([
  [1, {x: -20, y: 0}], [2, {x: 0, y: 0}],
  [3, {x: 20, y: 0}], [4, {x: 40, y: 0}],
  [5, {x: 10, y: 10}],
]);
const edgeIdsByNode = new Map([[1, [10]], [2, [10, 11, 13]], [3, [11, 12]], [4, [12]], [5, [13]]]);
process.stdout.write(JSON.stringify(detector.expandUpperEdgeIds(
  structure, shape, edgeById, nodeById, edgeIdsByNode,
).sort((left, right) => left - right)));
"""
    completed = subprocess.run(
        ["node", "-e", script, str(MODULE)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return json.loads(completed.stdout)


def run_curved_geometry() -> dict:
    script = r"""
const detector = require(process.argv[1]);
const crossings = [
  {position:{x:0,y:0},upper_z:10,lower_z:0,upper_edge_id:1,lower_edge_id:2,
   upper_node_ids:[1,2],upper_direction:{x:1,y:0},lower_direction:{x:0,y:1}},
  {position:{x:15,y:5},upper_z:10,lower_z:0,upper_edge_id:1,lower_edge_id:3,
   upper_node_ids:[1,2],upper_direction:{x:.9,y:.3},lower_direction:{x:0,y:1}},
  {position:{x:30,y:15},upper_z:10,lower_z:0,upper_edge_id:1,lower_edge_id:4,
   upper_node_ids:[1,2],upper_direction:{x:.8,y:.6},lower_direction:{x:0,y:1}},
];
const structure = detector.resolveStructures(crossings)[0];
const shape = detector.geometry(structure, point => point, {upperPolylines:[[
  {x:-20,y:-2},{x:0,y:0},{x:15,y:5},{x:30,y:15},{x:50,y:35},
]], curvedBridgeOutline:true});
process.stdout.write(JSON.stringify({source:shape.geometrySource,sidePoints:shape.bridgeSides[0].length,
  clearance:shape.upperShortEdgeClearanceM,deckPoints:shape.deck.length,
  endViolations:shape.upperShortEdgeViolationCount,maskDecks:shape.maskDecks.length,
  maskDeckPointCounts:shape.maskDecks.map(deck=>deck.length)}));
"""
    completed = subprocess.run(
        ["node", "-e", script, str(MODULE)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return json.loads(completed.stdout)


def run_render_order() -> list[str]:
    script = r"""
const detector=require(process.argv[1]),root={children:[]};
const create=(tag,attrs,text,parent=root)=>{const node={tag,attrs,children:[]};parent.children.push(node);return node;};
detector.renderSvg([
  {position:{x:0,y:0},upper_z:20,lower_z:0,upper_edge_id:1,lower_edge_id:2,
   upper_direction:{x:1,y:0},lower_direction:{x:0,y:1}},
  {position:{x:100,y:0},upper_z:10,lower_z:0,upper_edge_id:3,lower_edge_id:4,
   upper_direction:{x:1,y:0},lower_direction:{x:0,y:1}},
],point=>point,create,root);
process.stdout.write(JSON.stringify(root.children.filter(node=>node.attrs?.['data-bridge-role'])
  .map(node=>`${node.attrs['data-bridge-role']}:${node.attrs['data-bridge-index']}`)));
"""
    completed = subprocess.run(
        ["node", "-e", script, str(MODULE)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return json.loads(completed.stdout)


class BridgeCrossingTests(unittest.TestCase):
    def test_bridge_deck_follows_real_curved_upper_track_with_three_metre_end_clearance(self):
        result = run_curved_geometry()

        self.assertEqual("ENGINE_UPPER_TRACK_CURVE_SWEPT_DECK", result["source"])
        self.assertGreater(result["sidePoints"], 2)
        self.assertGreater(result["deckPoints"], 4)
        self.assertEqual(3, result["clearance"])
        self.assertEqual(0, result["endViolations"])
        self.assertGreater(result["maskDecks"], 1)
        self.assertEqual({4}, set(result["maskDeckPointCounts"]))

    def test_overlapping_bridge_compositor_draws_lower_z_before_higher_z(self):
        roles = run_render_order()

        self.assertEqual("bridge-deck-mask:1", roles[0])
        self.assertIn("upper-track:1", roles)
        self.assertGreater(roles.index("bridge-deck-mask:0"), roles.index("upper-track:1"))

    def test_upper_track_redraw_follows_adjacent_edges_inside_extended_deck(self):
        self.assertEqual([10, 11], run_upper_edge_expansion())

    def test_default_bridge_symbol_keeps_straight_rectangular_sides(self):
        crossings = [{
            "position": {"x": 0, "y": 0}, "upper_z": 10, "lower_z": 0,
            "upper_edge_id": 1, "lower_edge_id": 2,
            "upper_direction": {"x": 1, "y": 0},
            "lower_direction": {"x": 0, "y": 1},
        }]

        result = run_cluster(crossings)

        self.assertEqual(2, result["sidePointCount"])

    def test_double_track_crossing_is_one_bridge_with_two_upper_and_lower_lanes(self):
        crossings = []
        for upper_index, upper_x in enumerate((-3, 3), 1):
            for lower_index, lower_y in enumerate((-3, 3), 1):
                crossings.append({
                    "position": {"x": upper_x, "y": lower_y},
                    "upper_z": 8, "lower_z": 2,
                    "upper_edge_id": 100 + upper_index,
                    "lower_edge_id": 200 + lower_index,
                    "upper_direction": {"x": 0, "y": 1},
                    "lower_direction": {"x": 1, "y": 0},
                })

        result = run_cluster(crossings)

        self.assertEqual({
            "structures": 1, "members": 4, "upperEdges": 2, "lowerEdges": 2,
        }, {key: result[key] for key in ("structures", "members", "upperEdges", "lowerEdges")})
        self.assertEqual(2, result["gaps"])
        self.assertEqual(2, result["uppers"])
        self.assertEqual(2, result["bridgeSides"])
        self.assertEqual(4, result["deckPoints"])
        self.assertEqual(4, result["bridgeWings"])
        self.assertEqual(2, result["sidePointCount"])
        self.assertAlmostEqual(0, result["sideDirection"]["x"], places=6)
        self.assertAlmostEqual(26, result["sideDirection"]["y"], places=6)
        self.assertAlmostEqual(2, abs(result["wingDirection"]["x"]), places=6)
        self.assertAlmostEqual(2, abs(result["wingDirection"]["y"]), places=6)
        self.assertAlmostEqual(abs(result["wingDirection"]["x"]), abs(result["wingDirection"]["y"]), places=6)
        self.assertAlmostEqual(2, result["wingComponentM"], places=6)
        self.assertAlmostEqual(8 ** .5, result["wingLengthM"], places=6)
        self.assertAlmostEqual(2, result["virtualLongSideInsetM"], places=6)
        self.assertLessEqual(result["firstGap"][0]["x"], -9.5)
        self.assertGreaterEqual(result["firstGap"][1]["x"], 9.5)

    def test_shallow_underpass_extends_until_it_enters_virtual_long_side(self):
        crossings = [
            {
                "position": {"x": 0, "y": 0}, "upper_z": 20, "lower_z": 8,
                "upper_edge_id": 100, "lower_edge_id": 200,
                "upper_direction": {"x": 1, "y": 0},
                "lower_direction": {"x": 0.9396926208, "y": 0.3420201433},
            },
            {
                "position": {"x": 20, "y": 0}, "upper_z": 20, "lower_z": 8,
                "upper_edge_id": 100, "lower_edge_id": 201,
                "upper_direction": {"x": 1, "y": 0},
                "lower_direction": {"x": 0, "y": 1},
            },
        ]

        result = run_cluster(crossings)

        self.assertGreater(result["approachExtensions"]["left"], 12)
        self.assertLess(result["approachExtensions"]["left"], 13)
        self.assertAlmostEqual(0, result["approachExtensions"]["right"], places=6)
        self.assertAlmostEqual(
            26 + result["approachExtensions"]["left"],
            result["sideDirection"]["x"], places=6,
        )
        virtual_start = min(point["x"] for point in result["virtualDeck"])
        virtual_end = max(point["x"] for point in result["virtualDeck"])
        for lower_line in result["lowerLineVirtualIntersections"]:
            self.assertGreaterEqual(
                min(lower_line["along"]) - virtual_start,
                result["virtualLongSideInsetM"] - 1e-9,
            )
            self.assertGreaterEqual(
                virtual_end - max(lower_line["along"]),
                result["virtualLongSideInsetM"] - 1e-9,
            )

    def test_virtual_rectangle_corner_counts_as_short_edge_and_extends_both_ends(self):
        result = run_cluster([{
            "position": {"x": 0, "y": 0}, "upper_z": 20, "lower_z": 8,
            "upper_edge_id": 100, "lower_edge_id": 200,
            "upper_direction": {"x": 1, "y": 0},
            "lower_direction": {"x": 30, "y": 11},
        }])

        self.assertAlmostEqual(2, result["approachExtensions"]["left"], places=6)
        self.assertAlmostEqual(2, result["approachExtensions"]["right"], places=6)

    def test_nearby_edge_fragments_still_form_one_physical_bridge(self):
        crossings = [
            {
                "position": {"x": offset, "y": offset / 4}, "upper_z": 20 + offset / 100,
                "lower_z": 8 + offset / 100, "upper_edge_id": 100 + index,
                "lower_edge_id": 200 + index, "upper_direction": {"x": 1, "y": 0},
                "upper_node_ids": [index, index + 1],
                "lower_node_ids": [1000 + index, 1001 + index],
                "lower_direction": {"x": 0, "y": 1},
            }
            for index, offset in enumerate((-9, -3, 3, 9))
        ]

        result = run_cluster(crossings)

        self.assertEqual(1, result["structures"])
        self.assertEqual(4, result["members"])
        self.assertEqual(2, result["bridgeSides"])

    def test_overlapping_virtual_rectangles_merge_after_initial_clustering(self):
        crossings = [
            {
                "position": {"x": offset, "y": 0}, "upper_z": 20, "lower_z": 8,
                "upper_edge_id": 100 + index, "lower_edge_id": 200 + index,
                "upper_node_ids": [1, 2],
                "upper_direction": {"x": 1, "y": 0}, "lower_direction": {"x": 0, "y": 1},
            }
            for index, offset in enumerate((0, 28))
        ]

        result = run_cluster(crossings)

        self.assertEqual(1, result["structures"])
        self.assertEqual(2, result["members"])

    def test_non_overlapping_virtual_rectangles_remain_separate_bridges(self):
        crossings = [
            {
                "position": {"x": offset, "y": 0}, "upper_z": 20, "lower_z": 8,
                "upper_edge_id": 100 + index, "lower_edge_id": 200 + index,
                "upper_direction": {"x": 1, "y": 0}, "lower_direction": {"x": 0, "y": 1},
            }
            for index, offset in enumerate((0, 40))
        ]

        result = run_cluster(crossings)

        self.assertEqual(2, result["structures"])

    def test_overlapping_masks_do_not_merge_different_upper_track_directions(self):
        crossings = [
            {
                "position": {"x": 0, "y": 0}, "upper_z": 20, "lower_z": 8,
                "upper_edge_id": 100, "lower_edge_id": 200,
                "upper_direction": {"x": 1, "y": 0}, "lower_direction": {"x": 0, "y": 1},
            },
            {
                "position": {"x": 2, "y": 2}, "upper_z": 20, "lower_z": 8,
                "upper_edge_id": 101, "lower_edge_id": 201,
                "upper_direction": {"x": 0, "y": 1}, "lower_direction": {"x": 1, "y": 0},
            },
        ]

        self.assertEqual(2, run_cluster(crossings)["structures"])

    def test_shallow_non_parallel_crossing_has_no_business_angle_limit(self):
        nodes = [
            {"entity_id": 1, "position": {"x": -100, "y": 0, "z": 2}},
            {"entity_id": 2, "position": {"x": 100, "y": 0, "z": 2}},
            {"entity_id": 3, "position": {"x": -100, "y": -5, "z": 8}},
            {"entity_id": 4, "position": {"x": 100, "y": 5, "z": 8}},
        ]
        edges = [
            {"entity_id": 10, "node0": 1, "node1": 2},
            {"entity_id": 20, "node0": 3, "node1": 4},
        ]

        self.assertEqual(1, len(run_detector(nodes, edges)))
        self.assertEqual(1, len(detect_grade_separated_crossings(edges, nodes, samples=4)))

    def test_disconnected_xy_crossing_uses_engine_height_to_choose_upper_track(self):
        nodes = [
            {"entity_id": 1, "position": {"x": -20, "y": 0, "z": 2}},
            {"entity_id": 2, "position": {"x": 20, "y": 0, "z": 2}},
            {"entity_id": 3, "position": {"x": 0, "y": -20, "z": 8}},
            {"entity_id": 4, "position": {"x": 0, "y": 20, "z": 8}},
        ]
        edges = [
            {"entity_id": 10, "node0": 1, "node1": 2},
            {"entity_id": 20, "node0": 3, "node1": 4},
        ]

        crossings = run_detector(nodes, edges)
        python_crossings = detect_grade_separated_crossings(edges, nodes, samples=4)

        self.assertEqual(1, len(crossings))
        self.assertEqual(1, len(python_crossings))
        self.assertEqual(20, crossings[0]["upper_edge_id"])
        self.assertEqual(20, python_crossings[0]["upper_edge_id"])
        self.assertEqual(10, crossings[0]["lower_edge_id"])
        self.assertEqual([3, 4], crossings[0]["upper_node_ids"])
        self.assertEqual([1, 2], crossings[0]["lower_node_ids"])
        self.assertEqual([3, 4], python_crossings[0]["upper_node_ids"])
        self.assertEqual([1, 2], python_crossings[0]["lower_node_ids"])
        self.assertAlmostEqual(6, crossings[0]["clearance_m"])
        self.assertEqual("ENGINE_XYZ_TOPOLOGY_DERIVED", crossings[0]["source"])

    def test_real_crossing_four_tenths_from_a_track_seam_is_retained(self):
        nodes = [
            {"entity_id": 1, "position": {"x": -20, "y": 0, "z": 8}},
            {"entity_id": 2, "position": {"x": .4, "y": 0, "z": 8}},
            {"entity_id": 3, "position": {"x": 0, "y": -20, "z": 2}},
            {"entity_id": 4, "position": {"x": 0, "y": 20, "z": 2}},
        ]
        edges = [
            {"entity_id": 10, "node0": 1, "node1": 2},
            {"entity_id": 20, "node0": 3, "node1": 4},
        ]

        crossings = run_detector(nodes, edges)
        python_crossings = detect_grade_separated_crossings(edges, nodes, samples=4)

        self.assertEqual(1, len(crossings))
        self.assertEqual(1, len(python_crossings))
        self.assertAlmostEqual(6, crossings[0]["clearance_m"])

    def test_edges_sharing_a_topology_node_are_not_a_bridge(self):
        nodes = [
            {"entity_id": 1, "position": {"x": -20, "y": 0, "z": 0}},
            {"entity_id": 2, "position": {"x": 0, "y": 0, "z": 0}},
            {"entity_id": 3, "position": {"x": 0, "y": 20, "z": 6}},
        ]
        edges = [
            {"entity_id": 10, "node0": 1, "node1": 2},
            {"entity_id": 20, "node0": 2, "node1": 3},
        ]

        self.assertEqual([], run_detector(nodes, edges))
        self.assertEqual([], detect_grade_separated_crossings(edges, nodes, samples=4))

    def test_disconnected_same_height_crossing_is_not_claimed_as_a_bridge(self):
        nodes = [
            {"entity_id": 1, "position": {"x": -20, "y": 0, "z": 3}},
            {"entity_id": 2, "position": {"x": 20, "y": 0, "z": 3}},
            {"entity_id": 3, "position": {"x": 0, "y": -20, "z": 3}},
            {"entity_id": 4, "position": {"x": 0, "y": 20, "z": 3}},
        ]
        edges = [
            {"entity_id": 10, "node0": 1, "node1": 2},
            {"entity_id": 20, "node0": 3, "node1": 4},
        ]

        self.assertEqual([], run_detector(nodes, edges))
        self.assertEqual([], detect_grade_separated_crossings(edges, nodes, samples=4))


if __name__ == "__main__":
    unittest.main()
