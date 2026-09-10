import io,json,sys,unittest,zipfile
from pathlib import Path
from urllib.request import Request
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))

import directory
import sync


CHAIN_ID='7290058108879'
PRICE='Price7290058108879-000-340-20260910-231951.GZ'
STORES='StoresFull7290058108879-000-20260910-011315.gz'


class SourceConfigurationTest(unittest.TestCase):
 def test_priority_retailers_are_registered_once(self):
  expected={'kingstore','keshet','tivtaam','hazihinam','freshmarket','stopmarket','superbareket','salahdabah','netivhesed','zolvebegadol','maayan2000','supersapir','shukhayir','shefabirkat','goodpharm','mishnatyosef','doralon','politzer','hcohen','superpharm','wolt','citymarket','superyuda'}
  ids=[chain['id'] for chain in sync.VERIFIED_CHAINS]
  chain_ids=[chain['chainId'] for chain in sync.VERIFIED_CHAINS]
  self.assertEqual(set(ids),expected)
  self.assertEqual(len(ids),23)
  self.assertEqual(len(ids),len(set(ids)))
  self.assertEqual(len(chain_ids),len(set(chain_ids)))

 def test_verified_sources_use_explicit_official_https_configuration(self):
  for chain in sync.VERIFIED_CHAINS:
   self.assertNotIn('chp',json.dumps(chain).lower())
   self.assertNotIn('password',chain)
   self.assertRegex(chain['chainId'],r'^\d{13}$')
   self.assertTrue(chain['portal'].startswith('https://'))
   if chain['adapter']=='bina':
    sync.validate_source_url(chain['portal'],(chain['host'],))
   elif chain['adapter']=='publishedprices':
    host=sync.urllib.parse.urlsplit(chain['base']).hostname
    sync.validate_source_url(chain['base'],(host,))
    self.assertTrue(chain['username'])
   elif chain['adapter']=='hazi':
    sync.validate_source_url(chain['portal'],sync.HaziHinamPortal.HOSTS)
   elif chain['adapter']=='netiv':
    sync.validate_source_url(chain['portal'],sync.NetivHesedPortal.HOSTS)
   elif chain['adapter']=='laib_safe':
    sync.validate_source_url(chain['portal'],(chain['host'],))
   elif chain['adapter']=='superpharm':
    sync.validate_source_url(chain['portal'],sync.SuperPharmPortal.HOSTS)
   elif chain['adapter']=='wolt':
    sync.validate_source_url(chain['portal'],sync.WoltPortal.HOSTS)
   else:self.fail('unreviewed adapter '+chain['adapter'])

 def test_nonempty_public_passwords_come_only_from_named_environment_variables(self):
  protected=[chain for chain in sync.VERIFIED_CHAINS if chain.get('passwordEnv')]
  self.assertEqual({chain['passwordEnv'] for chain in protected},{'SALSAL_SALAH_DABAH_PASSWORD','SALSAL_SUPER_YUDA_PASSWORD'})
  for chain in protected:
   with self.assertRaisesRegex(ValueError,chain['passwordEnv']):sync.public_portal_password(chain,{})
   self.assertEqual(sync.public_portal_password(chain,{chain['passwordEnv']:'local-value'}),'local-value')

 def test_directory_registry_has_exact_verified_source_entries(self):
  configured={chain['id']:chain for chain in directory.CHAINS}
  for chain in sync.VERIFIED_CHAINS:
   self.assertIs(configured[chain['id']],chain)

 def test_researched_gaps_cannot_silently_enter_the_registry(self):
  unsupported={entry['id']:entry for entry in sync.RESEARCHED_NOT_IMPLEMENTED}
  self.assertTrue({'rosman','paz-yellow','mega'}.issubset(unsupported))
  registered={chain['id'] for chain in directory.CHAINS}
  for entry in unsupported.values():
   self.assertNotIn(entry['id'],registered)
   self.assertNotIn('chainId',entry)
   self.assertTrue(entry['reason'])
   self.assertTrue(all(url.startswith('https://') for url in entry['evidence']))


