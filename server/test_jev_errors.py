import json
import socket
import ssl
import unittest
from unittest import mock
import urllib.error

import jev_server as j


class Diagnostics(unittest.TestCase):
    def test_wrapped_network_causes_are_distinguished_without_secret_text(self):
        secret = 'https://host.invalid/private-token?key=do-not-log'
        cases = [
            (urllib.error.URLError(TimeoutError(secret)), 'timeout'),
            (TimeoutError(secret), 'timeout'),
            (urllib.error.URLError(ssl.SSLError(secret)), 'tls'),
            (urllib.error.URLError(socket.gaierror(8, secret)), 'dns'),
            (urllib.error.URLError(secret), 'network'),
            (ValueError(secret), 'invalid_response'),
            (RuntimeError(secret), 'other'),
        ]
        for error, category in cases:
            result = j.jev_error_details(error)
            self.assertEqual(result, {'category': category})
            self.assertNotIn(secret, json.dumps(result))

    def test_http_status_is_retained_but_url_and_message_are_not(self):
        error = urllib.error.HTTPError('https://private-token', 429, 'secret', {}, None)
        self.assertEqual(j.jev_error_details(error), {'category': 'http', 'status': 429})

    def test_routing_and_ask_timeouts_remain_independent(self):
        self.enterContext(mock.patch.object(j, "decision_backend", return_value="jev"))
        with mock.patch.object(j, 'call_jev', return_value={}) as call:
            j.call_jev_routed('fixture', {'task': 'fixture'})
            self.assertEqual(call.call_args.kwargs['timeout'], 10.0)
            j.call_jev_routed('fixture', {}, timeout=j.ASK_TIMEOUT)
            self.assertEqual(call.call_args.kwargs['timeout'], 15.0)


if __name__ == '__main__':
    unittest.main()
