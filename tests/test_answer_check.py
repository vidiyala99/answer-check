"""Tests for answer_check. A tiny fake SDK tree is written to a temp dir; no real SDK code is imported or run."""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE.parent
sys.path.insert(0, str(BUILD))

from answer_check.sigindex import build_index  # noqa: E402
from answer_check.check import check_answer  # noqa: E402

FAKE_CLIENT = '''
import functools
from .users._resource import Users
from .vault._resource import Vault

class WorkOSClient(_SyncBase):
    @functools.cached_property
    def users(self) -> Users:
        return Users(self)

    @functools.cached_property
    def vault(self) -> Vault:
        return Vault(self)

class AsyncWorkOSClient(_AsyncBase):
    @functools.cached_property
    def users(self) -> AsyncUsers:
        return AsyncUsers(self)
'''

FAKE_USERS = '''
class _SessionMixin:
    def load_sealed_session(self, *, session_data: str, cookie_password: str):
        ...

class Users(_SessionMixin):
    def get_user(self, id: str, *, request_options=None):
        ...

    def list_users(self, *, limit: int | None = None, organization_id: str | None = None):
        ...

    def create_user(self, *, email: str, first_name: str | None = None):
        ...

    def _private(self, x):
        ...

class AsyncUsers:
    async def get_user(self, id: str):
        ...
'''

FAKE_VAULT = '''
class Vault:
    def get_kv(self, id: str, *, request_options=None):
        ...

    def anything(self, **kwargs):
        ...

    def list_kv(self, *, type: str | None = None, types_: list | None = None):
        ...
'''


def make_sdk(root: Path) -> Path:
    src = root / 'workos'
    (src / 'users').mkdir(parents=True)
    (src / 'vault').mkdir(parents=True)
    (src / '_client.py').write_text(FAKE_CLIENT, encoding='utf-8')
    (src / 'users' / '_resource.py').write_text(FAKE_USERS, encoding='utf-8')
    (src / 'vault' / '_resource.py').write_text(FAKE_VAULT, encoding='utf-8')
    (src / 'broken.py').write_text('def oops(:\n', encoding='utf-8')  # unparsable file must not crash indexing
    return src


def answer(code: str, lang: str = 'python') -> str:
    return f'Here is how:\n\n```{lang}\n{textwrap.dedent(code).strip()}\n```\n\nDone.'


class IndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.index = build_index(make_sdk(Path(cls.tmp.name)), version='0.0.1')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_accessors_map_to_resource_classes(self):
        self.assertEqual(self.index['clients']['WorkOSClient'], {'users': 'Users', 'vault': 'Vault'})
        self.assertEqual(self.index['clients']['AsyncWorkOSClient'], {'users': 'AsyncUsers'})

    def test_signature_shape(self):
        sig = self.index['classes']['Users']['methods']['create_user']
        self.assertEqual(sig['positional'], [])
        self.assertEqual(sig['keyword_only'], ['email', 'first_name'])
        self.assertEqual(sig['required'], ['email'])
        self.assertFalse(sig['varkw'])

    def test_positional_required_and_self_dropped(self):
        sig = self.index['classes']['Users']['methods']['get_user']
        self.assertEqual(sig['positional'], ['id'])
        self.assertEqual(sig['required'], ['id'])

    def test_private_methods_skipped_and_bases_kept(self):
        users = self.index['classes']['Users']
        self.assertNotIn('_private', users['methods'])
        self.assertEqual(users['bases'], ['_SessionMixin'])

    def test_version_recorded(self):
        self.assertEqual(self.index['sdk_version'], '0.0.1')


class CheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.index = build_index(make_sdk(Path(cls.tmp.name)), version='0.0.1')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def verdicts(self, text):
        return [(c['call'], c['verdict']) for c in check_answer(text, self.index)['calls']]

    def test_correct_call_is_ok(self):
        r = check_answer(answer('''
            from workos import WorkOSClient
            client = WorkOSClient()
            user = client.users.get_user(id="user_1")
        '''), self.index)
        self.assertEqual([(c['call'], c['verdict']) for c in r['calls']], [('users.get_user', 'ok')])
        self.assertTrue(r['ok'])

    def test_planted_id_underscore_is_wrong_arg_with_fix(self):
        r = check_answer(answer('client = WorkOSClient()\nclient.vault.get_kv(id_="kv_1")'), self.index)
        call = r['calls'][0]
        self.assertEqual(call['verdict'], 'wrong-arg')
        self.assertFalse(r['ok'])
        self.assertIn({'kind': 'unknown-keyword', 'keyword': 'id_', 'suggest': 'id'}, call['problems'])
        self.assertIn('get_kv', call['hint'])
        self.assertIn('id', call['hint'])

    def test_trailing_underscore_prefers_stripped_name_over_closer_fuzzy_match(self):
        r = check_answer(answer('client = WorkOSClient()\nclient.vault.list_kv(type_="x")'), self.index)
        self.assertIn({'kind': 'unknown-keyword', 'keyword': 'type_', 'suggest': 'type'}, r['calls'][0]['problems'])

    def test_invented_name_gets_closest_suggestion(self):
        r = check_answer(answer('client = WorkOSClient()\nclient.users.get_user(user_id="u")'), self.index)
        probs = r['calls'][0]['problems']
        self.assertEqual(r['calls'][0]['verdict'], 'wrong-arg')
        self.assertIn('user_id', [p.get('keyword') for p in probs])

    def test_inherited_method_found_through_bases(self):
        bad = check_answer(answer(
            'client = WorkOSClient()\n'
            'client.users.load_sealed_session(sealed_session="c", cookie_password="p")'), self.index)
        self.assertEqual(bad['calls'][0]['verdict'], 'wrong-arg')
        good = check_answer(answer(
            'client = WorkOSClient()\n'
            'client.users.load_sealed_session(session_data="c", cookie_password="p")'), self.index)
        self.assertEqual(good['calls'][0]['verdict'], 'ok')

    def test_missing_required_keyword(self):
        r = check_answer(answer('client = WorkOSClient()\nclient.users.create_user(first_name="A")'), self.index)
        self.assertEqual(r['calls'][0]['verdict'], 'wrong-arg')
        self.assertIn({'kind': 'missing-required', 'param': 'email'}, r['calls'][0]['problems'])

    def test_missing_required_positional_counts_positional_args(self):
        ok = check_answer(answer('client = WorkOSClient()\nclient.users.get_user("user_1")'), self.index)
        self.assertEqual(ok['calls'][0]['verdict'], 'ok')
        bad = check_answer(answer('client = WorkOSClient()\nclient.users.get_user()'), self.index)
        self.assertIn({'kind': 'missing-required', 'param': 'id'}, bad['calls'][0]['problems'])

    def test_too_many_positional(self):
        r = check_answer(answer('client = WorkOSClient()\nclient.users.get_user("a", "b")'), self.index)
        self.assertIn({'kind': 'too-many-positional', 'given': 2, 'allowed': 1}, r['calls'][0]['problems'])

    def test_keyword_only_passed_positionally(self):
        r = check_answer(answer('client = WorkOSClient()\nclient.users.create_user("a@b.c")'), self.index)
        self.assertEqual(r['calls'][0]['verdict'], 'wrong-arg')

    def test_unknown_method(self):
        r = check_answer(answer('client = WorkOSClient()\nclient.users.get_usr(id="u")'), self.index)
        c = r['calls'][0]
        self.assertEqual(c['verdict'], 'unknown-method')
        self.assertIn('get_user', c['hint'])

    def test_unknown_accessor(self):
        r = check_answer(answer('client = WorkOSClient()\nclient.userz.get_user(id="u")'), self.index)
        self.assertEqual(r['calls'][0]['verdict'], 'unknown-method')

    def test_unknown_accessor_points_to_resource_that_has_the_method(self):
        # Docs called client.organizations_data_providers.X while X lives on client.pipes: the fuzzy accessor
        # match ("organization_domains") was wrong; the method's real home is the useful hint.
        r = check_answer(answer('client = WorkOSClient()\nclient.secrets.get_kv(id="k")'), self.index)
        c = r['calls'][0]
        self.assertEqual(c['verdict'], 'unknown-method')
        self.assertEqual(c['problems'][0]['suggest'], 'vault')
        self.assertIn('client.vault.get_kv', c['hint'])

    def test_unknown_accessor_and_method_nowhere_makes_no_accessor_guess(self):
        r = check_answer(answer('client = WorkOSClient()\nclient.vaults.no_such_call(id="k")'), self.index)
        c = r['calls'][0]
        self.assertEqual(c['verdict'], 'unknown-method')
        self.assertIsNone(c['problems'][0]['suggest'])
        self.assertIn('no resource on the client has `no_such_call`', c['hint'])

    def test_method_on_wrong_known_accessor_points_to_its_home(self):
        r = check_answer(answer('client = WorkOSClient()\nclient.users.get_kv(id="k")'), self.index)
        c = r['calls'][0]
        self.assertEqual(c['verdict'], 'unknown-method')
        self.assertIn('client.vault.get_kv', c['hint'])

    def test_varkw_method_accepts_anything(self):
        r = check_answer(answer('client = WorkOSClient()\nclient.vault.anything(foo=1)'), self.index)
        self.assertEqual(r['calls'][0]['verdict'], 'ok')

    def test_double_star_splat_is_not_checked(self):
        r = check_answer(answer('client = WorkOSClient()\nargs = {}\nclient.users.create_user(**args)'), self.index)
        self.assertEqual(r['calls'][0]['verdict'], 'not-checked')

    def test_client_name_from_assignment_and_accessor_alias(self):
        r = check_answer(answer('''
            wos = WorkOSClient(api_key="k")
            um = wos.users
            um.get_user(id_="u")
        '''), self.index)
        self.assertEqual([(c['call'], c['verdict']) for c in r['calls']], [('users.get_user', 'wrong-arg')])

    def test_default_client_names_without_constructor(self):
        r = check_answer(answer('workos.users.get_user(id="u")'), self.index)
        self.assertEqual(r['calls'][0]['verdict'], 'ok')

    def test_async_client_uses_async_accessors(self):
        r = check_answer(answer('c = AsyncWorkOSClient()\nawait c.users.get_user(id="u")'), self.index)
        self.assertEqual(r['calls'][0]['verdict'], 'ok')

    def test_unrelated_calls_ignored(self):
        r = check_answer(answer('import os\nos.environ.get("X")\nprint("hi")\nrequest.cookies.get("a")'), self.index)
        self.assertEqual(r['calls'], [])
        self.assertTrue(r['ok'])

    def test_non_python_blocks_ignored_and_py_alias_read(self):
        self.assertEqual(check_answer(answer('client.vault.get_kv(id_="x")', 'ts'), self.index)['calls'], [])
        r = check_answer(answer('client = WorkOSClient()\nclient.vault.get_kv(id_="x")', 'py'), self.index)
        self.assertEqual(r['calls'][0]['verdict'], 'wrong-arg')

    def test_unparsable_block_reported_not_crashed(self):
        r = check_answer(answer('client.vault.get_kv(id_="x"\n'), self.index)
        self.assertEqual(r['calls'], [])
        self.assertEqual(r['blocks'][0]['status'], 'syntax-error')
        self.assertTrue(r['ok'])

    def test_line_numbers_are_within_block(self):
        r = check_answer(answer('client = WorkOSClient()\n\nclient.vault.get_kv(id_="x")'), self.index)
        self.assertEqual(r['calls'][0]['line'], 3)
        self.assertEqual(r['calls'][0]['block'], 0)

    def test_multiple_blocks_and_calls(self):
        text = answer('client = WorkOSClient()\nclient.users.get_user(id="u")') + '\n' + \
            answer('client = WorkOSClient()\nclient.vault.get_kv(id_="k")')
        r = check_answer(text, self.index)
        self.assertEqual([c['verdict'] for c in r['calls']], ['ok', 'wrong-arg'])
        self.assertEqual([c['block'] for c in r['calls']], [0, 1])

    def test_signature_reported(self):
        r = check_answer(answer('client = WorkOSClient()\nclient.vault.get_kv(id_="k")'), self.index)
        self.assertEqual(r['calls'][0]['signature'], 'get_kv(id, *, request_options=None)')


