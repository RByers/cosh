import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import balance_clusters as C  # noqa: E402


class PcaTest(unittest.TestCase):
    def test_jacobi_diagonal_and_known_matrix(self):
        vals, vecs = C.jacobi_eigen([[2.0, 1.0], [1.0, 2.0]])
        self.assertAlmostEqual(vals[0], 3.0, places=9)
        self.assertAlmostEqual(vals[1], 1.0, places=9)
        # The first eigenvector is (1, 1)/sqrt(2), sign fixed positive.
        self.assertAlmostEqual(vecs[0][0], 2 ** -0.5, places=9)
        self.assertAlmostEqual(vecs[0][1], 2 ** -0.5, places=9)

    def test_pca_finds_the_long_axis(self):
        rng = random.Random(1)
        rows = []
        for _ in range(500):
            t = rng.gauss(0, 3)
            rows.append([t, t + rng.gauss(0, 0.1), rng.gauss(0, 0.1)])
        var, comps, mu = C.pca(rows, 2)
        self.assertGreater(var[0], 0.99)
        self.assertAlmostEqual(abs(comps[0][0]), 2 ** -0.5, places=2)
        self.assertAlmostEqual(abs(comps[0][2]), 0.0, places=2)
        # Projection of the mean is the origin.
        self.assertTrue(all(abs(x) < 1e-9 for x in C.project(mu, comps, mu)))


class KmeansTest(unittest.TestCase):
    def blobs(self):
        rng = random.Random(2)
        centres = [(0, 0), (10, 0), (0, 10)]
        rows, truth = [], []
        for i, (x, y) in enumerate(centres):
            for _ in range(100):
                rows.append([x + rng.gauss(0, 0.5), y + rng.gauss(0, 0.5)])
                truth.append(i)
        return rows, truth

    def test_recovers_three_blobs(self):
        rows, truth = self.blobs()
        cents, labels, _ = C.kmeans(rows, 3, seed=4)
        # Each true blob maps to exactly one cluster.
        for t in range(3):
            self.assertEqual(len({l for l, tt in zip(labels, truth) if tt == t}), 1)
        self.assertEqual(len(set(labels)), 3)

    def test_silhouette_prefers_the_true_k(self):
        rows, _ = self.blobs()
        s3 = C.silhouette(rows, C.kmeans(rows, 3, seed=4)[1])
        s6 = C.silhouette(rows, C.kmeans(rows, 6, seed=4)[1])
        self.assertGreater(s3, 0.8)
        self.assertGreater(s3, s6)


class NamesTest(unittest.TestCase):
    def test_names_and_paths(self):
        self.assertEqual(C.name_cluster({"tenure": -1.0, "owner": -1.0}), "newcomers ramping up")
        self.assertEqual(C.name_cluster({"newcomer_approvals": 2.0}), "reviewer-mentors")
        self.assertEqual(C.unique_names(["a", "b", "a"]), ["a (a)", "b", "a (b)"])
        path = [(h, "newcomers ramping up") for h in range(3)] + [(h, "mostly reviewing") for h in range(3, 6)]
        self.assertEqual(C.trajectory(path), "light → reviewer")


if __name__ == "__main__":
    unittest.main()
