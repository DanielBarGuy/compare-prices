"""Public read-only Cerberus price portal. Never sends write/delete operations."""
import urllib.request,urllib.parse,http.cookiejar,re,json
BASE='https://url.publishedprices.co.il'
class Cerberus:
 def __init__(self,username,password=""):
  self.op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
  page=self.get(BASE+'/login').decode();token=re.search('name="csrftoken" content="([^"]+)"',page)[1]
  body=urllib.parse.urlencode({'username':username,'password':password,'csrftoken':token,'r':''}).encode()
  req=urllib.request.Request(BASE+'/login/user',data=body,headers={'Referer':BASE+'/login','X-CSRFToken':token})
  page=self.op.open(req,timeout=30).read().decode()
  if 'Logged in as' not in page:raise ValueError('Public portal login failed')
  self.token=re.search('name="csrftoken" content="([^"]+)"',page)[1]
 def get(self,url):
  with self.op.open(url,timeout=35) as r:return r.read(40_000_001)
 def listing(self,search):
  result=[]
  for offset in range(0,10000,1000):
   payload={'cd':'/','iDisplayStart':offset,'iDisplayLength':1000,'sEcho':1,'sSearch':search,'csrftoken':self.token}
   req=urllib.request.Request(BASE+'/file/json/dir',data=urllib.parse.urlencode(payload).encode(),headers={'X-CSRFToken':self.token,'Referer':BASE+'/file'})
   j=json.load(self.op.open(req,timeout=30));rows=j.get('aaData',[])
   result.extend((BASE+'/file/d/'+urllib.parse.quote(f['name']),f['name']) for f in rows if f.get('type')=='file')
   if len(rows)<1000:break
  return result