class CliTests(unittest.TestCase):
    def test_index_then_check_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            src = make_sdk(d)
            idx = d / 'index.json'
            env = {**os.environ, 'PYTHONPATH': str(BUILD)}
            subprocess.run([sys.executable, '-m', 'answer_check', 'index', str(src), '--version', '0.0.1',
                            '-o', str(idx)], check=True, env=env, cwd=BUILD)
            bad = d / 'bad.md'
            bad.write_text(answer('client = WorkOSClient()\nclient.vault.get_kv(id_="k")'), encoding='utf-8')
            good = d / 'good.md'
            good.write_text(answer('client = WorkOSClient()\nclient.vault.get_kv(id="k")'), encoding='utf-8')
            r_bad = subprocess.run([sys.executable, '-m', 'answer_check', 'check', '--index', str(idx), str(bad)],
                                   capture_output=True, text=True, env=env, cwd=BUILD)
            r_good = subprocess.run([sys.executable, '-m', 'answer_check', 'check', '--index', str(idx), str(good)],
                                    capture_output=True, text=True, env=env, cwd=BUILD)
            self.assertEqual(r_bad.returncode, 1)
            self.assertEqual(r_good.returncode, 0)
            self.assertEqual(json.loads(r_bad.stdout)['calls'][0]['verdict'], 'wrong-arg')

    def test_check_reads_saved_bot_answer_json(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            src = make_sdk(d)
            idx = d / 'index.json'
            env = {**os.environ, 'PYTHONPATH': str(BUILD)}
            subprocess.run([sys.executable, '-m', 'answer_check', 'index', str(src), '-o', str(idx)],
                           check=True, env=env, cwd=BUILD)
            saved = d / 'q.json'
            saved.write_text(json.dumps({'question': 'q', 'answer': answer(
                'client = WorkOSClient()\nclient.vault.get_kv(id_="k")')}), encoding='utf-8')
            r = subprocess.run([sys.executable, '-m', 'answer_check', 'check', '--index', str(idx), str(saved)],
                               capture_output=True, text=True, env=env, cwd=BUILD)
            self.assertEqual(r.returncode, 1)


if __name__ == '__main__':
    unittest.main()
