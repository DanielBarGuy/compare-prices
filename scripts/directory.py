"""Nationwide locality and official branch directory. No synthetic branch prices."""
import json,re,gzip,xml.etree.ElementTree as ET
from pathlib import Path
from sync import DATA,save,now,get,cached_xml,fields,val,timestamp,shuf_listing,carrefour_listing
from cerberus import Cerberus
LOCALITIES_URL='https://data.gov.il/api/3/action/datastore_search?resource_id=5f75cd96-d670-43b0-bf6d-583436c5d054&limit=5000'
CHAINS=[
 {'id':'shufersal','name':'שופרסל','chainId':'7290027600007','adapter':'shufersal','portal':'https://prices.shufersal.co.il/'},
 {'id':'carrefour','name':'קרפור','chainId':'7290055700007','adapter':'carrefour','portal':'https://prices.carrefour.co.il/'},
 {'id':'ramilevy','name':'רמי לוי','chainId':'7290058140886','adapter':'cerberus','username':'RamiLevi','portal':'https://www.rami-levy.co.il/he/price-transparency'},
 {'id':'yohananof','name':'יוחננוף','chainId':'7290803800003','adapter':'cerberus','username':'Yohananof','portal':'https://url.publishedprices.co.il/'},
 {'id':'victory','name':'ויקטורי','chainId':'7290696200003','adapter':'laib','portal':'https://laibcatalog.co.il/'},
 {'id':'osherad','name':'אושר עד','chainId':'7290103152017','adapter':'cerberus','username':'osherad','portal':'https://url.publishedprices.co.il/'},
 {'id':'mahsani','name':'מחסני השוק','chainId':'7290661400001','adapter':'laib','portal':'https://laibcatalog.co.il/'}]
def norm(s):
 return re.sub(r'[^א-תa-z0-9]','',s.lower()).replace('קריית','קרית').replace('תקוה','תקווה')
def localities(refresh=False):
 p=DATA/'localities-source.json'
 if refresh or not p.exists():
  j=json.loads(get(LOCALITIES_URL))
  if not j.get('success') or len(j['result']['records'])<1000:raise ValueError('Incomplete national locality list')
  save(p,j)
 return [{'id':str(r['סמל_ישוב']),'name':r['שם_ישוב'].strip(),'english':r['שם_ישוב_לועזי'].strip(),'district':r['שם_נפה'].strip()} for r in json.loads(p.read_text())['result']['records'] if int(r['סמל_ישוב'])>0]
def adapter(chain):
 if chain['adapter']=='cerberus':
  c=Cerberus(chain['username'],chain.get('password',''));return c.listing,c.get
 if chain['adapter']=='carrefour':
  listing,_=carrefour_listing();return lambda search:listing,get
 if chain['adapter']=='shufersal':return lambda search:shuf_listing('0',5),get
 entries=json.loads(get('https://laibcatalog.co.il/webapi/api/getfiles?edi='+chain['chainId']))
 listing=[('https://laibcatalog.co.il/webapi/'+chain['chainId']+'/'+e['fileName'],e['fileName']) for e in entries]
 return lambda search:listing,get

def branch_rows(chain,xml,source,cities):
 root=ET.fromstring(xml)
 if val(fields(root),'ChainID')!=chain['chainId']:raise ValueError('Directory chain identity mismatch')
 codes={c['id']:c for c in cities};names={norm(c['name']):c for c in cities}
 aliases={'תלאביב':codes['5000'],'תלאביתיפה':codes['5000'],'תא':codes['5000'],'מודיעין':codes.get('1200'),'ראשון':codes.get('8300')}
 names.update({k:v for k,v in aliases.items() if v})
 out=[]
 for e in root.findall('.//Store'):
  d=fields(e);code=val(d,'StoreID');name=val(d,'StoreName');raw=val(d,'City');address=val(d,'Address')
  if not code.isdigit() or not name:continue
  city=codes.get(str(int(raw))) if raw.isdigit() else names.get(norm(raw));method='source-city'
  if not city:
   # Match a whole locality phrase from the retailer's own branch name/address; never fuzzy geocode.
   hay=' '+re.sub(r'[^א-תa-z0-9 ]',' ',(name+' '+address).lower())+' '
   matches=[c for c in cities if len(c['name'])>=4 and (' '+c['name']+' ') in hay]
   if matches:city=max(matches,key=lambda c:len(c['name']));method='source-name'
  out.append({'id':chain['id']+'-'+code.zfill(3),'chain':chain['id'],'chainName':chain['name'],'chainId':chain['chainId'],'code':code.zfill(3),'name':name,'city':city['name'] if city else (raw if raw and not raw.isdigit() else 'מיקום לא צוין'),'cityId':city['id'] if city else None,'cityMatch':method if city else 'unknown','sourceCity':raw,'address':address,'portal':chain['portal'],'directorySource':source,'storeType':val(d,'StoreType')})
 return out

def refresh(offline=False):
 cities=localities();old=json.loads((DATA/'directory.json').read_text()) if (DATA/'directory.json').exists() else {};stores=[];reports=[]
 for chain in CHAINS:
  try:
   if offline:
    files=list((DATA/'raw').glob('Stores'+chain['chainId']+'*'));p=max(files,key=lambda x:x.name);b=p.read_bytes();xml=gzip.decompress(b) if b[:2]==b'\x1f\x8b' else b;source=p.name
   else:
    listing,fetcher=adapter(chain);files=[x for x in listing('Stores') if x[1].startswith('Stores'+chain['chainId'])];entry=max(files,key=lambda x:x[1]);xml,_=cached_xml(*entry,fetcher=fetcher);source=entry[1]
   rows=branch_rows(chain,xml,source,cities);stores.extend(rows);reports.append({'id':chain['id'],'name':chain['name'],'count':len(rows),'source':source,'checkedAt':now(),'error':None});print(chain['id'],len(rows),'branches',flush=True)
  except Exception as e:
   rows=[s for s in old.get('stores',[]) if s['chain']==chain['id']];stores.extend(rows);reports.append({'id':chain['id'],'name':chain['name'],'count':len(rows),'error':str(e)});print(chain['id'],e,flush=True)
 save(DATA/'directory.json',{'updatedAt':now(),'localitiesSource':LOCALITIES_URL,'localities':cities,'chains':reports,'stores':stores})
if __name__=='__main__':
 import sys
 refresh('--offline' in sys.argv)
