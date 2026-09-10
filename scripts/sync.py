"""Read official price files; retain raw evidence and atomically publish branch snapshots."""
import os,re,json,html,gzip,hashlib,time,io,zipfile,http.cookiejar,urllib.request,urllib.parse,xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from decimal import Decimal,InvalidOperation
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parent.parent; DATA=ROOT/'data'; TZ=ZoneInfo('Asia/Jerusalem'); MAX_SOURCE_BYTES=40_000_000; MAX_XML_BYTES=80_000_000; MAX_LISTING_BYTES=5_000_000
CPFTA_RETAILERS_URL='https://www.gov.il/he/pages/cpfta_prices_regulations'
# Every entry below was matched to the regulator's retailer directory, its live public
# listing, a current Stores file, and the file-download response.  The config is kept
# beside the allowlisted adapters so an entry cannot silently fall back to a generic URL.
VERIFIED_CHAINS=[
 {'id':'kingstore','name':'קינג סטור','chainId':'7290058108879','adapter':'bina','host':'kingstore.binaprojects.com','portal':'https://kingstore.binaprojects.com/Main.aspx'},
 {'id':'keshet','name':'קשת טעמים','chainId':'7290785400000','adapter':'publishedprices','base':'https://url.publishedprices.co.il','username':'Keshet','portal':'https://url.publishedprices.co.il/login'},
 {'id':'tivtaam','name':'טיב טעם','chainId':'7290873255550','adapter':'publishedprices','base':'https://url.publishedprices.co.il','username':'TivTaam','portal':'https://url.publishedprices.co.il/login'},
 {'id':'hazihinam','name':'חצי חינם','chainId':'7290700100008','adapter':'hazi','portal':'https://shop.hazi-hinam.co.il/Prices'},
 {'id':'freshmarket','name':'פרשמרקט / מחסני להב','chainId':'7290876100000','adapter':'publishedprices','base':'https://url.publishedprices.co.il','username':'freshmarket','portal':'https://url.publishedprices.co.il/login'},
 {'id':'stopmarket','name':'סטופ מרקט','chainId':'7290639000004','adapter':'publishedprices','base':'https://url.retail.publishedprices.co.il','username':'Stop_Market','portal':'https://url.retail.publishedprices.co.il/login'},
 {'id':'superbareket','name':'סופר ברקת','chainId':'7290875100001','adapter':'bina','host':'superbareket.binaprojects.com','portal':'https://superbareket.binaprojects.com/Main.aspx'},
 {'id':'salahdabah','name':'סאלח דבאח','chainId':'7290526500006','adapter':'publishedprices','base':'https://url.publishedprices.co.il','username':'SalachD','passwordEnv':'SALSAL_SALAH_DABAH_PASSWORD','portal':'https://url.publishedprices.co.il/login'},
 {'id':'netivhesed','name':'נתיב החסד / ברכל','chainId':'7290058160839','adapter':'netiv','portal':'https://app.netiv-hesed.com/'},
 {'id':'zolvebegadol','name':'זול ובגדול','chainId':'7290058173198','adapter':'bina','host':'zolvebegadol.binaprojects.com','portal':'https://zolvebegadol.binaprojects.com/Main.aspx'},
 {'id':'maayan2000','name':'מעיין 2000','chainId':'7290058159628','adapter':'bina','host':'maayan2000.binaprojects.com','portal':'https://maayan2000.binaprojects.com/Main.aspx'},
 {'id':'supersapir','name':'סופר ספיר','chainId':'7290058156016','adapter':'bina','host':'supersapir.binaprojects.com','portal':'https://supersapir.binaprojects.com/Main.aspx'},
 {'id':'shukhayir','name':'שוק העיר','chainId':'7290058148776','adapter':'bina','host':'shuk-hayir.binaprojects.com','portal':'https://shuk-hayir.binaprojects.com/Main.aspx'},
 {'id':'shefabirkat','name':'שפע ברכת השם','chainId':'7290058134977','adapter':'bina','host':'shefabirkathashem.binaprojects.com','portal':'https://shefabirkathashem.binaprojects.com/Main.aspx'},
 {'id':'goodpharm','name':'גוד פארם','chainId':'7290058197699','adapter':'bina','host':'goodpharm.binaprojects.com','portal':'https://goodpharm.binaprojects.com/Main.aspx'},
 {'id':'mishnatyosef','name':'משנת יוסף','chainId':'7290058289400','adapter':'bina','host':'ktshivuk.binaprojects.com','portal':'https://ktshivuk.binaprojects.com/Main.aspx'},
 {'id':'doralon','name':'דור אלון','chainId':'7290492000005','adapter':'publishedprices','base':'https://url.publishedprices.co.il','username':'doralon','portal':'https://url.publishedprices.co.il/login'},
 {'id':'politzer','name':'פוליצר','chainId':'7291059100008','adapter':'publishedprices','base':'https://url.publishedprices.co.il','username':'politzer','portal':'https://url.publishedprices.co.il/login'},
 {'id':'hcohen','name':'ח. כהן','chainId':'7290455000004','adapter':'laib_safe','host':'laibcatalog.co.il','portal':'https://laibcatalog.co.il/hcohen/index.html'},
 {'id':'superpharm','name':'סופר-פארם','chainId':'7290172900007','adapter':'superpharm','portal':'https://prices.super-pharm.co.il/'},
 {'id':'wolt','name':'וולט מרקט','chainId':'7290058249350','adapter':'wolt','portal':'https://wm-gateway.wolt.com/isr-prices/public/v1/index.html'},
 {'id':'citymarket','name':'סיטי מרקט קריית גת','chainId':'7290058266241','adapter':'bina','host':'citymarketkiryatgat.binaprojects.com','portal':'https://citymarketkiryatgat.binaprojects.com/Main.aspx'},
 {'id':'superyuda','name':'סופר יודה','chainId':'7290058177776','adapter':'publishedprices','base':'https://publishedprices.co.il','directory':'/Yuda','username':'yuda_ho','passwordEnv':'SALSAL_SUPER_YUDA_PASSWORD','portal':'https://publishedprices.co.il/file'}]
