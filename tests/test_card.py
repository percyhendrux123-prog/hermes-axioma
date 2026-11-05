import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CARD = dict(intent='Share the synthetic draft', light='yellow',
            signal='The public post cannot be recalled.', question='Is this the audience you intended?')


class CardTests(unittest.TestCase):
    def test_validates_and_rejects_malformed_cards(self):
        self.assertTrue((ROOT / 'axioma' / 'card.py').is_file(), 'card module missing')
        from axioma.card import validate_card
        self.assertEqual(validate_card(CARD), CARD)
        for c in [None, {}, {**CARD, 'light': 'GO'}, {**CARD, 'intent': ''},
                  {**CARD, 'question': 'Do it'}, {**CARD, 'question': 'Why? Who?'},
                  {**CARD, 'signal': 'First. Second.'}, {**CARD, 'signal': 'escape\x1b[31m'},
                  {**CARD, 'extra': 'not allowed'}, {**CARD, 'intent': 'x' * 401}]:
            with self.subTest(card=c), self.assertRaises(ValueError):
                validate_card(c)

    def test_card_ends_on_question_red_never_yes(self):
        from axioma.card import render_card
        for light, word, rgb in [('red', 'STOP', '255;69;58'),
                                  ('yellow', 'CAUTION', '255;204;0'), ('green', 'GO', '48;209;88')]:
            card = {**CARD, 'light': light}
            plain = render_card(card)
            self.assertIn(word, plain)
            self.assertEqual(plain.splitlines()[1], CARD['question'])
            self.assertTrue(plain.splitlines()[0].startswith(word))
            self.assertNotIn('\x1b', plain)
            self.assertIn('proceed: no' if light == 'red' else 'proceed: yes / no', plain)
            if light == 'red':
                self.assertNotIn('yes', plain)
            colored = render_card(card, color=True)
            self.assertIn('\x1b[38;2;' + rgb + 'm', colored)
            self.assertIn('\x1b[38;2;255;255;255m', colored)


if __name__ == '__main__':
    unittest.main()
