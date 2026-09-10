import http from 'node:http';
import {readFile,writeFile,rename} from 'node:fs/promises';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {catalog,loadCatalog,listProducts,filteredProduct,compareBasket} from './catalog.mjs';
const root=path.resolve('dist');
const readJSON=async(file,fallback)=>{try{return JSON.parse(await readFile(file,'utf8'));}catch{return fallback;}};
let directory=await readJSON('data/directory.json',{stores:[],chains:[],localities:[]});
let selection=(await readJSON('data/selection.json',{stores:[]})).stores;
if(!selection.length){await loadCatalog();selection=catalog.stores.map(s=>s.id);}
await loadCatalog(selection);
let reloadQueue=Promise.resolve();
function reload(){reloadQueue=reloadQueue.catch(()=>{}).then(()=>loadCatalog(selection));return reloadQueue;}
let syncing=false,pending=false,syncStores=[],lastSync=(await readJSON('data/status.json',{})).finishedAt||null,syncError=null,revision=0;
let nextCheckAt=new Date(Date.now()+15*60*1000).toISOString();
function activeStores(value){
 const ids=Array.isArray(value)?value:String(value||'').split(',').filter(Boolean);
 if(!ids.length)return [...selection];
 if(new Set(ids).size!==ids.length||!ids.every(id=>selection.includes(id)))throw Error('Store is not in the active selection');
 return ids;
}
function basketRows(items,ids){
 const rows=compareBasket(items,ids),seen=new Set(rows.map(s=>s.id));
 for(const id of ids){
  if(seen.has(id))continue;
  const store=directory.stores.find(s=>s.id===id);
  if(store)rows.push({id:store.id,chain:store.chain,chainName:store.chainName,name:store.name,city:store.city,portal:store.portal,cents:0,missing:items.map(i=>i.id),complete:false,stale:true,pending:true});
 }
 return rows;
}
async function sync(){
 if(syncing){pending=true;return;}
 syncing=true;syncStores=[...selection];syncError=null;
 const p=spawn(process.env.PYTHON||'/usr/bin/python3',['-B','scripts/sync.py'],{cwd:process.cwd(),stdio:['ignore','pipe','pipe']});let errors='';
 p.stdout.on('data',b=>process.stdout.write(b));p.stderr.on('data',b=>{errors+=b.toString();});
 p.on('error',e=>{syncing=false;syncError=e.message;});
 p.on('close',async code=>{try{syncError=code?errors.slice(-1500):null;lastSync=(await readJSON('data/status.json',{})).finishedAt;await reload();directory=await readJSON('data/directory.json',directory);revision++;}catch(e){syncError=e.message;}finally{syncing=false;if(pending){pending=false;sync();}}});
}
setInterval(()=>{nextCheckAt=new Date(Date.now()+15*60*1000).toISOString();sync();},15*60*1000);
if(!lastSync||Date.now()-Date.parse(lastSync)>15*60*1000)sync();
const server=http.createServer(async(req,res)=>{
 const json=(data,status=200)=>{res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});res.end(JSON.stringify(data));};
 try{
 const url=new URL(req.url,'http://localhost');
 const body=async()=>{let b='';for await(const chunk of req){b+=chunk;if(b.length>15000)throw Error('Request too large');}return JSON.parse(b);};
 if(url.pathname==='/api/status'){
  const status=await readJSON('data/status.json',{}),progress=await readJSON('data/progress.json',{});
  const currentSync=syncStores.length===selection.length&&syncStores.every(id=>selection.includes(id));
  return json({stores:catalog.stores,selectedStores:selection,productCount:catalog.products.size,storage:catalog.storage,databaseUpdatedAt:catalog.databaseUpdatedAt,directoryUpdatedAt:directory.updatedAt||null,lastSync,revision,syncing,syncError:syncError||(status.errors||[]).join('; ')||null,intervalMinutes:15,nextCheckAt,progress:syncing?(currentSync?{done:progress.done||0,total:progress.total||selection.length}:{done:0,total:selection.length,pending:true}):null,results:status.stores||[]});
 }
 if(url.pathname==='/api/directory')return json(directory);
 if(url.pathname==='/api/selection'&&req.method==='POST'){
  // Local browser only; do not let other websites change the active comparison.
  if(req.headers.origin&&!['http://localhost:3000','http://127.0.0.1:3000'].includes(req.headers.origin))return json({error:'Invalid origin'},403);
  const input=await body(),ids=input.stores;
  if(!Array.isArray(ids)||!ids.length||ids.length>24||new Set(ids).size!==ids.length||!ids.every(id=>directory.stores.some(s=>s.id===id)))return json({error:'יש לבחור בין סניף אחד ל־24 סניפים מהרשימה'},400);
  await writeFile('data/selection.json.tmp',JSON.stringify({stores:ids}));await rename('data/selection.json.tmp','data/selection.json');selection=ids;await reload();revision++;sync();return json({stores:selection,syncing:true},202);
 }
 if(url.pathname==='/api/products'){const selected=activeStores(url.searchParams.get('stores'));return json(listProducts({q:(url.searchParams.get('q')||'').slice(0,200),stores:selected,promos:url.searchParams.get('promos')==='1',sort:url.searchParams.get('sort'),offset:Math.max(0,Number(url.searchParams.get('offset'))||0)}));}
 if(url.pathname==='/api/product'){const selected=activeStores(url.searchParams.get('stores')),p=catalog.products.get(url.searchParams.get('id'));return json(p?filteredProduct(p,selected):{error:'Product not found'},p?200:404);}
 if(url.pathname==='/api/basket'&&req.method==='POST'){const input=await body(),selected=activeStores(input.stores);return json({stores:basketRows(input.items,selected)});}
 if(url.pathname==='/api/source'){const file=url.searchParams.get('file')||'';if(!/^(?:Price|Promo)[\w.-]+\.(?:gz|xml)$/i.test(file))return json({error:'Invalid source'},400);const b=await readFile(path.join('data/raw',file)),zipped=b.length>=4&&b[0]===0x50&&b[1]===0x4b;res.writeHead(200,{'Content-Type':zipped?'application/zip':file.toLowerCase().endsWith('.gz')?'application/gzip':'application/xml','Content-Disposition':`attachment; filename="${file}"`});return res.end(b);}
 if(req.method!=='GET'&&req.method!=='HEAD')return json({error:'Method not allowed'},405);
 const file=path.resolve(root,'.'+decodeURIComponent(url.pathname==='/'?'/index.html':url.pathname));if(!file.startsWith(root+path.sep))return json({error:'Forbidden'},403);
 const data=await readFile(file);res.writeHead(200,{'Content-Type':file.endsWith('.html')?'text/html; charset=utf-8':file.endsWith('.css')?'text/css':file.endsWith('.js')?'text/javascript':'application/octet-stream','Cache-Control':'no-cache'});res.end(data);
 }catch(e){json({error:e.code==='ENOENT'?'Not found':e.message||'Invalid request'},e.code==='ENOENT'?404:400);}
});
server.listen(3000,'127.0.0.1',()=>console.log('Local: http://localhost:3000'));
