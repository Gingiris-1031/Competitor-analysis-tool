import os
import unittest
from unittest.mock import patch
from modules import insforge_client as client


class DataRoutingTests(unittest.TestCase):
    def test_default_routes_remain_on_insforge(self):
        with patch.dict(os.environ,{'INSFORGE_URL':'https://old.example','INSFORGE_API_KEY':'old'},clear=True):
            self.assertEqual(client._records_url('reports'),'https://old.example/api/database/records/reports')
            self.assertEqual(client._headers(),{'Authorization':'Bearer old'})

    def test_new_data_routes_do_not_change_auth_base(self):
        with patch.dict(os.environ,{'INSFORGE_URL':'https://old.example','SUPABASE_DATA_URL':'https://new.example/','SUPABASE_DATA_SERVICE_KEY':'sb_secret_test'},clear=True):
            self.assertTrue(client.enabled())
            self.assertEqual(client._records_url('reports'),'https://new.example/rest/v1/reports')
            self.assertEqual(client._rpc_url('consume_mcp_credit'),'https://new.example/rest/v1/rpc/consume_mcp_credit')
            self.assertEqual(client._base(),'https://old.example')
            self.assertEqual(client._headers(),{'apikey':'sb_secret_test'})

    def test_partial_data_config_cannot_use_insforge(self):
        with patch.dict(os.environ,{'INSFORGE_URL':'https://old.example','INSFORGE_API_KEY':'old','SUPABASE_DATA_URL':'https://new.example'},clear=True):
            self.assertFalse(client.enabled())
            with self.assertRaises(RuntimeError):client._records_url('reports')
            with self.assertRaises(RuntimeError):client._headers()

    def test_legacy_service_jwt_has_both_headers(self):
        with patch.dict(os.environ,{'SUPABASE_DATA_URL':'https://new.example','SUPABASE_DATA_SERVICE_KEY':'jwt-test'},clear=True):
            headers=client._headers(write=True)
            self.assertEqual(headers['apikey'],'jwt-test')
            self.assertEqual(headers['Authorization'],'Bearer jwt-test')
            self.assertEqual(headers['Prefer'],'return=representation')


if __name__=='__main__':unittest.main()
