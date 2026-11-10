"""Read-only Axiōma board lights, mounted by Hermes under /api/plugins/hermes-axioma.

Hermes owns authentication, profile scope and enabled-plugin consent. No tools or message reads.
"""
import importlib.util
from pathlib import Path
import sqlite3
from fastapi import APIRouter, HTTPException, Response

# The host imports this file standalone, not as part of the agent plugin package.
# Load our own stdlib-only audit module without changing sys.path or importing a live plugin.
_spec = importlib.util.spec_from_file_location('_axioma_board_audit',
                                              Path(__file__).resolve().parents[1] / 'axioma' / 'audit.py')
_audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_audit)
router = APIRouter()


def data_root():
    from plugins.plugin_storage import plugin_data_dir
    return plugin_data_dir('hermes-axioma')


@router.get('/board-lights')
def board_lights(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    try:
        # Resolve at request time so the host's profile scope, not the import scope, owns the read.
        return _audit.Audit(data_root() / 'audit.sqlite3').board_lights()
    except (OSError, sqlite3.Error):
        raise HTTPException(status_code=503, detail='Axiōma board lights are unavailable.') from None
