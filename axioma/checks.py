"""Code floors and bounded read-only preflights. Configuration is operator-owned."""
from fnmatch import fnmatchcase
import json
import os
from pathlib import Path
import re


def norm(value):
    """Match host normalization: Kanban/profile names and providers are stripped + lowercased."""
    return value.strip().lower() if isinstance(value, str) else None


def _ok(fn):
    try:
        fn()
        return True
    except Exception:
        return False


def lock_free(path):
    """Fail CLOSED: only a definite 'does not exist' counts as available.

    Path.exists() on Python 3.14 swallows PermissionError into False, so use lstat directly.
    """
    try:
        os.lstat(path)
    except FileNotFoundError:
        return True
    except Exception:
        return False  # unreadable/unknown => not available
    return False


def secret_present(name):
    # Hermes scopes the credential; never read .env/auth files or return the value.
    from agent.secret_scope import get_secret
    return bool(get_secret(name))


class Checks:
    def __init__(self, config, secret_present=secret_present):
        if not isinstance(config, dict) or set(config) - {'deny', 'non_reversible', 'skills', 'provider_conflicts', 'locks', 'senders'}:
            raise ValueError('invalid checks configuration')
        self.config, self.secret_present = config, secret_present
        self.red_rules = []
        for kind in ('deny', 'non_reversible'):
            rules = config.get(kind, [])
            if not isinstance(rules, list):
                raise ValueError('red rules must be lists')
            for r in rules:
                if not isinstance(r, dict) or set(r) != {'tool', 'pattern'} or not all(isinstance(v, str) for v in r.values()):
                    raise ValueError('red rule needs tool and pattern')
                self.red_rules.append((r['tool'], re.compile(r['pattern']), kind))
        senders = config.get('senders', {})
        if not isinstance(senders, dict) or not all(isinstance(k, str) and isinstance(v, bool) for k, v in senders.items()):
            raise ValueError('senders must map identities to boolean send rights')
        self.senders = {norm(k): v for k, v in senders.items()}
        skills = config.get('skills', {})
        if not isinstance(skills, dict) or not all(isinstance(k, str) and norm(k) for k in skills):
            raise ValueError('skills must map nonempty profile names to rules')
        self.skills = {norm(k): v for k, v in skills.items()}
        for profile, r in skills.items():
            if not isinstance(r, dict) or set(r) != {'root', 'required'} or not isinstance(r['required'], list):
                raise ValueError('skills requires root and required list')
            if not isinstance(r['root'], str) or not Path(r['root']).is_absolute():
                raise ValueError('skills root must be absolute')
            if not all(isinstance(s, str) and re.fullmatch(r'[a-zA-Z0-9_-]+', s) for s in r['required']):
                raise ValueError('invalid skill identifier')
        for kind in ('provider_conflicts', 'locks'):
            if not isinstance(config.get(kind, []), list):
                raise ValueError(kind + ' must be a list')
        for r in config.get('provider_conflicts', []):
            if not isinstance(r, dict) or set(r) != {'provider', 'key_envs'} or not isinstance(r['provider'], str):
                raise ValueError('invalid provider conflict')
            if not isinstance(r['key_envs'], list) or not all(isinstance(n, str) and re.fullmatch(r'[A-Z][A-Z0-9_]*', n) for n in r['key_envs']):
                raise ValueError('invalid credential name')
        for r in config.get('locks', []):
            if not isinstance(r, dict) or set(r) != {'tool', 'path'} or not isinstance(r['tool'], str):
                raise ValueError('invalid lock check')
            if not isinstance(r['path'], str) or not Path(r['path']).is_absolute():
                raise ValueError('lock path must be absolute')

    @classmethod
    def lenient(cls, config, **kwargs):
        """(checks, had_error). On a bad config keep every rule that is valid on its own,
        so one typo never silently drops the operator's other deny/non_reversible rules."""
        try:
            return cls(config, **kwargs), False
        except Exception:
            pass
        clean = {}
        if isinstance(config, dict):
            for kind in ('deny', 'non_reversible', 'provider_conflicts', 'locks'):
                if isinstance(config.get(kind), list):
                    clean[kind] = [r for r in config[kind] if _ok(lambda: cls({kind: [r]}))]
            for kind in ('senders', 'skills'):
                if isinstance(config.get(kind), dict):
                    clean[kind] = {k: v for k, v in config[kind].items() if _ok(lambda: cls({kind: {k: v}}))}
        try:
            return cls(clean, **kwargs), True
        except Exception:
            return cls({}, **kwargs), True

    def hard_red(self, tool, args):
        payload = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
        return any(fnmatchcase(tool, pattern) and regex.search(payload) for pattern, regex, kind in self.red_rules)

    def apply(self, tool, args, card, categories=()):
        """Return (adjusted card, check results). `categories` comes from Policy.classify."""
        card, results = dict(card), []
        if self.hard_red(tool, args):
            results.append({'check': 'standing_rule', 'pass': False})
        affects = card.get('affects', [])
        affects = [affects] if isinstance(affects, str) else affects
        # Letters-only boundaries, so all_users / my_clients / public_followers count too.
        downstream = any(re.search(r'(?<![a-z])(?:end[ _-]?users?|public|clients?|customers?|users?|'
                                   r'subscribers?|followers?|everyone|patients?|members?|audiences?|'
                                   r'students?|buyers?|leads?)(?![a-z])', x, re.I)
                         for x in affects)
        if not affects:
            results.append({'check': 'downstream_declared', 'pass': False})
        if downstream and not card.get('told', False):
            results.append({'check': 'downstream_informed', 'pass': False})
        senders = self.config.get('senders', {})
        # Keyed on the configured SEND category, not on tool-name substrings.
        if senders and 'send' in categories:
            # Every sender-identity field present must have send rights; none present = fail.
            given = [args.get(k) for k in ('sender', 'from', 'from_address') if args.get(k) is not None]
            # A terminal command (git push, gh pr create) has no sender identity to check.
            if given or tool != 'terminal':
                good = bool(given) and all(isinstance(s, str) and self.senders.get(s.strip().lower()) is True
                                           for s in given)
                results.append({'check': 'sender_rights', 'pass': good})
        if tool in ('kanban_create', 'delegate_task'):
            tasks = args.get('tasks') if isinstance(args.get('tasks'), list) else [args]
            for task in tasks:
                if not isinstance(task, dict):
                    continue
                profile = norm(task.get('assignee') or task.get('profile'))
                rule = self.skills.get(profile)
                if rule:
                    try:
                        good = all((Path(rule['root']) / s / 'SKILL.md').is_file() for s in rule['required'])
                    except OSError:
                        good = False  # inaccessible metadata is a failed preflight, not unavailable advice
                    results.append({'check': 'skills', 'pass': good})
        providers = {norm(args.get('provider'))}
        if isinstance(args.get('tasks'), list):
            providers |= {norm(t.get('provider')) for t in args['tasks'] if isinstance(t, dict)}
        for rule in self.config.get('provider_conflicts', []):
            if norm(rule['provider']) in providers:
                try:
                    good = not any(self.secret_present(n) for n in rule['key_envs'])
                except Exception:
                    good = False
                results.append({'check': 'provider_credentials', 'pass': good})
        for rule in self.config.get('locks', []):
            if fnmatchcase(tool, rule['tool']):
                results.append({'check': 'device_lock', 'pass': lock_free(rule['path'])})
        failed_preflight = [r for r in results if not r['pass'] and not r['check'].startswith('downstream_')]
        if failed_preflight:
            card['light'] = 'red'
            names = sorted({r['check'] for r in failed_preflight} - {'standing_rule'})
            parts = []
            if any(r['check'] == 'standing_rule' for r in failed_preflight):
                parts.append('A standing rule or non-reversible identity change forbids this action')
            if names:
                parts.append('preflight failed (' + ', '.join(names) + ')')
            card['signal'] = ', and '.join(parts) + '; revise the target or fix the check before re-review.'
            card['signal'] = card['signal'][0].upper() + card['signal'][1:]
        elif card['light'] == 'green' and any(not r['pass'] for r in results):
            card['light'] = 'yellow'
        return card, results
