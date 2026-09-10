"""Read official price files; retain raw evidence and atomically publish branch snapshots."""
import os,re,json,html,gzip,hashlib,time,urllib.request,urllib.parse,xml.etree.ElementTree as ET
from pathlib import Path
from decimal import Decimal,InvalidOperation
from datetime import datetime
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parent.parent; DATA=ROOT/'data'; TZ=ZoneInfo('Asia/Jerusalem')
def now():return datetime.now(TZ).isoformat(timespec='seconds')
def save(p,value):
 p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,separators=(',',':')));os.replace(tmp,p)
def get(url):
 req=urllib.request.Request(url,headers={'User-Agent':'SalSal-local/0.2 (public price transparency reader)'})
 with urllib.request.urlopen(req,timeout=35) as r:
  b=r.read(40_000_001)
  if len(b)>40_000_000:raise ValueError('Source file exceeds size limit')
  return b

def fields(el):return {c.tag.lower():(c.text or '').strip() for c in el}
def val(d,*keys):return next((d[k.lower()] for k in keys if d.get(k.lower())), '')
def timestamp(name):
 m=re.search(r'(\d{8})-?(\d{4,6})(?:\.|$)',name)
 return (m[1]+m[2].ljust(6,'0')) if m else ''
def source_time(name):
 t=timestamp(name)
 return datetime.strptime(t,'%Y%m%d%H%M%S').replace(tzinfo=TZ).isoformat() if t else ''
def parse_price(xml,store,source):
 r=ET.fromstring(xml);head=fields(r)
 if val(head,'ChainID')!=store['chainId'] or int(val(head,'StoreID'))!=int(store['code']):raise ValueError('Source branch identity mismatch')
 result={}
 for el in r.findall('.//Item'):
  d=fields(el);code=val(d,'ItemCode');name=val(d,'ItemName');raw=val(d,'ItemPrice')
  try:cents=int((Decimal(raw)*100).quantize(Decimal('1')))
  except (InvalidOperation,ValueError):continue
  if not code or not name or cents<=0:continue
  itemtype=val(d,'ItemType');weighted=val(d,'bIsWeighted')=='1'
  key=code if itemtype=='1' and not weighted and len(code)>=8 else store['chainId']+':'+code
  result[key]={'id':key,'barcode':code,'name':name,'brand':val(d,'ManufactureName','ManufacturerName'),'size':(val(d,'Quantity')+' '+val(d,'UnitQty')).strip(),'cents':cents,'weighted':weighted,'unitPrice':val(d,'UnitOfMeasurePrice'),'unit':val(d,'UnitOfMeasure'),'priceUpdatedAt':val(d,'PriceUpdateTime'),'sourceFile':source['file'],'sourcePublishedAt':source['publishedAt'],'itemType':itemtype}
 return result

def parse_promos(xml,store,source):
 r=ET.fromstring(xml);head=fields(r)
 if val(head,'ChainID')!=store['chainId'] or int(val(head,'StoreID'))!=int(store['code']):raise ValueError('Promotion branch mismatch')
 result={}
 for el in r.findall('.//Promotion'):
  d=fields(el);pid=val(d,'PromotionID');start=val(d,'PromotionStartDateTime','PromotionStartDate');end=val(d,'PromotionEndDateTime','PromotionEndDate')
  if len(start)==10:start+='T'+(val(d,'PromotionStartHour') or '00:00:00')
  if len(end)==10:end+='T'+(val(d,'PromotionEndHour') or '23:59:59')
  try:start=datetime.fromisoformat(start).replace(tzinfo=TZ).isoformat();end=datetime.fromisoformat(end).replace(tzinfo=TZ).isoformat()
  except ValueError:continue
  items=[]
  for item in el.findall('.//PromotionItem'):
   f=fields(item)
   if val(f,'ItemCode'):items.append({'barcode':val(f,'ItemCode'),'minQty':val(f,'MinQty'),'maxQty':val(f,'MaxQty'),'discountedPrice':val(f,'DiscountedPrice'),'discountRate':val(f,'DiscountRate'),'rewardType':val(f,'RewardType')})
  if pid:result[pid]={'id':pid,'description':val(d,'PromotionDescription'),'start':start,'end':end,'club':val(d,'ClubID'),'coupon':val(d,'AdditionalIsCoupon')=='1','restrictions':val(d,'AdditionalRestrictions','Remarks'),'items':items,'sourceFile':source['file'],'sourcePublishedAt':source['publishedAt']}
 return result

def cached_xml(url,name,fetcher=get):
 if not re.fullmatch(r'[\w.-]+',name):raise ValueError('Invalid source filename')
 p=DATA/'raw'/name
 if not p.exists():
  b=fetcher(url);x=gzip.decompress(b) if b[:2]==b'\x1f\x8b' else b
  if len(x)>80_000_000 or b'<!DOCTYPE' in x or b'<!ENTITY' in x:raise ValueError('Unsupported XML')
  ET.fromstring(x);p.write_bytes(b)
 else:b=p.read_bytes();x=gzip.decompress(b) if b[:2]==b'\x1f\x8b' else b
 return x,hashlib.sha256(b).hexdigest()

