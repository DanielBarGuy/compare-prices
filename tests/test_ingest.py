import sys,unittest,tempfile,gzip
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import sync
from sync import parse_price,parse_promos,decode_xml
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
 def test_removed_item_is_returned_as_tombstone(self):
  xml=b'<Root><ChainID>123</ChainID><StoreID>1</StoreID><Items><Item><ItemCode>7290004131074</ItemCode><ItemType>1</ItemType><bIsWeighted>0</bIsWeighted><ItemStatus>0</ItemStatus></Item></Items></Root>'
  p=parse_price(xml,{'chainId':'123','code':'1'},{'file':'Price-test.xml','publishedAt':'now'})
  self.assertIsNone(p['7290004131074'])
 def test_repeated_promotion_id_keeps_every_item(self):
  xml=b'''<Root><ChainID>123</ChainID><StoreID>1</StoreID><Promotions>
   <Promotion><PromotionID>42</PromotionID><PromotionDescription>Shared offer</PromotionDescription><PromotionStartDateTime>2026-09-01T00:00:00</PromotionStartDateTime><PromotionEndDateTime>2026-09-30T23:59:59</PromotionEndDateTime><PromotionItems><PromotionItem><ItemCode>111</ItemCode><MinQty>1</MinQty></PromotionItem></PromotionItems></Promotion>
   <Promotion><PromotionID>42</PromotionID><PromotionDescription>Shared offer</PromotionDescription><PromotionStartDateTime>2026-09-01T00:00:00</PromotionStartDateTime><PromotionEndDateTime>2026-09-30T23:59:59</PromotionEndDateTime><PromotionItems><PromotionItem><ItemCode>222</ItemCode><MinQty>1</MinQty></PromotionItem></PromotionItems></Promotion>
  </Promotions></Root>'''
  promos=parse_promos(xml,{'chainId':'123','code':'1'},{'file':'Promo-test.xml','publishedAt':'now'})
  self.assertEqual([item['barcode'] for item in promos['42']['items']],['111','222'])
 def test_gzip_output_is_bounded_before_xml_parsing(self):
  with self.assertRaises(ValueError):decode_xml(gzip.compress(b'<Root>'+b'x'*128+b'</Root>'),limit=64)
 def test_newer_baseline_replays_an_already_seen_delta(self):
  full1='PriceFull123-1-20260910-010000.gz';full2='PriceFull123-1-20260910-020000.gz';delta3='Price123-1-20260910-030000.gz'
  with tempfile.TemporaryDirectory() as directory:
   original=sync.DATA;sync.DATA=Path(directory)
   try:
    files={full1:self._price_xml('1.00'),full2:self._price_xml('2.00'),delta3:self._price_xml('3.00')}
    fetch=lambda url:files[url.rsplit('/',1)[-1]]
    store=self._store()
    sync.sync_store(store,[(f'https://example/{name}',name) for name in [full1,delta3]],fetch)
    # The already-applied delta may have disappeared from the portal listing, but its raw evidence is retained.
    sync.sync_store(store,[(f'https://example/{name}',name) for name in [full1,full2]],fetch)
    saved=sync.json.loads((sync.DATA/'stores'/'test-001.json').read_text())
    self.assertEqual(saved['products']['7290004131074']['cents'],300)
    self.assertEqual(saved['baselines']['price'],full2)
    # A transiently older portal listing must not roll the retained baseline back.
    sync.sync_store(store,[(f'https://example/{full1}',full1)],fetch)
    saved=sync.json.loads((sync.DATA/'stores'/'test-001.json').read_text())
    self.assertEqual(saved['products']['7290004131074']['cents'],300)
    self.assertEqual(saved['baselines']['price'],full2)
   finally:sync.DATA=original
 def test_late_delta_cannot_overwrite_a_newer_delta(self):
  full='PriceFull123-1-20260910-010000.gz';delta2='Price123-1-20260910-020000.gz';delta3='Price123-1-20260910-030000.gz'
  with tempfile.TemporaryDirectory() as directory:
   original=sync.DATA;sync.DATA=Path(directory)
   try:
    files={full:self._price_xml('1.00'),delta2:self._price_xml('2.00'),delta3:self._price_xml('3.00')}
    fetch=lambda url:files[url.rsplit('/',1)[-1]]
    store=self._store()
    sync.sync_store(store,[(f'https://example/{name}',name) for name in [full,delta3]],fetch)
    sync.sync_store(store,[(f'https://example/{name}',name) for name in [full,delta2,delta3]],fetch)
    saved=sync.json.loads((sync.DATA/'stores'/'test-001.json').read_text())
    self.assertEqual(saved['products']['7290004131074']['cents'],300)
   finally:sync.DATA=original
 def test_parser_validated_pending_files_are_recovered_after_a_failed_run(self):
  full='PriceFull123-1-20260910-010000.gz';delta='Price123-1-20260910-020000.gz';bad_promo='PromoFull123-1-20260910-020000.gz'
  with tempfile.TemporaryDirectory() as directory:
   original=sync.DATA;sync.DATA=Path(directory)
   try:
    store=self._store();files={full:self._price_xml('1.00'),delta:self._price_xml('2.00'),bad_promo:b'<Root><ChainID>wrong</ChainID><StoreID>1</StoreID></Root>'};fetch=lambda url:files[url.rsplit('/',1)[-1]]
    sync.sync_store(store,[(f'https://example/{name}',name) for name in [full,delta,bad_promo]],fetch)
    failed=sync.json.loads((sync.DATA/'stores'/'test-001.json').read_text())
    self.assertNotIn('products',failed)
    self.assertIn(delta,sync.json.loads((sync.DATA/'pending'/'test-001.json').read_text()))
    sync.sync_store(store,[],fetch)
    saved=sync.json.loads((sync.DATA/'stores'/'test-001.json').read_text())
    self.assertEqual(saved['products']['7290004131074']['cents'],200)
    self.assertIn(delta,saved['sources'])
    self.assertEqual(sync.json.loads((sync.DATA/'pending'/'test-001.json').read_text()),{})
   finally:sync.DATA=original
 @staticmethod
 def _price_xml(price):
  return f'<Root><ChainID>123</ChainID><StoreID>1</StoreID><Items><Item><ItemCode>7290004131074</ItemCode><ItemName>Milk</ItemName><ItemPrice>{price}</ItemPrice><ItemType>1</ItemType><bIsWeighted>0</bIsWeighted><ItemStatus>1</ItemStatus></Item></Items></Root>'.encode()
 @staticmethod
 def _store():
  return {'id':'test-001','chain':'test','chainName':'Test','chainId':'123','code':'1','name':'Branch','city':'Test','portal':'https://example'}
if __name__=='__main__':unittest.main()
