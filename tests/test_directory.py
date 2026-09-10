import sys,json,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from directory import branch_rows,CHAINS,norm
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
   self.assertTrue(s['directorySource'].startswith('Stores'+s['chainId']))
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
if __name__=='__main__':unittest.main()