def shuf_listing(code,category):
 u=f'https://prices.shufersal.co.il/FileObject/UpdateCategory?catID={category}&storeId={int(code)}';s=get(u).decode('utf-8-sig')
 return [(html.unescape(u),urllib.parse.urlparse(html.unescape(u)).path.split('/')[-1]) for u in re.findall(r'href="(https[^\"]+\.gz[^\"]*)"',s)]
def carrefour_listing():
 s=get('https://prices.carrefour.co.il/').decode('utf-8-sig');day=re.search(r"const path = '([^']+)'",s)[1];files=json.loads(re.search(r'const files = (\[.*?\]);',s,re.S)[1]);names={v:html.unescape(n) for v,n in re.findall(r'<option value="(\d+)">(.*?)</option>',s)}
 return [(f'https://prices.carrefour.co.il/{day}/{f["name"]}',f['name']) for f in files],names

def sync_store(store,listing=None,fetcher=get):
 path=DATA/'stores'/(store['id']+'.json');old=json.loads(path.read_text()) if path.exists() else {};state={**old,**store,'lastAttemptAt':now()};sources=old.get('sources',{}).copy();prices=old.get('products',{}).copy();promos=old.get('promotions',{}).copy()
 try:
  if store['chain']=='shufersal':
   lists={k:shuf_listing(store['code'],c) for k,c in [('PriceFull',2),('Price',1),('PromoFull',4),('Promo',3)]}
  else:
   relevant=[x for x in listing if (m:=re.match(r'^(?:PriceFull|Price|PromoFull|Promo)\d+-(?:\d+-)?(\d+)-\d{8}-?\d{4,6}\.',x[1])) and int(m[1])==int(store['code'])];lists={k:[x for x in relevant if x[1].startswith(k) and (k.endswith('Full') or not x[1].startswith(k+'Full'))] for k in ['PriceFull','Price','PromoFull','Promo']}
  for full,delta,kind,parser in [('PriceFull','Price','price',parse_price),('PromoFull','Promo','promo',parse_promos)]:
   fullfiles=sorted(lists[full],key=lambda x:timestamp(x[1]));base=fullfiles[-1:]
   if kind=='price' and not base and not old.get('products'):raise ValueError('No full price baseline')
   base_t=timestamp(base[0][1]) if base else ''
   queue=base+sorted((x for x in lists[delta] if timestamp(x[1])>=base_t),key=lambda x:timestamp(x[1]))
   for url,name in queue:
    if name in sources:continue
    xml,sha=cached_xml(url,name,fetcher);src={'file':name,'publishedAt':source_time(name),'fetchedAt':now(),'sha256':sha,'portal':store['portal']};parsed=parser(xml,store,src)
    if kind=='price':
     if name.startswith(full):prices={}
     prices.update(parsed)
    else:
     if name.startswith(full):promos={}
     promos.update(parsed)
    sources[name]=src
  if not prices:raise ValueError('Empty price snapshot')
  state.update(products=prices,promotions=promos,sources=sources,lastSuccessAt=now(),error=None)
  save(path,state);print(store['id'],len(prices),'products,',len(promos),'promotions',flush=True)
 except Exception as e:
  state['error']=str(e);save(path,state);print(store['id'],'ERROR',str(e),flush=True)
 return {k:v for k,v in state.items() if k not in ['products','promotions','sources']}

def main():
 from directory import CHAINS,adapter,refresh
 started=now();errors=[]
 if not (DATA/'directory.json').exists():
  refresh()
 directory=json.loads((DATA/'directory.json').read_text())
 if time.time()-(DATA/'directory.json').stat().st_mtime>86400:
  refresh();directory=json.loads((DATA/'directory.json').read_text())
 selected=json.loads((DATA/'selection.json').read_text())['stores'] if (DATA/'selection.json').exists() else [p.stem for p in (DATA/'stores').glob('*.json')]
 requested=[s for s in directory['stores'] if s['id'] in selected]
 progress={'startedAt':started,'running':True,'total':len(requested),'done':0,'current':None,'results':[]}
 save(DATA/'progress.json',progress)
 def group(chain):
  groupstores=[s for s in requested if s['chain']==chain['id']]
  if not groupstores:return []
  try:
   listing,fetcher=adapter(chain);results=[]
   for store in groupstores:
    result=sync_store(store,None if chain['adapter']=='shufersal' else listing('-'+store['code']+'-'),fetcher)
    results.append(result)
    # Main thread publishes completion progress per chain.
   return results
  except Exception as e:
   errors.append(chain['name']+': '+str(e))
   return [{**s,'error':str(e)} for s in groupstores]
 results=[]
 from concurrent.futures import as_completed
 with ThreadPoolExecutor(max_workers=3) as pool:
  for f in as_completed([pool.submit(group,c) for c in CHAINS]):
   results.extend(f.result());progress.update(done=len(results),results=results);save(DATA/'progress.json',progress)
 progress.update(running=False,finishedAt=now());save(DATA/'progress.json',progress)
 save(DATA/'status.json',{'startedAt':started,'finishedAt':now(),'intervalMinutes':15,'stores':results,'errors':errors})
if __name__=='__main__':
 import fcntl
 with open(DATA/'.sync.lock','w') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:print('Another sync is running',flush=True)
  else:main()
