"""Build the project's own SQLite catalog from verified retailer snapshots."""
import json,os,sqlite3,tempfile
from pathlib import Path
from datetime import datetime,timezone
from db_lock import database_lock

ROOT=Path(__file__).resolve().parent.parent
DATA=ROOT/'data'
SCHEMA_VERSION=1

SCHEMA="""
PRAGMA foreign_keys=ON;
CREATE TABLE metadata (
 key TEXT PRIMARY KEY,
 value TEXT NOT NULL
);
CREATE TABLE stores (
 id TEXT PRIMARY KEY,
 chain TEXT NOT NULL,
 chain_name TEXT NOT NULL,
 chain_id TEXT NOT NULL,
 code TEXT NOT NULL,
 name TEXT NOT NULL,
 city TEXT,
 city_id TEXT,
 address TEXT,
 portal TEXT NOT NULL,
 last_success_at TEXT,
 error TEXT,
 product_count INTEGER NOT NULL,
 price_baseline TEXT,
 promo_baseline TEXT
);
CREATE TABLE sources (
 store_id TEXT NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
 file TEXT NOT NULL,
 published_at TEXT,
 fetched_at TEXT,
 sha256 TEXT NOT NULL,
 portal TEXT NOT NULL,
 PRIMARY KEY (store_id,file)
);
CREATE TABLE products (
 id TEXT PRIMARY KEY,
 barcode TEXT NOT NULL,
 name TEXT NOT NULL,
 brand TEXT,
 size TEXT,
 weighted INTEGER NOT NULL CHECK (weighted IN (0,1))
);
CREATE INDEX products_barcode_idx ON products(barcode);
CREATE TABLE offers (
 product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
 store_id TEXT NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
 cents INTEGER NOT NULL CHECK (cents>0),
 unit TEXT,
 unit_price TEXT,
 price_updated_at TEXT,
 source_file TEXT NOT NULL,
 source_published_at TEXT,
 source_name TEXT,
 source_size TEXT,
 item_type TEXT,
 PRIMARY KEY (product_id,store_id),
 FOREIGN KEY (store_id,source_file) REFERENCES sources(store_id,file)
);
CREATE INDEX offers_store_price_idx ON offers(store_id,cents);
CREATE TABLE promotions (
 store_id TEXT NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
 promotion_id TEXT NOT NULL,
 description TEXT,
 starts_at TEXT NOT NULL,
 ends_at TEXT NOT NULL,
 club TEXT,
 coupon INTEGER NOT NULL CHECK (coupon IN (0,1)),
 restrictions TEXT,
 source_file TEXT NOT NULL,
 source_published_at TEXT,
 PRIMARY KEY (store_id,promotion_id),
 FOREIGN KEY (store_id,source_file) REFERENCES sources(store_id,file)
);
CREATE INDEX promotions_end_idx ON promotions(ends_at);
CREATE TABLE promotion_items (
 id INTEGER PRIMARY KEY,
 store_id TEXT NOT NULL,
 promotion_id TEXT NOT NULL,
 barcode TEXT NOT NULL,
 min_qty TEXT,
 max_qty TEXT,
 discounted_price TEXT,
 discount_rate TEXT,
 reward_type TEXT,
 FOREIGN KEY (store_id,promotion_id) REFERENCES promotions(store_id,promotion_id) ON DELETE CASCADE
);
CREATE INDEX promotion_items_lookup_idx ON promotion_items(store_id,barcode);
CREATE TABLE product_images (
 barcode TEXT PRIMARY KEY,
 image_url TEXT,
 source_name TEXT NOT NULL,
 source_page_url TEXT,
 license_name TEXT,
 license_url TEXT,
 attribution TEXT,
 source_updated_at TEXT,
 checked_at TEXT NOT NULL,
 width INTEGER,
 height INTEGER,
 content_sha256 TEXT,
 match_method TEXT NOT NULL,
 status TEXT NOT NULL
);
CREATE VIRTUAL TABLE product_search USING fts5(product_id UNINDEXED,name,brand,barcode,tokenize='unicode61');
"""

IMAGE_COLUMNS=('barcode','image_url','source_name','source_page_url','license_name','license_url','attribution','source_updated_at','checked_at','width','height','content_sha256','match_method','status')

def retained_images(path):
 if not path.exists():return []
 try:
  with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as db:
   columns={row[1] for row in db.execute('PRAGMA table_info(product_images)')}
   if not set(IMAGE_COLUMNS).issubset(columns):return []
   return db.execute('SELECT '+','.join(IMAGE_COLUMNS)+' FROM product_images').fetchall()
 except sqlite3.Error:return []

