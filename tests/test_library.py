import os
import tempfile
import unittest

from eachlabs import code_check
from eachlabs.library import helpers, store

CODE = '''
# a rounded crate with planks
def crate(name, size, loc):
    m = bpy.data.meshes.new(name)
    o = bpy.data.objects.new(name, m)
    scene.collection.objects.link(o)
    return o

def _tiny(x):
    return x

def short(x): return x

crate("Crate", 1.0, (0, 0, 0))
'''


def allowed(source):
    try:
        code_check.check(source)
        return True
    except code_check.Refused:
        return False


class ExtractTest(unittest.TestCase):
    def test_keeps_public_helpers_of_some_length(self):
        found = helpers.extract(CODE, allowed)
        self.assertEqual([e["name"] for e in found], ["crate"])
        self.assertEqual(found[0]["args"], "name, size, loc")
        self.assertEqual(found[0]["description"], "a rounded crate with planks")

    def test_refused_code_is_not_kept(self):
        bad = "def leak(path):\n    f = open(path)\n    return f.read()\n"
        self.assertEqual(helpers.extract(bad, allowed), [])

    def test_broken_code_gives_nothing(self):
        self.assertEqual(helpers.extract("def x(:\n", allowed), [])


class OfferTest(unittest.TestCase):
    def test_relevant_by_shared_words(self):
        entries = [{"name": "crate", "description": "a rounded crate with planks"},
                   {"name": "tree", "description": "a pine tree with tiers"}]
        self.assertEqual([e["name"] for e in helpers.relevant(entries, "a harbour with crates and nets")], [])
        self.assertEqual([e["name"] for e in helpers.relevant(entries, "stack some crate boxes")], ["crate"])

    def test_prelude_only_for_called_and_undefined(self):
        entries = [{"name": "crate", "source": "def crate():\n    pass"},
                   {"name": "tree", "source": "def tree():\n    pass"}]
        self.assertEqual(helpers.prelude("crate()\n", entries), "def crate():\n    pass")
        self.assertEqual(helpers.prelude("def crate():\n    pass\ncrate()\n", entries), "")
        self.assertEqual(helpers.prelude("x = 1\n", entries), "")


class StoreTest(unittest.TestCase):
    def test_round_trip_newest_wins_and_caps(self):
        folder = tempfile.mkdtemp()
        old = {"name": "crate", "args": "", "source": "def crate(): 1", "description": "old", "hash": "a"}
        new = dict(old, description="new", hash="b")
        store.save(folder, store.merged([old], [new]))
        loaded = store.load(folder)
        self.assertEqual([(e["name"], e["description"]) for e in loaded], [("crate", "new")])
        many = [dict(old, name="h%d" % i) for i in range(store.ENTRIES_MAX + 10)]
        self.assertEqual(len(store.merged([], many)), store.ENTRIES_MAX)

    def test_unreadable_file_is_empty(self):
        folder = tempfile.mkdtemp()
        with open(os.path.join(folder, store.FILE), "w") as fh:
            fh.write("{not json")
        self.assertEqual(store.load(folder), [])


if __name__ == "__main__":
    unittest.main()
