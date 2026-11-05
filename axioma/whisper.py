"""Compatibility name. WHISPER is now one level of the inline signal renderer (axioma/signal.py)."""
from .signal import EMPTY, REASONS, Signal as Whisper

__all__ = ['EMPTY', 'REASONS', 'Whisper']
