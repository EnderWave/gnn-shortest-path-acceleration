from __future__ import annotations

import unittest

from src.compression_index import (
    NODE_BOUNDARY,
    NODE_INTERNAL,
    NODE_OUTSIDE,
    build_compression_index,
)
from src.graph_types import WeightedDiGraph
from src.indexed_query import indexed_bidirectional_dijkstra_distance
from src.regions import Region
from src.shortest_path import bidirectional_dijkstra_distance


class MaterializedCompressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.graph = WeightedDiGraph()
        for node in range(1, 7):
            self.graph.add_node(node)
        for source, target, weight in [
            (1, 2, 1.0),
            (2, 1, 1.0),
            (2, 3, 1.0),
            (3, 2, 1.0),
            (3, 4, 1.0),
            (4, 3, 1.0),
            (4, 5, 1.0),
            (5, 4, 1.0),
            (2, 4, 10.0),
            (5, 6, 1.0),
            (6, 5, 1.0),
        ]:
            self.graph.add_edge(source, target, weight)

        region = Region(
            region_id=0,
            nodes=frozenset({2, 3, 4}),
            boundary_nodes=frozenset({2, 4}),
            seed_node=3,
            selection_method="test",
        )
        self.index = build_compression_index(self.graph, [region])

    def test_materializes_node_states_and_shortcut(self) -> None:
        self.assertEqual(self.index.node_states[1], NODE_OUTSIDE)
        self.assertEqual(self.index.node_states[2], NODE_BOUNDARY)
        self.assertEqual(self.index.node_states[3], NODE_INTERNAL)
        self.assertFalse(self.index.compressed_graph.has_node(3))
        self.assertEqual(self.index.compressed_graph.node_count, 5)
        self.assertIn((4, 2.0), self.index.compressed_graph.out_neighbors(2))
        self.assertNotIn((4, 10.0), self.index.compressed_graph.out_neighbors(2))

    def test_compressed_query_matches_original_graph(self) -> None:
        expected = bidirectional_dijkstra_distance(self.graph, 1, 6)
        actual = indexed_bidirectional_dijkstra_distance(self.graph, self.index, 1, 6)
        self.assertEqual(actual.distance, expected.distance)
        self.assertFalse(self.index.requires_original_graph(1, 6))

    def test_internal_endpoint_falls_back_to_original_graph(self) -> None:
        expected = bidirectional_dijkstra_distance(self.graph, 3, 6)
        actual = indexed_bidirectional_dijkstra_distance(self.graph, self.index, 3, 6)
        self.assertEqual(actual.distance, expected.distance)
        self.assertEqual(actual.expanded_nodes, expected.expanded_nodes)
        self.assertTrue(self.index.requires_original_graph(3, 6))


if __name__ == "__main__":
    unittest.main()