# These are deliberately not consumed by directory.py.  They make investigated gaps
# auditable without assigning an unverified chain ID, login, or download endpoint.
RESEARCHED_NOT_IMPLEMENTED=[
 {'id':'rosman','name':'רוסמן','status':'unverified','reason':'No statutory price-file portal, public credentials, or Stores file was verified','evidence':(CPFTA_RETAILERS_URL,'https://www.gov.il/BlobFolder/news/iron-branches-140424/he/barzel_iron-branches-160625.pdf','https://www.gov.il/BlobFolder/legalinfo/2021-026627reg/he/mirsham_2021-026627.pdf')},
 {'id':'paz-yellow','name':'פז Yellow','status':'verified-feed-without-directory','reason':'The official price feed was verified, but it published no Stores file needed for safe branch identity','evidence':(CPFTA_RETAILERS_URL,)},
 {'id':'mega','name':'מגה','status':'covered-only-as-published','reason':'No separate current Mega feed was verified; legacy Bitan-branded branches remain in the official Global Retail feed','evidence':(CPFTA_RETAILERS_URL,)}]
def now():return datetime.now(TZ).isoformat(timespec='seconds')
def save(p,value):
 p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,separators=(',',':')));os.replace(tmp,p)
def get(url):
 req=urllib.request.Request(url,headers={'User-Agent':'SalSal-local/0.2 (public price transparency reader)'})
 with urllib.request.urlopen(req,timeout=35) as r:
  b=r.read(MAX_SOURCE_BYTES+1)
  if len(b)>MAX_SOURCE_BYTES:raise ValueError('Source file exceeds size limit')
  return b

def validate_source_url(url,allowed_hosts):
 if not isinstance(url,str) or not url or re.search(r'[\x00-\x20\\]',url):raise ValueError('Invalid source URL')
 try:
  parsed=urllib.parse.urlsplit(url);port=parsed.port
 except ValueError as e:raise ValueError('Invalid source URL') from e
 hosts={h.lower().rstrip('.') for h in allowed_hosts}
 if parsed.scheme!='https' or not parsed.hostname or parsed.hostname.lower().rstrip('.') not in hosts:raise ValueError('Source host is not allowlisted')
 if parsed.username is not None or parsed.password is not None or port not in (None,443) or parsed.fragment:raise ValueError('Invalid source URL')
 return url

class AllowlistRedirectHandler(urllib.request.HTTPRedirectHandler):
 def __init__(self,allowed_hosts):self.allowed_hosts=tuple(allowed_hosts)
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  target=urllib.parse.urljoin(req.full_url,newurl)
  validate_source_url(target,self.allowed_hosts)
  return super().redirect_request(req,fp,code,msg,headers,target)

def allowlisted_opener(allowed_hosts,cookies=None):
 handlers=[AllowlistRedirectHandler(allowed_hosts)]
 if cookies is not None:handlers.append(urllib.request.HTTPCookieProcessor(cookies))
 return urllib.request.build_opener(*handlers)

def allowlisted_read(opener,url,allowed_hosts,data=None,headers=None,limit=MAX_SOURCE_BYTES):
 validate_source_url(url,allowed_hosts)
 request_headers={'User-Agent':'SalSal-local/0.2 (public price transparency reader)'}
 request_headers.update(headers or {})
 req=urllib.request.Request(url,data=data,headers=request_headers)
 with opener.open(req,timeout=35) as response:
  validate_source_url(response.geturl(),allowed_hosts)
  blob=response.read(limit+1)
 if len(blob)>limit:raise ValueError('Source response exceeds size limit')
 return blob

def public_portal_password(chain,environ=None):
 env=chain.get('passwordEnv')
 if not env:return ''
 if not re.fullmatch(r'SALSAL_[A-Z0-9_]+',env):raise ValueError('Invalid public portal password environment variable')
 value=(os.environ if environ is None else environ).get(env)
 if value is None:raise ValueError('Public portal password is not configured; set '+env+' from the regulator directory')
 return value