class SourceUrlSafetyTest(unittest.TestCase):
 def test_exact_https_host_is_required(self):
  allowed=('files.example.co.il',)
  self.assertEqual(sync.validate_source_url('https://files.example.co.il:443/a.gz',allowed),'https://files.example.co.il:443/a.gz')
  for url in ('http://files.example.co.il/a.gz','https://evil-files.example.co.il/a.gz','https://files.example.co.il.evil.test/a.gz','https://user@files.example.co.il/a.gz','https://files.example.co.il:444/a.gz','https://files.example.co.il/a.gz#x','https://files.example.co.il\\@evil.test/a.gz'):
   with self.subTest(url=url),self.assertRaises(ValueError):sync.validate_source_url(url,allowed)

 def test_redirect_handler_rejects_an_off_host_location(self):
  handler=sync.AllowlistRedirectHandler(('files.example.co.il',))
  request=Request('https://files.example.co.il/a.gz')
  with self.assertRaises(ValueError):handler.redirect_request(request,None,302,'Found',{},'https://evil.test/a.gz')


class ListingParserTest(unittest.TestCase):
 def test_bina_json_is_constrained_to_chain_and_download_directory(self):
  blob=json.dumps([{'FileNm':PRICE},{'FileNm':'Price7290000000000-000-340-20260910-231951.gz'}]).encode()
  self.assertEqual(sync.parse_bina_listing(blob,'https://kingstore.binaprojects.com',CHAIN_ID),[('https://kingstore.binaprojects.com/Download/'+PRICE,PRICE)])
  with self.assertRaises(ValueError):sync.parse_bina_listing(b'[{"FileNm":7}]','https://kingstore.binaprojects.com',CHAIN_ID)

 def test_publishedprices_json_only_accepts_files_for_the_chain(self):
  payload={'aaData':[{'type':'file','name':STORES},{'type':'dir','name':PRICE},{'type':'file','name':'Stores7290000000000-000-202609100100.gz'}]}
  self.assertEqual(sync.parse_published_listing(json.dumps(payload).encode(),'https://url.publishedprices.co.il',CHAIN_ID),[('https://url.publishedprices.co.il/file/d/'+STORES,STORES)])

 def test_publishedprices_nested_directory_is_encoded_and_validated(self):
  name='Stores7290058177776-000-20260910-090000.xml';payload={'aaData':[{'type':'file','name':name}]}
  rows=sync.parse_published_listing(json.dumps(payload).encode(),'https://publishedprices.co.il','7290058177776','/Yuda')
  self.assertEqual(rows,[('https://publishedprices.co.il/file/d/Yuda/'+name,name)])
  with self.assertRaises(ValueError):sync.parse_published_listing(json.dumps(payload).encode(),'https://publishedprices.co.il','7290058177776','/../Yuda')

 def test_laib_json_supports_the_verified_duplicate_time_suffix(self):
  name='Stores7290455000004-000-20260910060202-060202.gz';payload=[{'branchNumber':0,'fileName':name,'fileType':'stores'}]
  rows=sync.parse_laib_listing(json.dumps(payload).encode(),'https://laibcatalog.co.il','7290455000004')
  self.assertEqual(rows,[('https://laibcatalog.co.il/webapi/7290455000004/'+name,name)])
  self.assertEqual(sync.timestamp(name),'20260910060202')

 def test_hazi_html_accepts_only_allowlisted_blob_path(self):
  url='https://hazihinamprod01.blob.core.windows.net/regulatories/'+STORES
  blob=('<a href="'+url+'">download</a>').encode()
  paths={'hazihinamprod01.blob.core.windows.net':('/regulatories/',)}
  self.assertEqual(sync.parse_html_listing(blob,'https://shop.hazi-hinam.co.il/Prices',CHAIN_ID,paths),[(url,STORES)])
  evil=('<a href="https://evil.test/regulatories/'+STORES+'">download</a>').encode()
  with self.assertRaises(ValueError):sync.parse_html_listing(evil,'https://shop.hazi-hinam.co.il/Prices',CHAIN_ID,paths)
  wrong_path=('<a href="https://hazihinamprod01.blob.core.windows.net/public/'+STORES+'">download</a>').encode()
  with self.assertRaises(ValueError):sync.parse_html_listing(wrong_path,'https://shop.hazi-hinam.co.il/Prices',CHAIN_ID,paths)

 def test_netiv_html_extracts_the_query_filename(self):
  href='/Prices/Download?fileName='+STORES
  blob=('<a href="'+href+'">download</a>').encode()
  expected='https://app.netiv-hesed.com'+href
  self.assertEqual(sync.parse_html_listing(blob,'https://app.netiv-hesed.com/',CHAIN_ID,sync.NetivHesedPortal.PATHS),[(expected,STORES)])

 def test_netiv_adapter_uses_a_bounded_previous_date_fallback(self):
  chain={'id':'netiv','chainId':CHAIN_ID,'adapter':'netiv','portal':'https://app.netiv-hesed.com/'}
  portal=sync.NetivHesedPortal(chain);calls=[]
  empty=b'<html></html>';found=('<a href="/Prices/Download?fileName='+STORES+'">file</a>').encode()
  def fake_read(opener,url,hosts,**kwargs):
   calls.append(url)
   return found if len(calls)==2 else empty
  with patch.object(sync,'allowlisted_read',side_effect=fake_read):rows=portal.listing('Stores')
  self.assertEqual(rows[0][1],STORES)
  self.assertEqual(len(calls),2)
  self.assertIn('Date=',calls[0]);self.assertIn('Date=',calls[1])

 def test_listing_pagination_is_same_host_path_and_bounded(self):
  page='https://shop.hazi-hinam.co.il/Prices?p=1&s=&f=&t=&d='
  blob=b'<a href="?p=2">2</a><a href="/Prices?p=5">5</a>'
  self.assertEqual(sync.parse_html_page_numbers(blob,page,'shop.hazi-hinam.co.il'),{1,2,5})
  with self.assertRaises(ValueError):sync.parse_html_page_numbers(b'<a href="https://evil.test/Prices?p=2">2</a>',page,'shop.hazi-hinam.co.il')
  with self.assertRaises(ValueError):sync.parse_html_page_numbers(b'<a href="?p=21">21</a>',page,'shop.hazi-hinam.co.il')

 def test_grid_page_count_is_explicit_and_bounded(self):
  self.assertEqual(sync.parse_grid_page_count(b'<div data-total-rows="21"></div>'),2)
  with self.assertRaises(ValueError):sync.parse_grid_page_count(b'<div data-total-rows="401"></div>')
  with self.assertRaises(ValueError):sync.parse_grid_page_count(b'<html></html>')

 def test_wolt_index_accepts_only_same_path_dated_pages(self):
  index='https://wm-gateway.wolt.com/isr-prices/public/v1/index.html'
  blob=b'<a href="2026-09-11.html">today</a><a href="2026-09-10.html">yesterday</a>'
  self.assertEqual(sync.parse_wolt_index(blob,index,'wm-gateway.wolt.com'),['https://wm-gateway.wolt.com/isr-prices/public/v1/2026-09-11.html','https://wm-gateway.wolt.com/isr-prices/public/v1/2026-09-10.html'])
  evil=b'<a href="https://evil.test/isr-prices/public/v1/2026-09-11.html">today</a>'
  with self.assertRaises(ValueError):sync.parse_wolt_index(evil,index,'wm-gateway.wolt.com')

 def test_superpharm_resolves_code_through_stores_before_filtering(self):
  chain={'id':'superpharm','chainId':'7290172900007','adapter':'superpharm','portal':'https://prices.super-pharm.co.il/'}
  stores='Stores7290172900007-000-20260910-070110.gz';price='PriceFull7290172900007-000-043-20260910-070110.gz'
  stores_href='/Download/'+stores+'?bucketName=sp_transparency_output_prod_v2';price_href='/Download/'+price+'?bucketName=sp_transparency_output_prod_v2'
  stores_html=('<a href="'+stores_href+'">file</a>').encode();price_html=('<div data-total-rows="1"></div><a href="'+price_href+'">file</a>').encode()
  stores_xml=b'<Root><ChainId>7290172900007</ChainId><Stores><Store><StoreId>043</StoreId><StoreName>Branch</StoreName></Store></Stores></Root>';calls=[]
  def fake_read(opener,url,hosts,**kwargs):
   calls.append(url)
   if 'Category-equals=Stores' in url:return stores_html
   if '/Download/'+stores in url:return stores_xml
   if 'BranchName-equals=Branch' in url:return price_html
   raise AssertionError(url)
  portal=sync.SuperPharmPortal(chain)
  with patch.object(sync,'allowlisted_read',side_effect=fake_read):rows=portal.listing('-043-')
  self.assertEqual(rows[0][1],price)
  self.assertTrue(any('BranchName-equals=Branch' in url for url in calls))

 def test_source_filename_accepts_known_variants_but_not_traversal(self):
  self.assertTrue(sync.source_filename(PRICE,CHAIN_ID))
  self.assertTrue(sync.is_stores_file(STORES,CHAIN_ID))
  self.assertFalse(sync.source_filename('../'+PRICE,CHAIN_ID))
  self.assertFalse(sync.source_filename('Price7290000000000-000-340-20260910-231951.gz',CHAIN_ID))
  self.assertFalse(sync.source_filename('Price'+CHAIN_ID+'-000-340-no-date.gz',CHAIN_ID))
  self.assertTrue(sync.is_stores_file('Stores7290027600007-000-20260910-020.gz','7290027600007'))
  self.assertFalse(sync.is_stores_file('Price7290027600007-000-20260910-020.gz','7290027600007'))
  self.assertTrue(sync.store_file('PriceFull7290455000004-000-35-20260910060202-060202.gz','PriceFull',{'chainId':'7290455000004','code':'035'}))


