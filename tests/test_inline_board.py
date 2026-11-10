"""0.6.0 regressions. Synthetic data; no live profile, message or tool execution."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def entrypoint():
    spec = importlib.util.spec_from_file_location('axioma_inline_test', ROOT / '__init__.py',
                                                submodule_search_locations=[str(ROOT)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Context:
    surface = ''

    def __init__(self):
        self.hooks = {}

    def session_surface(self):
        return self.surface

    def get_config(self, key, default=None):
        return default

    def register_hook(self, name, handler):
        self.hooks[name] = handler

    def register_tool(self, **kw):
        pass

    def register_command(self, *args, **kw):
        pass


class GuidanceTests(unittest.TestCase):
    def test_inline_instruction_only_on_desktop_and_rechecked_each_turn(self):
        module, ctx = entrypoint(), Context()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(module, 'data_root', return_value=Path(tmp)):
                module.register(ctx)
            for surface in ('desktop', 'telegram', 'cli', 'discord', 'acp', 'dashboard', '', ' Desktop '):
                with self.subTest(surface=surface):
                    ctx.surface = surface
                    text = ctx.hooks['pre_llm_call']()['context']
                    self.assertIn('AXIOMA SIGNAL', text)
                    self.assertEqual('::axioma{' in text, surface.strip().lower() == 'desktop')
                    if surface.strip().lower() == 'desktop':
                        self.assertIn('MAY', text)
                        self.assertIn('stop or caution', text)
                        self.assertIn('never permission', text)

    def test_missing_or_failing_surface_does_not_advertise_inline_cards(self):
        module, ctx = entrypoint(), Context()
        ctx.session_surface = lambda: (_ for _ in ()).throw(RuntimeError('synthetic'))
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(module, 'data_root', return_value=Path(tmp)):
                module.register(ctx)
            self.assertNotIn('::axioma{', ctx.hooks['pre_llm_call']()['context'])