SOURCE_FILE_RE=re.compile(r'^(StoresFull|Stores|PriceFull|Price|PromoFull|Promo)(\d{13})-[0-9-]+\.(?i:gz|xml)$')
def source_filename(name,chain_id):
 if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+',name):return False
 match=SOURCE_FILE_RE.fullmatch(name)
 return bool(match and match[2]==str(chain_id) and timestamp(name))
def is_stores_file(name,chain_id):
 # Shufersal's real Stores files can end with a three-digit run marker
 # (for example ``...-20260910-020.gz``), rather than the 4–6 digit time
 # used by price files. Keep that exception scoped to exact Stores names.
 if source_filename(name,chain_id):return name.startswith('Stores'+str(chain_id)) or name.startswith('StoresFull'+str(chain_id))
 if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+',name):return False
 return bool(re.fullmatch(r'Stores(?:Full)?'+re.escape(str(chain_id))+r'-(?:\d+-)*\d{8}-?\d{3,6}(?:-\d{3,6})?\.(?i:gz|xml)',name))

def parse_bina_listing(blob,base,chain_id):
 validate_source_url(base,((urllib.parse.urlsplit(base).hostname or ''),))
 try:rows=json.loads(blob.decode('utf-8-sig'))
 except (UnicodeDecodeError,json.JSONDecodeError) as e:raise ValueError('Invalid Bina listing') from e
 if not isinstance(rows,list):raise ValueError('Invalid Bina listing')
 result=[]
 for row in rows:
  if not isinstance(row,dict) or not isinstance(row.get('FileNm'),str):raise ValueError('Invalid Bina listing row')
  name=row['FileNm'].strip()
  if not source_filename(name,chain_id):continue
  result.append((base.rstrip('/')+'/Download/'+urllib.parse.quote(name,safe=''),name))
 return result

def parse_published_listing(blob,base,chain_id,directory='/'):
 try:payload=json.loads(blob.decode('utf-8-sig'))
 except (UnicodeDecodeError,json.JSONDecodeError) as e:raise ValueError('Invalid published-prices listing') from e
 rows=payload.get('aaData') if isinstance(payload,dict) else None
 if not isinstance(rows,list):raise ValueError('Invalid published-prices listing')
 if directory!='/' and not re.fullmatch(r'/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*',directory):raise ValueError('Invalid published-prices directory')
 folder='' if directory=='/' else '/'.join(urllib.parse.quote(part,safe='') for part in directory.strip('/').split('/'))+'/'
 result=[]
 for row in rows:
  if not isinstance(row,dict):raise ValueError('Invalid published-prices listing row')
  name=row.get('name')
  if row.get('type')!='file' or not source_filename(name,chain_id):continue
  result.append((base.rstrip('/')+'/file/d/'+folder+urllib.parse.quote(name,safe=''),name))
 return result

def parse_laib_listing(blob,base,chain_id):
 try:rows=json.loads(blob.decode('utf-8-sig'))
 except (UnicodeDecodeError,json.JSONDecodeError) as e:raise ValueError('Invalid Laib listing') from e
 if not isinstance(rows,list):raise ValueError('Invalid Laib listing')
 result=[]
 for row in rows:
  if not isinstance(row,dict) or not isinstance(row.get('fileName'),str):raise ValueError('Invalid Laib listing row')
  name=row['fileName'].strip()
  if not source_filename(name,chain_id):continue
  result.append((base.rstrip('/')+'/webapi/'+str(chain_id)+'/'+urllib.parse.quote(name,safe=''),name))
 return result

class _LinkParser(HTMLParser):
 def __init__(self):super().__init__(convert_charrefs=True);self.hrefs=[]
 def handle_starttag(self,tag,attrs):
  if tag.lower()=='a':
   href=dict(attrs).get('href')
   if href:self.hrefs.append(href)

def _candidate_filename(url):
 parsed=urllib.parse.urlsplit(url);query=urllib.parse.parse_qs(parsed.query,keep_blank_values=True)
 values=query.get('fileName')
 if values:
  if len(values)!=1:return ''
  return urllib.parse.unquote(values[0])
 return urllib.parse.unquote(parsed.path.rsplit('/',1)[-1])

def parse_html_listing(blob,page_url,chain_id,download_paths):
 try:text=blob.decode('utf-8-sig')
 except UnicodeDecodeError as e:raise ValueError('Invalid HTML listing encoding') from e
 parser=_LinkParser();parser.feed(text);result=[];seen=set()
 for href in parser.hrefs:
  url=urllib.parse.urljoin(page_url,href);name=_candidate_filename(url)
  if not source_filename(name,chain_id):continue
  validate_source_url(url,download_paths)
  parsed=urllib.parse.urlsplit(url);prefixes=download_paths[parsed.hostname.lower().rstrip('.')]
  if not any(parsed.path.startswith(prefix) if prefix.endswith('/') else parsed.path==prefix for prefix in prefixes):raise ValueError('Unexpected download path')
  if name in seen:continue
  seen.add(name);result.append((url,name))
 return result