class SourceFormatTest(unittest.TestCase):
 @staticmethod
 def zipped(entries):
  stream=io.BytesIO()
  with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
   for name,blob in entries:archive.writestr(name,blob)
  return stream.getvalue()

 def test_single_xml_zip_is_supported_for_vendor_gz_files(self):
  xml=b'<Root><ChainId>7290058173198</ChainId></Root>'
  blob=self.zipped([('StoresFull7290058173198-000-202609101000.xml',xml)])
  self.assertEqual(sync.decode_xml(blob),xml)

 def test_utf16_xml_is_supported_but_utf16_entities_are_rejected(self):
  self.assertTrue(sync.decode_xml('<Root/>'.encode('utf-16')).startswith((b'\xff\xfe',b'\xfe\xff')))
  hostile='<!DOCTYPE Root [<!ENTITY x "boom">]><Root>&x;</Root>'.encode('utf-16')
  with self.assertRaises(ValueError):sync.decode_xml(hostile)

 def test_zip_output_and_members_are_bounded(self):
  oversized=self.zipped([('source.xml',b'<Root>'+b'x'*64+b'</Root>')])
  with self.assertRaises(ValueError):sync.decode_xml(oversized,limit=32)
  multiple=self.zipped([('one.xml',b'<Root/>'),('two.xml',b'<Root/>')])
  with self.assertRaises(ValueError):sync.decode_xml(multiple)
  traversal=self.zipped([('../source.xml',b'<Root/>')])
  with self.assertRaises(ValueError):sync.decode_xml(traversal)

 def test_bina_item_and_promotion_variants_are_parsed(self):
  source={'file':'PriceFull-test.xml','publishedAt':'now'};store={'chainId':'123','code':'1'}
  price=b'<Root><ChainId>123</ChainId><StoreId>1</StoreId><Items><Item><ItemCode>7290004131074</ItemCode><ItemNm>Milk</ItemNm><ItemPrice>7.35</ItemPrice><ItemType>1</ItemType><bIsWeighted>0</bIsWeighted><PriceUpdateDate>2026-09-10</PriceUpdateDate></Item></Items></Root>'
  parsed=sync.parse_price(price,store,source)['7290004131074']
  self.assertEqual((parsed['name'],parsed['priceUpdatedAt']),('Milk','2026-09-10'))
  promo=b'<Root><ChainId>123</ChainId><StoreId>1</StoreId><Promotions><Promotion><PromotionID>p1</PromotionID><PromotionStartDate>2026-09-01</PromotionStartDate><PromotionEndDate>2026-09-30</PromotionEndDate><MinQty>2</MinQty><DiscountedPrice>10</DiscountedPrice><PromotionItems><Item><ItemCode>7290004131074</ItemCode></Item></PromotionItems><AdditionalRestrictions><AdditionalIsCoupon>1</AdditionalIsCoupon><ClubID>club</ClubID><Remarks>members</Remarks></AdditionalRestrictions></Promotion></Promotions></Root>'
  parsed=sync.parse_promos(promo,store,source)['p1']
  self.assertEqual(parsed['items'][0]['minQty'],'2')
  self.assertEqual(parsed['items'][0]['discountedPrice'],'10')
  self.assertEqual((parsed['coupon'],parsed['club'],parsed['restrictions']),(True,'club','members'))


if __name__=='__main__':unittest.main()
