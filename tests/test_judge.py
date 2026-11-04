import unittest

from eachlabs.chat import judge


class Judge(unittest.TestCase):
    def test_messages_label_both_versions(self):
        sent = judge.messages("a cosy cabin", "Cabin", ["data:a1", "data:a2"], ["data:b1"])
        parts = sent[1]["content"]
        texts = [p["text"] for p in parts if p["type"] == "text"]
        self.assertIn('"Cabin"', texts[0])
        self.assertEqual(texts[1:], ["Version A:", "Version B:"])
        self.assertEqual([p["image_url"]["url"] for p in parts if p["type"] == "image_url"],
                         ["data:a1", "data:a2", "data:b1"])

    def test_verdict(self):
        self.assertEqual(judge.verdict("B. The logs and the chimney read clearly."),
                         ("B", "The logs and the chimney read clearly"))
        self.assertEqual(judge.verdict("A"), ("A", ""))
        self.assertEqual(judge.verdict("**A** — fuller detail"), ("A", "** — fuller detail"))
        self.assertEqual(judge.verdict("Both are fine"), (None, ""))
        self.assertEqual(judge.verdict(""), (None, ""))


if __name__ == "__main__":
    unittest.main()