def parse_html_page_numbers(blob,page_url,listing_host,max_pages=20):
 try:text=blob.decode('utf-8-sig')
 except UnicodeDecodeError as e:raise ValueError('Invalid HTML listing encoding') from e
 parser=_LinkParser();parser.feed(text);pages={1};page_path=urllib.parse.urlsplit(page_url).path
 for href in parser.hrefs:
  url=urllib.parse.urljoin(page_url,href);parsed=urllib.parse.urlsplit(url);values=urllib.parse.parse_qs(parsed.query).get('p')
  if not values:continue
  validate_source_url(url,(listing_host,))
  if parsed.path!=page_path or len(values)!=1 or not values[0].isdigit():raise ValueError('Invalid listing pagination URL')
  page=int(values[0])
  if page<1 or page>max_pages:raise ValueError('Listing pagination exceeds limit')
  pages.add(page)
 return pages

def parse_grid_page_count(blob,page_size=20,max_pages=20):
 try:text=blob.decode('utf-8-sig')
 except UnicodeDecodeError as e:raise ValueError('Invalid HTML listing encoding') from e
 matches=re.findall(r'data-total-rows="(\d+)"',text)
 if len(matches)!=1:raise ValueError('Invalid grid listing')
 pages=max(1,(int(matches[0])+page_size-1)//page_size)
 if pages>max_pages:raise ValueError('Grid listing exceeds page limit')
 return pages

def parse_wolt_index(blob,index_url,host,max_days=8):
 try:text=blob.decode('utf-8-sig')
 except UnicodeDecodeError as e:raise ValueError('Invalid Wolt index encoding') from e
 parser=_LinkParser();parser.feed(text);base_path=urllib.parse.urlsplit(index_url).path.rsplit('/',1)[0]+'/';result=[]
 for href in parser.hrefs:
  url=urllib.parse.urljoin(index_url,href);parsed=urllib.parse.urlsplit(url);name=parsed.path.rsplit('/',1)[-1]
  if not re.fullmatch(r'\d{4}-\d{2}-\d{2}\.html',name):continue
  validate_source_url(url,(host,))
  if parsed.path!=base_path+name or parsed.query:raise ValueError('Invalid Wolt date-page URL')
  try:datetime.strptime(name,'%Y-%m-%d.html')
  except ValueError as e:raise ValueError('Invalid Wolt date-page URL') from e
  result.append(url)
 return sorted(set(result),reverse=True)[:max_days]

class BinaPortal:
 def __init__(self,chain):
  self.chain=chain;self.host=chain['host'].lower();self.base='https://'+self.host
  validate_source_url(chain['portal'],(self.host,));self.opener=allowlisted_opener((self.host,))
 def listing(self,search):
  match=re.fullmatch(r'-(\d+)-',search or '')
  store=str(int(match[1])) if match else '0';file_type='1' if search=='Stores' else '0'
  body=urllib.parse.urlencode({'WStore':store,'WDate':'','WFileType':file_type}).encode()
  blob=allowlisted_read(self.opener,self.base+'/MainIO_Hok.aspx',(self.host,),data=body,limit=MAX_LISTING_BYTES)
  rows=parse_bina_listing(blob,self.base,self.chain['chainId'])
  if search=='Stores':return [row for row in rows if is_stores_file(row[1],self.chain['chainId'])]
  return [row for row in rows if not search or search in row[1]]
 def get(self,url):return allowlisted_read(self.opener,url,(self.host,))

class PublishedPricesPortal:
 def __init__(self,chain):
  self.chain=chain;self.base=chain['base'].rstrip('/');self.host=(urllib.parse.urlsplit(self.base).hostname or '').lower();self.hosts=(self.host,)
  self.directory=chain.get('directory','/')
  if self.directory!='/' and not re.fullmatch(r'/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*',self.directory):raise ValueError('Invalid published-prices directory')
  validate_source_url(self.base,self.hosts);jar=http.cookiejar.CookieJar();self.opener=allowlisted_opener(self.hosts,jar)
  page=self._read(self.base+'/login').decode('utf-8');match=re.search(r'name="csrftoken" content="([^"\s]+)"',page)
  if not match:raise ValueError('Public portal CSRF token missing')
  token=match[1];body=urllib.parse.urlencode({'username':chain['username'],'password':public_portal_password(chain),'csrftoken':token,'r':''}).encode()
  page=self._read(self.base+'/login/user',data=body,headers={'Referer':self.base+'/login','X-CSRFToken':token}).decode('utf-8')
  if 'Logged in as' not in page:raise ValueError('Public portal login failed')
  match=re.search(r'name="csrftoken" content="([^"\s]+)"',page)
  if not match:raise ValueError('Public portal CSRF token missing')
  self.token=match[1]
 def _read(self,url,data=None,headers=None,limit=MAX_LISTING_BYTES):return allowlisted_read(self.opener,url,self.hosts,data=data,headers=headers,limit=limit)
 def listing(self,search):
  result=[]
  for offset in range(0,10000,1000):
   payload={'cd':self.directory,'iDisplayStart':offset,'iDisplayLength':1000,'sEcho':1,'sSearch':search,'csrftoken':self.token}
   headers={'X-CSRFToken':self.token,'Referer':self.base+'/file'}
   blob=self._read(self.base+'/file/json/dir',data=urllib.parse.urlencode(payload).encode(),headers=headers)
   page=parse_published_listing(blob,self.base,self.chain['chainId'],self.directory);result.extend(page)
   raw=json.loads(blob.decode('utf-8-sig')).get('aaData',[])
   if len(raw)<1000:break
  return result
 def get(self,url):return self._read(url,limit=MAX_SOURCE_BYTES)

class HaziHinamPortal:
 HOSTS=('shop.hazi-hinam.co.il','hazihinamprod01.blob.core.windows.net')
 PATHS={'hazihinamprod01.blob.core.windows.net':('/regulatories/',)}
 def __init__(self,chain):self.chain=chain;self.base=chain['portal'];self.opener=allowlisted_opener(self.HOSTS);self.cache={}
 def listing(self,search):
  key='stores' if search=='Stores' else 'files'
  if key not in self.cache:
   first=self.base+('?t=3' if key=='stores' else '?p=1&s=&f=&t=&d=')
   blob=allowlisted_read(self.opener,first,self.HOSTS,limit=MAX_LISTING_BYTES);rows=parse_html_listing(blob,first,self.chain['chainId'],self.PATHS)
   if key=='files':
    pages=parse_html_page_numbers(blob,first,'shop.hazi-hinam.co.il')
    for page in sorted(pages-{1}):
     url=self.base+'?'+urllib.parse.urlencode({'p':page,'s':'','f':'','t':'','d':''})
     page_blob=allowlisted_read(self.opener,url,self.HOSTS,limit=MAX_LISTING_BYTES)
     rows.extend(parse_html_listing(page_blob,url,self.chain['chainId'],self.PATHS))
   self.cache[key]=list(dict.fromkeys(rows))
  rows=self.cache[key]
  if search=='Stores':return [row for row in rows if is_stores_file(row[1],self.chain['chainId'])]
  return [row for row in rows if not search or search in row[1]]
 def get(self,url):return allowlisted_read(self.opener,url,self.HOSTS)

class NetivHesedPortal:
 HOSTS=('app.netiv-hesed.com',);PATHS={'app.netiv-hesed.com':('/Prices/Download',)}
 def __init__(self,chain):self.chain=chain;self.base=chain['portal'];self.opener=allowlisted_opener(self.HOSTS)
 def listing(self,search):
  # The portal defaults to the calendar date, which is empty shortly after midnight.
  # Walk back a bounded week and stop at the newest published day containing the request.
  for days_back in range(8):
   query={'Date':(datetime.now(TZ).date()-timedelta(days=days_back)).isoformat()}
   query.update({'FileType':'Stores'} if search=='Stores' else {'Search':search})
   url=self.base+'?'+urllib.parse.urlencode(query);blob=allowlisted_read(self.opener,url,self.HOSTS,limit=MAX_LISTING_BYTES)
   rows=parse_html_listing(blob,url,self.chain['chainId'],self.PATHS)
   rows=[row for row in rows if is_stores_file(row[1],self.chain['chainId'])] if search=='Stores' else [row for row in rows if not search or search in row[1]]
   if rows:return rows
  return []
 def get(self,url):return allowlisted_read(self.opener,url,self.HOSTS)

class LaibPortal:
 def __init__(self,chain):
  self.chain=chain;self.host=chain['host'].lower();self.base='https://'+self.host
  validate_source_url(chain['portal'],(self.host,));self.opener=allowlisted_opener((self.host,))
 def listing(self,search):
  url=self.base+'/webapi/api/getfiles?'+urllib.parse.urlencode({'edi':self.chain['chainId']})
  blob=allowlisted_read(self.opener,url,(self.host,),limit=MAX_LISTING_BYTES);rows=parse_laib_listing(blob,self.base,self.chain['chainId'])
  if search=='Stores':return [row for row in rows if is_stores_file(row[1],self.chain['chainId'])]
  return [row for row in rows if not search or search in row[1]]
 def get(self,url):return allowlisted_read(self.opener,url,(self.host,))

class SuperPharmPortal:
 HOSTS=('prices.super-pharm.co.il',);PATHS={'prices.super-pharm.co.il':('/Download/',)};BUCKET='sp_transparency_output_prod_v2'
 def __init__(self,chain):
  self.chain=chain;self.base=chain['portal'];validate_source_url(self.base,self.HOSTS);self.opener=allowlisted_opener(self.HOSTS);self.stores={}
 def _page(self,query):
  url=self.base+'?'+urllib.parse.urlencode(query);blob=allowlisted_read(self.opener,url,self.HOSTS,limit=MAX_LISTING_BYTES)
  rows=parse_html_listing(blob,url,self.chain['chainId'],self.PATHS)
  for row_url,_ in rows:
   values=urllib.parse.parse_qs(urllib.parse.urlsplit(row_url).query)
   if values!={'bucketName':[self.BUCKET]}:raise ValueError('Unexpected Super-Pharm download query')
  return blob,rows
 def _store_names(self):
  if not self.stores:
   rows=self.listing('Stores')
   if not rows:raise ValueError('Super-Pharm Stores listing is empty')
   xml=decode_xml(self.get(max(rows,key=lambda row:row[1])[0]));root=ET.fromstring(xml);head=fields(root)
   if val(head,'ChainID')!=self.chain['chainId']:raise ValueError('Super-Pharm directory identity mismatch')
   stores={}
   for store in root.findall('.//Store'):
    data=fields(store);code=val(data,'StoreID');name=val(data,'StoreName')
    if code.isdigit() and name:stores[str(int(code))]=name
   self.stores=stores
  return self.stores
 def listing(self,search):
  if search=='Stores':
   _,rows=self._page({'Category-equals':'Stores'});return [row for row in rows if is_stores_file(row[1],self.chain['chainId'])]
  match=re.fullmatch(r'-(\d+)-',search or '')
  if not match:return []
  name=self._store_names().get(str(int(match[1])))
  if not name:raise ValueError('Super-Pharm store is absent from its signed directory')
  query={'BranchName-equals':name};blob,rows=self._page(query);pages=parse_grid_page_count(blob)
  for page in range(2,pages+1):
   _,page_rows=self._page({**query,'page':page});rows.extend(page_rows)
  return list(dict.fromkeys(row for row in rows if search in row[1]))
 def get(self,url):return allowlisted_read(self.opener,url,self.HOSTS)

class WoltPortal:
 HOSTS=('wm-gateway.wolt.com',);PATHS={'wm-gateway.wolt.com':('/isr-prices/public/v1/download/',)}
 def __init__(self,chain):
  self.chain=chain;self.index=chain['portal'];validate_source_url(self.index,self.HOSTS);self.opener=allowlisted_opener(self.HOSTS);self.pages=None
 def listing(self,search):
  if self.pages is None:
   blob=allowlisted_read(self.opener,self.index,self.HOSTS,limit=MAX_LISTING_BYTES);self.pages=parse_wolt_index(blob,self.index,self.HOSTS[0])
  for page in self.pages:
   blob=allowlisted_read(self.opener,page,self.HOSTS,limit=MAX_LISTING_BYTES);rows=parse_html_listing(blob,page,self.chain['chainId'],self.PATHS)
   rows=[row for row in rows if is_stores_file(row[1],self.chain['chainId'])] if search=='Stores' else [row for row in rows if not search or search in row[1]]
   if rows:return rows
  return []
 def get(self,url):return allowlisted_read(self.opener,url,self.HOSTS)

def source_adapter(chain):
 adapters={'bina':BinaPortal,'publishedprices':PublishedPricesPortal,'hazi':HaziHinamPortal,'netiv':NetivHesedPortal,'laib_safe':LaibPortal,'superpharm':SuperPharmPortal,'wolt':WoltPortal}
 if chain.get('adapter') not in adapters:raise ValueError('Unsupported verified source adapter')
 portal=adapters[chain['adapter']](chain)
 return portal.listing,portal.get

def fields(el):return {c.tag.lower():(c.text or '').strip() for c in el}
def val(d,*keys):return next((d[k.lower()] for k in keys if d.get(k.lower())), '')
def timestamp(name):
 m=re.search(r'(\d{8})-?(\d{4,6})(?:-\d{4,6})?(?:\.|$)',name)
 return (m[1]+m[2].ljust(6,'0')) if m else ''
def source_time(name):
 t=timestamp(name)
 return datetime.strptime(t,'%Y%m%d%H%M%S').replace(tzinfo=TZ).isoformat() if t else ''
def store_file(name,prefix,store):
 m=re.fullmatch(re.escape(prefix)+re.escape(str(store['chainId']))+r'-(?:\d+-)?(\d+)-\d{8}-?\d{4,6}(?:-\d{4,6})?\.(?:gz|xml)',name,re.I)
 return bool(m and int(m[1])==int(store['code']))
def parse_price(xml,store,source):
 r=ET.fromstring(xml);head=fields(r)
 if val(head,'ChainID')!=store['chainId'] or int(val(head,'StoreID'))!=int(store['code']):raise ValueError('Source branch identity mismatch')
 result={}
 for el in r.findall('.//Item'):
  d=fields(el);code=val(d,'ItemCode');itemtype=val(d,'ItemType');weighted=val(d,'bIsWeighted')=='1'
  if not code:continue
  key=code if itemtype=='1' and not weighted and len(code)>=8 else store['chainId']+':'+code
  if val(d,'ItemStatus')=='0':
   result[key]=None
   continue
  name=val(d,'ItemName','ItemNm');raw=val(d,'ItemPrice')
  try:cents=int((Decimal(raw)*100).quantize(Decimal('1')))
  except (InvalidOperation,ValueError):continue
  if not name or cents<=0:continue
  result[key]={'id':key,'barcode':code,'name':name,'brand':val(d,'ManufactureName','ManufacturerName'),'size':(val(d,'Quantity')+' '+val(d,'UnitQty')).strip(),'cents':cents,'weighted':weighted,'unitPrice':val(d,'UnitOfMeasurePrice'),'unit':val(d,'UnitOfMeasure'),'priceUpdatedAt':val(d,'PriceUpdateTime','PriceUpdateDate'),'sourceFile':source['file'],'sourcePublishedAt':source['publishedAt'],'itemType':itemtype}
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
  promotion_items=el.findall('.//PromotionItem') or el.findall('./PromotionItems/Item')
  for item in promotion_items:
   f=fields(item)
   if val(f,'ItemCode'):items.append({'barcode':val(f,'ItemCode'),'minQty':val(f,'MinQty') or val(d,'MinQty'),'maxQty':val(f,'MaxQty') or val(d,'MaxQty'),'discountedPrice':val(f,'DiscountedPrice') or val(d,'DiscountedPrice'),'discountRate':val(f,'DiscountRate') or val(d,'DiscountRate'),'rewardType':val(f,'RewardType') or val(d,'RewardType')})
  if pid:
   extra=el.find('./AdditionalRestrictions');extra_fields=fields(extra) if extra is not None else {}
   club=val(d,'ClubID') or val(extra_fields,'ClubID')
   promo={'id':pid,'description':val(d,'PromotionDescription'),'start':start,'end':end,'club':club,'coupon':(val(d,'AdditionalIsCoupon') or val(extra_fields,'AdditionalIsCoupon'))=='1','restrictions':val(d,'AdditionalRestrictions','Remarks') or val(extra_fields,'Remarks'),'items':items,'sourceFile':source['file'],'sourcePublishedAt':source['publishedAt']}
   if pid in result:
    merged=result[pid]['items'][:]
    merged.extend(item for item in items if item not in merged)
    promo['items']=merged
   result[pid]=promo
 return result

def decode_xml(blob,limit=MAX_XML_BYTES):
 if blob[:2]==b'\x1f\x8b':
  with gzip.GzipFile(fileobj=io.BytesIO(blob)) as stream:xml=stream.read(limit+1)
 elif blob[:4] in (b'PK\x03\x04',b'PK\x05\x06',b'PK\x07\x08'):
  try:
   with zipfile.ZipFile(io.BytesIO(blob)) as archive:
    entries=[entry for entry in archive.infolist() if not entry.is_dir()]
    if len(entries)!=1:raise ValueError('Unsupported ZIP source')
    entry=entries[0];name=entry.filename
    if entry.flag_bits & 1 or entry.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED):raise ValueError('Unsupported ZIP source')
    if name!=Path(name).name or not name.lower().endswith('.xml') or entry.file_size>limit:raise ValueError('Unsupported ZIP source')
    with archive.open(entry) as stream:xml=stream.read(limit+1)
  except (zipfile.BadZipFile,RuntimeError) as e:raise ValueError('Unsupported ZIP source') from e
 else:xml=blob
 if len(xml)>limit or re.search(br'<!\s*(?:DOCTYPE|ENTITY)',xml.replace(b'\x00',b''),re.I):raise ValueError('Unsupported XML')
 ET.fromstring(xml)
 return xml

