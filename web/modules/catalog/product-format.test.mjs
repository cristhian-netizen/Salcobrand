import test from 'node:test';
import assert from 'node:assert/strict';
import {unitPrice,priceUnit} from './product-format.mjs';
test('unit prices do not apply the kilogram/litre conversion to units',()=>{
 for(const [saleUnit,quantity,price,expected,unit] of [['unidad',2,4990,2495,'unidad'],['gramos',100,1000,10000,'kg'],['ml',50,1000,20000,'litro'],['unidad',5,0,0,'unidad']]){
  assert.equal(unitPrice({saleUnit,quantity,price}),expected);assert.equal(priceUnit(saleUnit),unit);
 }
 assert.equal(unitPrice({saleUnit:'unidad',quantity:1,price:null}),null);
});
