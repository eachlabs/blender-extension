import unittest

from eachlabs.shot.price import text, total


class PriceTests(unittest.TestCase):
    def test_total_720p_10s_3_photos(self):
        self.assertEqual(round(total("720p", 10, 3), 3), 3.185)

    def test_text(self):
        self.assertEqual(text(3.185), "$3.19")
        self.assertEqual(text(total("720p", 10, 3)), "$3.19")  # the float sum is 3.18499…
        self.assertEqual([text(total(r, 5, 0)) for r in ("480p", "720p", "1080p")], ["$0.78", "$1.53", "$3.48"])
        self.assertEqual(text(4.0), "$4.00")


if __name__ == "__main__":
    unittest.main()