def read_source(path):
 with path.open('rb') as stream:blob=stream.read(MAX_SOURCE_BYTES+1)
 if len(blob)>MAX_SOURCE_BYTES:raise ValueError('Cached source file exceeds size limit')
 return blob

def cached_xml(url,name,fetcher=get):
 if not re.fullmatch(r'[\w.-]+',name):raise ValueError('Invalid source filename')
 p=DATA/'raw'/name
 if not p.exists():
  b=fetcher(url)
  if len(b)>MAX_SOURCE_BYTES:raise ValueError('Source file exceeds size limit')
  x=decode_xml(b);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_bytes(b);os.replace(tmp,p)
 else:b=read_source(p);x=decode_xml(b)
 return x,hashlib.sha256(b).hexdigest()

def shuf_listing(code,category):
 u=f'https://prices.shufersal.co.il/FileObject/UpdateCategory?catID={category}&storeId={int(code)}';s=get(u).decode('utf-8-sig')
 return [(html.unescape(u),urllib.parse.urlparse(html.unescape(u)).path.split('/')[-1]) for u in re.findall(r'href="(https[^\"]+\.gz[^\"]*)"',s)]
def carrefour_listing():
 s=get('https://prices.carrefour.co.il/').decode('utf-8-sig');day=re.search(r"const path = '([^']+)'",s)[1];files=json.loads(re.search(r'const files = (\[.*?\]);',s,re.S)[1]);names={v:html.unescape(n) for v,n in re.findall(r'<option value="(\d+)">(.*?)</option>',s)}
 return [(f'https://prices.carrefour.co.il/{day}/{f["name"]}',f['name']) for f in files],names

