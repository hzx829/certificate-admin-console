import test from 'node:test';
import assert from 'node:assert/strict';
import {loadPending, savePending, clearPending} from './pending.js';

const alice = {email:'alice@east.test',tenant:'East'};
const bob = {email:'bob@west.test',tenant:'West'};
const operation = {key:'original-key',payload:{course_id:101}};
function memory() {
  const values = new Map();
  return {getItem:k=>values.get(k)??null, setItem:(k,v)=>values.set(k,v), removeItem:k=>values.delete(k), values};
}
test('persist the original key and payload across reloads',()=>{
  const storage = memory(); savePending(alice,operation,storage);
  assert.deepEqual(loadPending(alice,storage),operation);
  assert.notEqual(loadPending(alice,storage),operation);
});
test('actor switch keeps separate pending operations',()=>{
  const storage=memory(); savePending(alice,operation,storage);
  assert.equal(loadPending(bob,storage),null);
  const west={key:'west-key',payload:{course_id:201}};
  savePending(bob,west,storage);
  assert.deepEqual(loadPending(alice,storage),operation);
  clearPending(alice,operation.key,storage);
  assert.deepEqual(loadPending(bob,storage),west);
});
test('clear only the confirmed operation',()=>{
  const storage=memory(); savePending(alice,operation,storage);
  clearPending(alice,'different-key',storage);
  assert.deepEqual(loadPending(alice,storage),operation);
  clearPending(alice,operation.key,storage);
  assert.equal(loadPending(alice,storage),null);
});
test('storage failures are surfaced, never silently replaced with a new operation',()=>{
  const storage=memory();
  storage.setItem=()=>{throw new Error('storage denied');};
  assert.throws(()=>savePending(alice,operation,storage));
  storage.getItem=()=>{throw new Error('storage denied');};
  assert.throws(()=>loadPending(alice,storage));
});
test('malformed saved requests are rejected and retained for diagnosis',()=>{
  const storage=memory(); savePending(alice,operation,storage);
  const key=[...storage.values.keys()][0];
  for(const invalid of ['broken JSON',JSON.stringify({key:'x',payload:{course_id:'101'}}),JSON.stringify({key:'x',payload:{course_id:101,extra:true}})]) {
    storage.values.set(key,invalid);
    assert.throws(()=>loadPending(alice,storage));
    assert.equal(storage.values.get(key),invalid);
  }
});