def _build_database(data_dir,output):
 data_dir=Path(data_dir);output=Path(output or data_dir/'prices.sqlite3');output.parent.mkdir(parents=True,exist_ok=True)
 images=retained_images(output);fd,temp_name=tempfile.mkstemp(prefix=output.name+'.',suffix='.tmp',dir=output.parent);os.close(fd);temp=Path(temp_name)
 db=None
 try:
  db=sqlite3.connect(temp)
  db.execute('PRAGMA journal_mode=DELETE');db.execute('PRAGMA synchronous=FULL');db.executescript(SCHEMA)
  files=sorted((data_dir/'stores').glob('*.json'),key=lambda p:(not p.name.startswith('shufersal'),p.name))
  for path in files:
   store=json.loads(path.read_text())
   products=store.get('products')
   if not isinstance(products,dict):continue
   store_id=store['id'];baselines=store.get('baselines') or {}
   db.execute('INSERT INTO stores VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(
    store_id,store['chain'],store['chainName'],str(store['chainId']),str(store['code']),store['name'],store.get('city'),store.get('cityId'),store.get('address'),store['portal'],store.get('lastSuccessAt'),store.get('error'),len(products),baselines.get('price'),baselines.get('promo')))
   for source in (store.get('sources') or {}).values():
    db.execute('INSERT INTO sources VALUES (?,?,?,?,?,?)',(store_id,source['file'],source.get('publishedAt'),source.get('fetchedAt'),source['sha256'],source.get('portal') or store['portal']))
   for product in products.values():
    db.execute('INSERT OR IGNORE INTO products VALUES (?,?,?,?,?,?)',(product['id'],product['barcode'],product['name'],product.get('brand'),product.get('size'),int(bool(product.get('weighted')))))
    db.execute('INSERT INTO offers VALUES (?,?,?,?,?,?,?,?,?,?,?)',(product['id'],store_id,int(product['cents']),product.get('unit'),product.get('unitPrice'),product.get('priceUpdatedAt'),product['sourceFile'],product.get('sourcePublishedAt'),product.get('name'),product.get('size'),product.get('itemType')))
   for promotion in (store.get('promotions') or {}).values():
    db.execute('INSERT INTO promotions VALUES (?,?,?,?,?,?,?,?,?,?)',(store_id,str(promotion['id']),promotion.get('description'),promotion['start'],promotion['end'],promotion.get('club'),int(bool(promotion.get('coupon'))),promotion.get('restrictions'),promotion['sourceFile'],promotion.get('sourcePublishedAt')))
    for item in promotion.get('items') or []:
     db.execute('INSERT INTO promotion_items(store_id,promotion_id,barcode,min_qty,max_qty,discounted_price,discount_rate,reward_type) VALUES (?,?,?,?,?,?,?,?)',(store_id,str(promotion['id']),item['barcode'],item.get('minQty'),item.get('maxQty'),item.get('discountedPrice'),item.get('discountRate'),item.get('rewardType')))
  db.executemany('INSERT INTO product_images VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',images)
  db.execute('INSERT INTO product_search(product_id,name,brand,barcode) SELECT id,name,coalesce(brand,\'\'),barcode FROM products')
  counts={table:db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ('stores','products','offers','promotions','promotion_items','sources','product_images')}
  built_at=datetime.now(timezone.utc).isoformat(timespec='seconds')
  metadata={'schema_version':str(SCHEMA_VERSION),'built_at':built_at,'origin':'retailer-transparency-files',**{table+'_count':str(count) for table,count in counts.items()}}
  db.executemany('INSERT INTO metadata VALUES (?,?)',metadata.items());db.execute('PRAGMA user_version='+str(SCHEMA_VERSION));db.commit()
  if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('SQLite integrity check failed')
  db.close();db=None;os.replace(temp,output)
  return {'path':str(output),'builtAt':built_at,**counts}
 except Exception:
  if db is not None:db.close()
  try:temp.unlink()
  except FileNotFoundError:pass
  raise

def build_database(data_dir=DATA,output=None):
 data_dir=Path(data_dir);output=Path(output or data_dir/'prices.sqlite3')
 with database_lock(data_dir):
  return _build_database(data_dir,output)

if __name__=='__main__':
 print(json.dumps(build_database(),ensure_ascii=False))
