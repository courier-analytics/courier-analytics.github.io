import io,json,sys,unittest,urllib.error
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from late_bot_group import api
class Idempotent(unittest.TestCase):
 def test_identical_edit_is_success_but_failed_send_is_not(self):
  for method in ['editMessageText','editMessageReplyMarkup','sendMessage']:
   error=urllib.error.HTTPError('https://example.invalid',400,'bad',{},io.BytesIO(json.dumps({'description':'Bad Request: message is not modified: specified content is identical'}).encode()))
   with patch('late_bot_group.urllib.request.build_opener',return_value=Mock(open=Mock(side_effect=error))):
    if method=='sendMessage':
     with self.assertRaises(RuntimeError):api('token',method,{})
    else:self.assertEqual(api('token',method,{}),{'not_modified':True})
