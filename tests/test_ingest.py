import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from sync import parse_price,parse_promos
class IngestTest(unittest.TestCase):
 def test_identity(self):
  with self.assertRaises(ValueError):parse_price(b'<Root><ChainID>wrong</ChainID><StoreID>1</StoreID></Root>',{'chainId':'7290027600007','code':'1'},{'file':'x','publishedAt':'now'})
 def test_decimal_price_is_stored_as_integer_agorot(self):
  xml=b'<Root><ChainID>123</ChainID><StoreID>1</StoreID><Items><Item><ItemCode>7290004131074</ItemCode><ItemName>Milk</ItemName><ItemPrice>7.35</ItemPrice><ItemType>1</ItemType><bIsWeighted>0</bIsWeighted></Item></Items></Root>'
  p=parse_price(xml,{'chainId':'123','code':'1'},{'file':'PriceFull-test.xml','publishedAt':'now'})
  self.assertEqual(p['7290004131074']['cents'],735)
 def test_weighted_not_cross_chain(self):
  xml=b'<Root><ChainID>123</ChainID><StoreID>1</StoreID><Items><Item><ItemCode>1234567891234</ItemCode><ItemName>Weighted</ItemName><ItemPrice>1.2</ItemPrice><ItemType>1</ItemType><bIsWeighted>1</bIsWeighted></Item></Items></Root>'
  p=parse_price(xml,{'chainId':'123','code':'1'},{'file':'test','publishedAt':'now'})
  self.assertIn('123:1234567891234',p)
if __name__=='__main__':unittest.main()