def sync_store(store,listing=None,fetcher=get):
 path=DATA/'stores'/(store['id']+'.json');pending_path=DATA/'pending'/(store['id']+'.json');old=json.loads(path.read_text()) if path.exists() else {};state={**old,**store,'lastAttemptAt':now()};sources=old.get('sources',{}).copy();prices=old.get('products',{}).copy();promos=old.get('promotions',{}).copy();baselines=old.get('baselines',{}).copy()
 try:pending=json.loads(pending_path.read_text()) if pending_path.exists() else {}
 except (ValueError,OSError):pending={}
 if not isinstance(pending,dict):pending={}
 try:
  if store['chain']=='shufersal':
   lists={k:shuf_listing(store['code'],c) for k,c in [('PriceFull',2),('Price',1),('PromoFull',4),('Promo',3)]}
  else:
   relevant=[x for x in listing if (m:=re.match(r'^(?:PriceFull|Price|PromoFull|Promo)\d+-(?:\d+-)?(\d+)-\d{8}-?\d{4,6}(?:-\d{4,6})?\.',x[1])) and int(m[1])==int(store['code'])];lists={k:[x for x in relevant if x[1].startswith(k) and (k.endswith('Full') or not x[1].startswith(k+'Full'))] for k in ['PriceFull','Price','PromoFull','Promo']}
  for full,delta,kind,parser in [('PriceFull','Price','price',parse_price),('PromoFull','Promo','promo',parse_promos)]:
   order=lambda name:(timestamp(name),name)
   current_full={name:url for url,name in lists[full]}
   pending_full={name:entry for name,entry in pending.items() if isinstance(entry,dict) and entry.get('kind')==kind and store_file(name,full,store)}
   full_names=set(current_full)
   full_names.update(name for name in sources if store_file(name,full,store))
   full_names.update(pending_full)
   if baselines.get(kind) and store_file(baselines[kind],full,store):full_names.add(baselines[kind])
   fullfiles=sorted(((current_full.get(name) or pending_full.get(name,{}).get('url',''),name) for name in full_names),key=lambda x:order(x[1]));base=fullfiles[-1:]
   if kind=='price' and not base and not old.get('products'):raise ValueError('No full price baseline')
   base_t=timestamp(base[0][1]) if base else ''
   base_name=base[0][1] if base else None
   current_delta={name:url for url,name in lists[delta]}
   pending_delta={name:entry for name,entry in pending.items() if isinstance(entry,dict) and entry.get('kind')==kind and store_file(name,delta,store)}
   delta_names=set(current_delta)
   delta_names.update(name for name in sources if store_file(name,delta,store))
   delta_names.update(pending_delta)
   deltas=sorted(((current_delta.get(name) or pending_delta.get(name,{}).get('url',''),name) for name in delta_names if timestamp(name)>=base_t),key=lambda x:order(x[1]))
   applied_names=[name for name in sources if name.startswith(delta) and not name.startswith(full) and timestamp(name)>=base_t]
   applied=[order(name) for name in applied_names]
   new_delta_orders=[order(name) for _,name in deltas if name not in sources]
   out_of_order=bool(applied and new_delta_orders and min(new_delta_orders)<max(applied))
   rebuild=baselines.get(kind)!=base_name or out_of_order or bool(base_name and base_name not in sources)
   queue=base+deltas
   if rebuild:
    if kind=='price':prices={}
    else:promos={}
   for url,name in queue:
    if name in sources and not rebuild:continue
    xml,sha=cached_xml(url,name,fetcher);existing=sources.get(name);pending_entry=pending.get(name,{})
    recovered=pending_entry.get('source',{}) if isinstance(pending_entry,dict) else {}
    expected=(existing or recovered).get('sha256')
    if expected and expected!=sha:raise ValueError('Cached source hash mismatch')
    src=existing or recovered or {'file':name,'publishedAt':source_time(name),'fetchedAt':now(),'sha256':sha,'portal':store['portal']};parsed=parser(xml,store,src)
    if not existing:
     pending[name]={'kind':kind,'url':url,'source':src};save(pending_path,pending)
    if kind=='price':
     for key,value in parsed.items():
      if value is None:prices.pop(key,None)
      else:prices[key]=value
    else:
     promos.update(parsed)
    sources[name]=src
   baselines[kind]=base_name
  if not prices:raise ValueError('Empty price snapshot')
  state.update(products=prices,promotions=promos,sources=sources,baselines=baselines,lastSuccessAt=now(),error=None)
  save(path,state)
  if pending_path.exists():save(pending_path,{})
  print(store['id'],len(prices),'products,',len(promos),'promotions',flush=True)
 except Exception as e:
  state['error']=str(e);save(path,state);print(store['id'],'ERROR',str(e),flush=True)
 return {k:v for k,v in state.items() if k not in ['products','promotions','sources']}

def main():
 from directory import CHAINS,adapter,refresh
 from build_db import build_database
 started=now();errors=[];database=None
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
 try:database=build_database()
 except Exception as e:errors.append('database: '+str(e))
 progress.update(running=False,finishedAt=now());save(DATA/'progress.json',progress)
 save(DATA/'status.json',{'startedAt':started,'finishedAt':now(),'intervalMinutes':15,'stores':results,'errors':errors,'database':database})
if __name__=='__main__':
 import fcntl
 with open(DATA/'.sync.lock','w') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:print('Another sync is running',flush=True)
  else:main()
