import test from 'node:test';
import assert from 'node:assert/strict';
import {catalog,listProducts,compareBasket,activePromos} from '../catalog.mjs';

const product={id:'7290004131074',barcode:'7290004131074',name:'חלב בדיקה',brand:'יצרן',size:'1 ליטר',weighted:false,offers:[
 {storeId:'chain-001',chain:'chain',chainName:'רשת א',storeName:'סניף א',city:'חיפה',cents:735,sourceFile:'PriceFull-test.xml',sourceHash:'abc',sourcePublishedAt:new Date().toISOString(),promotions:[]},
 {storeId:'chain-002',chain:'chain',chainName:'רשת א',storeName:'סניף ב',city:'אילת',cents:720,sourceFile:'PriceFull-test.xml',sourceHash:'def',sourcePublishedAt:new Date().toISOString(),promotions:[]}
]};
catalog.products=new Map([[product.id,product]]);
catalog.stores=product.offers.map(o=>({id:o.storeId,chain:o.chain,chainName:o.chainName,name:o.storeName,city:o.city}));

test('published offers retain source evidence',()=>{const result=listProducts({q:product.barcode});assert.equal(result.products.length,1);for(const o of result.products[0].offers){assert(o.sourceHash);assert(o.sourceFile);}});
test('basket totals are integer cents and incomplete branches cannot win',()=>{const rows=compareBasket([{id:product.id,quantity:3}]);for(const r of rows)assert.equal(r.cents,product.offers.find(o=>o.storeId===r.id).cents*3);const incomplete=compareBasket([{id:'missing-barcode',quantity:1}]);assert(incomplete.every(r=>!r.complete&&r.missing.length===1));});
test('invalid quantities and duplicate lines are rejected',()=>{assert.throws(()=>compareBasket([{id:'a',quantity:-1}]));assert.throws(()=>compareBasket([{id:'a',quantity:1},{id:'a',quantity:2}]));});
test('only currently valid promotions are exposed',()=>{const n=Date.now(),iso=d=>new Date(d).toISOString();const o={promotions:[{id:'active',start:iso(n-1000),end:iso(n+1000)},{id:'expired',start:iso(n-2000),end:iso(n-1)},{id:'future',start:iso(n+1),end:iso(n+2000)}]};assert.deepEqual(activePromos(o,n).map(p=>p.id),['active']);});
test('branch selection strictly limits offers and basket results',()=>{const id='chain-001';assert(listProducts({q:product.barcode,stores:[id]}).products[0].offers.every(o=>o.storeId===id));assert.equal(compareBasket([{id:product.id,quantity:1}],[id]).length,1);});
