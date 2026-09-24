import test from 'node:test';
import assert from 'node:assert/strict';
import {chooseRoute, explain} from './worker.mjs';

test('the direct route is preferred, the gateway is the fallback, neither key means no route', () => {
  assert.equal(chooseRoute({TYPESAFE_API_KEY: 'k', AI_GATEWAY_API_KEY: 'g'}).name, 'direct');
  assert.equal(chooseRoute({AI_GATEWAY_API_KEY: 'g'}).name, 'gateway');
  assert.equal(chooseRoute({TYPESAFE_API_KEY: 'k'}).name, 'direct');
  assert.equal(chooseRoute({}), null);
});

test('a failure is explained for the route that actually ran', () => {
  assert.match(explain({statusCode: 401}, 'direct').message, /TYPESAFE_API_KEY/);
  assert.match(explain({statusCode: 401}, 'gateway').message, /AI_GATEWAY_API_KEY/);
  assert.match(explain({statusCode: 529}, 'direct').message, /overloaded/i);
  assert.match(explain({statusCode: 403, message: 'credit card required'}, 'gateway').message, /credit card/i);
  assert.equal(explain({}, 'direct').status, null, 'an unknown failure still reports a status field');
});

test('the key never reaches the message a player is shown', () => {
  const key = 'sk-live-must-not-leak';
  const shown = explain({statusCode: 401, message: `bad key ${key}`}, 'direct');
  assert.ok(!JSON.stringify(shown).includes(key));
});

test('explicit direct mode never falls back to Vercel', () => {
  assert.equal(chooseRoute({AI_GATEWAY_API_KEY: 'g'}, 'direct'), null);
  assert.equal(chooseRoute({TYPESAFE_API_KEY: 'k', AI_GATEWAY_API_KEY: 'g'}, 'direct').name, 'direct');
});
