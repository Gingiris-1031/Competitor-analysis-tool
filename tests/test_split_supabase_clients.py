import os
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from modules import supabase_client as sc


def query_client(results):
    client=Mock()
    query=client.table.return_value
    for method in ['select','eq','limit','upsert']:
        getattr(query,method).return_value=query
    query.execute.side_effect=[SimpleNamespace(data=r) for r in results]
    return client,query


class SplitClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{
            'SUPABASE_URL':'https://legacy.example','SUPABASE_SERVICE_KEY':'old-key',
            'SUPABASE_DATA_URL':'https://target.example','SUPABASE_DATA_SERVICE_KEY':'new-key',
        },clear=True)
        self.env.start();self.addCleanup(self.env.stop)
        sc._client=None;sc._auth_client=None
        self.addCleanup(self.reset)

    def reset(self):
        sc._client=None;sc._auth_client=None

    def test_auth_and_data_use_separate_projects(self):
        factory=Mock(side_effect=lambda url,key:SimpleNamespace(url=url))
        with patch.dict(sys.modules,{'supabase':SimpleNamespace(create_client=factory)}):
            self.assertEqual(sc.get_supabase().url,'https://target.example')
            self.assertEqual(sc.get_auth_supabase().url,'https://legacy.example')

    def test_partial_data_config_never_falls_back(self):
        os.environ.pop('SUPABASE_DATA_SERVICE_KEY')
        self.assertIsNone(sc.get_supabase())
        self.assertTrue(sc.supabase_required())

    def test_default_still_uses_one_legacy_client(self):
        os.environ.pop('SUPABASE_DATA_URL');os.environ.pop('SUPABASE_DATA_SERVICE_KEY')
        factory=Mock(return_value=object())
        with patch.dict(sys.modules,{'supabase':SimpleNamespace(create_client=factory)}):
            self.assertIs(sc.get_supabase(),sc.get_auth_supabase())
            factory.assert_called_once_with('https://legacy.example','old-key')

    async def test_token_is_verified_only_by_legacy_auth(self):
        auth=Mock();auth.auth.get_user.return_value=SimpleNamespace(user=SimpleNamespace(id='user',email='a@example.com'))
        with patch.object(sc,'get_auth_supabase',return_value=auth),patch.object(sc,'get_supabase') as data:
            user=await sc.verify_token_and_get_user('jwt')
            self.assertEqual(user['id'],'user');data.assert_not_called()

    def test_existing_balance_is_never_replaced(self):
        target,q=query_client([[{'id':'user'}]])
        source=Mock()
        with patch.object(sc,'get_supabase',return_value=target),patch.object(sc,'get_auth_supabase',return_value=source):
            self.assertTrue(sc.ensure_data_profile('user'))
            q.upsert.assert_not_called();source.table.assert_not_called()

    def test_new_profile_keeps_id_and_ignores_concurrent_insert(self):
        target,q=query_client([[],[],[{'id':'user'}]])
        source,_=query_client([[{'id':'user','credits_balance':2}]])
        with patch.object(sc,'get_supabase',return_value=target),patch.object(sc,'get_auth_supabase',return_value=source):
            self.assertTrue(sc.ensure_data_profile('user'))
            q.upsert.assert_called_once_with({'id':'user','credits_balance':2},on_conflict='id',ignore_duplicates=True)

    def test_wrong_source_identity_is_rejected(self):
        target,q=query_client([[]]);source,_=query_client([[{'id':'other'}]])
        with patch.object(sc,'get_supabase',return_value=target),patch.object(sc,'get_auth_supabase',return_value=source):
            self.assertFalse(sc.ensure_data_profile('user'));q.upsert.assert_not_called()

    async def test_misconfigured_backend_never_gives_free_credit(self):
        os.environ.pop('SUPABASE_DATA_SERVICE_KEY')
        self.assertFalse(await sc.deduct_credit('user'))

    def test_payment_can_find_new_legacy_signup(self):
        target,_=query_client([[]]);source,_=query_client([[{'id':'user'}]])
        with patch.object(sc,'get_supabase',return_value=target),patch.object(sc,'get_auth_supabase',return_value=source),patch.object(sc,'ensure_data_profile',return_value=True) as ensure:
            self.assertEqual(sc.find_data_user_by_email('a@example.com'),'user');ensure.assert_called_once_with('user')


if __name__=='__main__':unittest.main()
