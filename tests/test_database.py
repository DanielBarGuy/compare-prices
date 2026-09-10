import json,sqlite3,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from build_db import build_database

class DatabaseTest(unittest.TestCase):
 def test_normalized_catalog_and_images_survive_atomic_rebuild(self):
  with tempfile.TemporaryDirectory() as directory:
   data=Path(directory);(data/'stores').mkdir();source='PriceFull123-1-20260910-010000.gz';promo_source='PromoFull123-1-20260910-010000.gz'
   store={'id':'test-001','chain':'test','chainName':'רשת בדיקה','chainId':'123','code':'1','name':'סניף','city':'חיפה','cityId':'4000','address':'רחוב 1','portal':'https://example','lastSuccessAt':'2026-09-10T10:00:00+03:00','error':None,'baselines':{'price':source,'promo':promo_source},'sources':{
    source:{'file':source,'publishedAt':'2026-09-10T01:00:00+03:00','fetchedAt':'2026-09-10T01:01:00+03:00','sha256':'a'*64,'portal':'https://example'},
    promo_source:{'file':promo_source,'publishedAt':'2026-09-10T01:00:00+03:00','fetchedAt':'2026-09-10T01:01:00+03:00','sha256':'b'*64,'portal':'https://example'}},'products':{'7290000000001':{'id':'7290000000001','barcode':'7290000000001','name':'מוצר בדיקה','brand':'יצרן','size':'1 יחידה','weighted':False,'cents':735,'unit':'יחידות','unitPrice':'7.35','priceUpdatedAt':'2026-09-10T00:30:00','sourceFile':source,'sourcePublishedAt':'2026-09-10T01:00:00+03:00','itemType':'1'}},'promotions':{'42':{'id':'42','description':'2 ב־10','start':'2026-09-01T00:00:00+03:00','end':'2026-09-30T23:59:59+03:00','club':'0','coupon':False,'restrictions':'','sourceFile':promo_source,'sourcePublishedAt':'2026-09-10T01:00:00+03:00','items':[{'barcode':'7290000000001','minQty':'2','maxQty':'','discountedPrice':'10','discountRate':'','rewardType':'10'}]}}}
   (data/'stores'/'test-001.json').write_text(json.dumps(store,ensure_ascii=False))
   target=data/'prices.sqlite3';stats=build_database(data,target)
   self.assertEqual(stats['offers'],1)
   with sqlite3.connect(target) as db:
    self.assertEqual(db.execute('SELECT cents FROM offers').fetchone()[0],735)
    self.assertEqual(db.execute('SELECT sha256 FROM sources WHERE file=?',(source,)).fetchone()[0],'a'*64)
    self.assertEqual(db.execute('SELECT barcode FROM promotion_items').fetchone()[0],'7290000000001')
    self.assertEqual(db.execute("SELECT value FROM metadata WHERE key='origin'").fetchone()[0],'retailer-transparency-files')
    db.execute('INSERT INTO product_images VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',('7290000000001','https://images.example/1.jpg','licensed-source','https://example/product','CC BY-SA 4.0','https://creativecommons.org/licenses/by-sa/4.0/','Source attribution','2026-09-09T00:00:00Z','2026-09-10T00:00:00Z',800,800,'c'*64,'exact-gtin','verified'));db.commit()
   build_database(data,target)
   with sqlite3.connect(target) as db:
    self.assertEqual(db.execute('PRAGMA quick_check').fetchone()[0],'ok')
    self.assertEqual(db.execute('SELECT status FROM product_images WHERE barcode=?',('7290000000001',)).fetchone()[0],'verified')

if __name__=='__main__':unittest.main()
