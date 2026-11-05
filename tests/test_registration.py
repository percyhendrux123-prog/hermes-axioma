import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class RegistrationTests(unittest.TestCase):
    def test_registers_only_declared_surfaces(self):
        self.assertTrue((ROOT / '__init__.py').is_file(), 'plugin entrypoint missing')
        spec = importlib.util.spec_from_file_location('axioma_plugin', ROOT / '__init__.py',
                                                    submodule_search_locations=[str(ROOT)])
        module = importlib.util.module_from_spec(spec)
        sys.modules['axioma_plugin'] = module
        spec.loader.exec_module(module)
        class Context:
            def __init__(self):
                self.hooks, self.tools, self.middleware, self.commands = {}, {}, {}, {}
            def get_config(self, key, default=None):
                return default
            def register_hook(self, key, fn):
                self.hooks[key] = fn
            def register_tool(self, **kw):
                self.tools[kw['name']] = kw
            def register_middleware(self, key, fn):
                self.middleware[key] = fn
            def register_command(self, key, fn, **kw):
                self.commands[key] = fn
        with tempfile.TemporaryDirectory() as tmp:
            ctx = Context()
            with patch.object(module, 'data_root', return_value=Path(tmp)):
                module.register(ctx)
            self.assertEqual(set(ctx.tools), {'axioma_card'})
            self.assertFalse(ctx.tools['axioma_card'].get('override', False))
            self.assertEqual(set(ctx.hooks), {'pre_tool_call', 'post_tool_call', 'post_approval_response',
                                               'pre_llm_call', 'on_session_finalize', 'transform_llm_output'})
            self.assertEqual(set(ctx.middleware), set(), 'advisor registers no execution middleware')
            self.assertEqual(set(ctx.commands), {'signals', 'whispers'})
            guidance = ctx.hooks['pre_llm_call']()['context']
            self.assertIn('[signal:stop', guidance)
            self.assertIn('best-effort', guidance)
            out = ctx.hooks['transform_llm_output']('Do [signal:stop;why=x]this[/signal]?', session_id='s',
                                                     platform='telegram')
            self.assertEqual(out, 'Do **this** (stop)?')
            self.assertIn('axioma_card', ctx.hooks['pre_llm_call']()['context'])
            self.assertIsNone(ctx.hooks['transform_llm_output']('A', session_id='s', platform='cli'))


class Pass16Wording(unittest.TestCase):
    def test_tool_and_card_text_say_what_scrub_does_not_see(self):
        import importlib.util
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('axioma_init_p16', root / '__init__.py',
                                                      submodule_search_locations=[str(root)])
        text = (root / '__init__.py').read_text()
        for needle in ('bash -c', 'eval', 'ssh', 'not seen'):
            self.assertIn(needle, text)


if __name__ == '__main__':
    unittest.main()
