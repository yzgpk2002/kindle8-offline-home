import json,tempfile,unittest,sys,time,threading
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent.parent/'src'/'app'))
from text_chat import TextChat,NoRedirect,URL

class TextTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name)/'config.json';self.chat=TextChat(self.p)
    def tearDown(self):self.tmp.cleanup()
    def config(self):
        self.p.write_text(json.dumps({'api_key':'test-only-secret','model':'deepseek-flash'}));self.p.chmod(0o600)
    def wait(self):
        for _ in range(100):
            if not self.chat.status()['busy']:return
            time.sleep(.01)
        self.fail('worker did not finish')
    def test_no_key_no_network(self):
        with patch('urllib.request.build_opener') as op:
            with self.assertRaises(ValueError):self.chat.send('hello')
            op.assert_not_called()
        self.assertFalse(self.chat.status()['configured'])
    def test_reply_and_secret_isolation(self):
        self.config()
        with patch('urllib.request.build_opener') as op:
            op.return_value.open.return_value.__enter__.return_value.read.return_value=json.dumps({'choices':[{'message':{'content':'answer'}}]}).encode()
            self.chat.send('question');self.wait()
            req=op.return_value.open.call_args.args[0]
            self.assertEqual(req.full_url,URL)
            self.assertFalse(json.loads(req.data)['stream'])
        s=self.chat.status();self.assertEqual(s['messages'][-1]['content'],'answer')
        self.assertNotIn('test-only-secret',json.dumps(s))
    def test_clear_discards_late_reply_and_no_duplicate(self):
        self.config();gate=threading.Event()
        with patch('urllib.request.build_opener') as op:
            def read(n):gate.wait(2);return b'{"choices":[{"message":{"content":"late"}}]}'
            op.return_value.open.return_value.__enter__.return_value.read.side_effect=read
            self.chat.send('question');self.chat.clear()
            with self.assertRaises(ValueError):self.chat.send('duplicate')
            gate.set();self.wait()
        self.assertEqual(self.chat.status()['messages'],[])
    def test_redirect_not_followed(self):self.assertIsNone(NoRedirect().redirect_request(None,None,None,None,None,None))

if __name__=='__main__':unittest.main()
