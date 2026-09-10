import sys,json,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from directory import branch_rows,CHAINS,norm,is_stores_file
ROOT=Path(__file__).resolve().parents[1]
class DirectoryTest(unittest.TestCase):
 def test_downloaded_country_directory_when_available(self):
  if not (ROOT/'data/directory.json').exists():self.skipTest('integration data is generated on first sync')
  d=json.loads((ROOT/'data/directory.json').read_text());cities={c['id']:c for c in d['localities']}
  self.assertGreater(len(cities),1200)
  for code in ['2600','4000','5000','3000','9000','2800']:
   self.assertIn(code,cities)
   self.assertTrue(any(s['cityId']==code for s in d['stores']),code)
  self.assertEqual(len(d['stores']),len({s['id'] for s in d['stores']}))
  for s in d['stores']:
   self.assertTrue(is_stores_file(s['directorySource'],s['chainId']),s['directorySource'])
   if s['cityId']:self.assertIn(s['cityId'],cities)
  self.assertGreater(sum(s['chain']=='victory' for s in d['stores']),50)
  self.assertGreater(sum(s['chain']=='osherad' for s in d['stores']),15)
 def test_unknown_city_not_assigned_another_branch_city(self):
  chain=CHAINS[0];xml='<Root><ChainID>'+chain['chainId']+'</ChainID><Store><StoreID>7</StoreID><StoreName>מרכז קניות</StoreName><City>0</City></Store></Root>'
  s=branch_rows(chain,xml,'test',[{'id':'5000','name':'תל אביב - יפו','english':'TEL AVIV','district':'תל אביב'}])[0]
  self.assertIsNone(s['cityId'])
  self.assertEqual(s['cityMatch'],'unknown')
 def test_wrong_chain_rejected_and_spelling_normalized(self):
  with self.assertRaises(ValueError):branch_rows(CHAINS[0],'<Root><ChainID>0</ChainID></Root>','test',[])
  self.assertEqual(norm('קריית ביאליק'),norm('קרית ביאליק'))
  self.assertEqual(norm('פתח תקוה'),norm('פתח תקווה'))
 def test_duplicate_store_ids_prefer_the_better_location_row(self):
  chain=CHAINS[0];xml='<Root><ChainID>'+chain['chainId']+'</ChainID><Store><StoreID>7</StoreID><StoreName>מרכז</StoreName><City>0</City></Store><Store><StoreID>7</StoreID><StoreName>מרכז תל אביב</StoreName><City>5000</City><Address>דיזנגוף 1</Address></Store></Root>'
  rows=branch_rows(chain,xml,'test',[{'id':'5000','name':'תל אביב - יפו','english':'TEL AVIV','district':'תל אביב'}])
  self.assertEqual(len(rows),1)
  self.assertEqual(rows[0]['cityId'],'5000')
 def test_empty_or_invalid_directory_cannot_replace_a_chain_snapshot(self):
  chain=CHAINS[0]
  with self.assertRaisesRegex(ValueError,'no valid stores'):
   branch_rows(chain,'<Root><ChainID>'+chain['chainId']+'</ChainID></Root>','test',[])
if __name__=='__main__':unittest.main()
