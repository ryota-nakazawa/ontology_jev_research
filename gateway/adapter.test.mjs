import test from 'node:test';
import assert from 'node:assert/strict';
import { toGatewayQuestions, toPythonAnswers } from './adapter.mjs';

test('converts noul while preserving structured instructions and choice criteria', () => {
 const result = toGatewayQuestions({jump:{type:'noul',instructions:'Jump?'},action:{type:'choice',instructions:{goal:'survive'},criteria:{left:'Left',right:'Right'}}});
 assert.deepEqual(result.jump,{type:'boolean',instructions:'Jump?'});
 assert.deepEqual(result.action,{type:'choice',instructions:{goal:'survive'},criteria:{left:'Left',right:'Right'}});
});
test('maps probability back to noul and does not invent confidence', () => {
 const result=toPythonAnswers({jump:{type:'boolean',probability:0.8},action:{type:'choice',choice:'right',probabilities:{left:0.2,right:0.8}},danger:{type:'score',score:1.5,probabilities:{0:0,1:0.5,2:0.5}}});
 assert.deepEqual(result.jump,{type:'noul',noul:0.8});
 assert.equal(result.action.confidence,null);
 assert.equal(result.action.choice,'right');
 assert.deepEqual(result.action.probabilities,{left:0.2,right:0.8});
 assert.equal(result.danger.score,1.5);
});
test('unsupported questions fail before requesting the gateway', () => {
 assert.throws(()=>toGatewayQuestions({x:{type:'text',instructions:'x'}}),/Unsupported/);
});
