import test from 'node:test';
import assert from 'node:assert/strict';
import {createSystemOne, checkQuestions, checkAnswers, SystemOneError} from './systemone.mjs';

const KEY = 'sk-test-must-never-be-logged';
const QUESTIONS = {
  drop: {type: 'choice', instructions: 'Pick a column.', criteria: {x0: {note: 'left'}, x1: {note: 'right'}}},
};
const ANSWER = {drop: {type: 'choice', choice: 'x1', probabilities: {x0: 0.3, x1: 0.7}, confidence: 0.64}};
const ok = (body = {model: 'jev-1.13.0', answers: ANSWER, usage: {input_tokens: 10, output_tokens: 4}}) =>
  ({ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body)});
const fail = (status, text = 'busy') => ({ok: false, status, text: async () => text, json: async () => ({})});

test('a question map is checked before anything is sent', () => {
  assert.throws(() => checkQuestions({}), /No questions/);
  assert.throws(() => checkQuestions({a: {type: 'essay'}}), /Unsupported question type/);
  assert.throws(() => checkQuestions({a: {type: 'choice', criteria: {only: 1}}}), /at least two options/);
  assert.throws(() => checkQuestions({a: {type: 'score', criteria: {}}}), /ordered list/);
  assert.deepEqual(checkQuestions(QUESTIONS), QUESTIONS);
});

test('an answer outside the offered options is refused, because a move is made from it', () => {
  assert.throws(() => checkAnswers({drop: {type: 'choice', choice: 'x9'}}, QUESTIONS), /not one of the offered/);
  assert.throws(() => checkAnswers({drop: {type: 'noul', noul: 1}}, QUESTIONS), /mistyped/);
  assert.throws(() => checkAnswers(null, QUESTIONS), /no answers/);
  assert.throws(() => checkAnswers({a: {type: 'noul', noul: 2}}, {a: {type: 'noul'}}), /not a probability/);
});

test('a successful call returns the answer, the confidence and the usage', async () => {
  let seen = null;
  const evaluate = createSystemOne({apiKey: KEY, fetchImpl: async (url, init) => {seen = {url, init}; return ok();}});
  const result = await evaluate({state: {board: []}, questions: QUESTIONS});
  assert.equal(result.answers.drop.choice, 'x1');
  assert.equal(result.answers.drop.confidence, 0.64, 'the direct route carries confidence the gateway drops');
  assert.deepEqual(result.usage, {input_tokens: 10, output_tokens: 4});
  assert.equal(seen.url, 'https://api.typesafe.ai/v1/systemone');
  assert.equal(seen.init.headers.Authorization, `Bearer ${KEY}`);
  const sent = JSON.parse(seen.init.body);
  assert.equal(sent.model, 'jev-latest');
  assert.equal(sent.questions.drop.type, 'choice', 'noul/choice/score are sent as written, not translated');
});

test('back-pressure is retried with growing waits, other failures are not', async () => {
  const waits = [];
  let calls = 0;
  const evaluate = createSystemOne({apiKey: KEY, wait: async ms => {waits.push(ms);},
    fetchImpl: async () => (++calls < 3 ? fail(529) : ok())});
  const result = await evaluate({state: {}, questions: QUESTIONS});
  assert.equal(result.answers.drop.choice, 'x1');
  assert.deepEqual(waits, [500, 1000], 'each retry waits longer than the last');

  let once = 0;
  const rejected = createSystemOne({apiKey: KEY, wait: async () => {},
    fetchImpl: async () => {once++; return fail(422, 'bad request');}});
  await assert.rejects(rejected({state: {}, questions: QUESTIONS}), e => e.statusCode === 422);
  assert.equal(once, 1, 'a request the server rejected is not sent again');
});

test('the key never appears in an error, however the call fails', async () => {
  const boom = createSystemOne({apiKey: KEY, maxRetries: 0, wait: async () => {},
    fetchImpl: async () => {throw Object.assign(new Error(`connect failed using ${KEY}`), {name: 'TypeError'});}});
  const error = await boom({state: {}, questions: QUESTIONS}).catch(e => e);
  assert.ok(error instanceof SystemOneError);
  assert.ok(!JSON.stringify({m: error.message, d: error.detail}).includes(KEY), 'no key in the message');
});

test('a missing key fails at construction, not mid-game', () => {
  assert.throws(() => createSystemOne({apiKey: ''}), /TYPESAFE_API_KEY/);
});

test('an abort stops the call instead of retrying it', async () => {
  const controller = new AbortController();
  const evaluate = createSystemOne({apiKey: KEY, wait: async () => {},
    fetchImpl: async () => {controller.abort(); throw Object.assign(new Error('aborted'), {name: 'AbortError'});}});
  await assert.rejects(evaluate({state: {}, questions: QUESTIONS, abortSignal: controller.signal}), /Cancelled/);
});
