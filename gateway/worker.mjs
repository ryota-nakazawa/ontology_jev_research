import { createInterface } from 'node:readline';
import { experimental_evaluate as evaluate } from 'ai';
import { toGatewayQuestions, toPythonAnswers } from './adapter.mjs';
import { createSystemOne } from './systemone.mjs';

// Two routes to the same model. The direct one halves the round trip and is the
// only one that returns a per-answer confidence; the gateway nulls it out. The
// Python side already speaks noul/choice/score, which are the direct API's own
// names, so that route needs no translation in either direction.
export function chooseRoute(env = process.env, preference = 'auto') {
  if (!['auto', 'direct'].includes(preference)) throw new Error('Unknown route preference');
  if (env.TYPESAFE_API_KEY) {
    const call = createSystemOne({ apiKey: env.TYPESAFE_API_KEY, maxRetries: 0 });
    return {
      name: 'direct',
      run: async request => {
        const result = await call({ state: request.state, questions: request.questions, timeoutMs: 20000 });
        return { answers: result.answers, usage: result.usage };
      },
    };
  }
  if (preference !== 'direct' && env.AI_GATEWAY_API_KEY) {
    return {
      name: 'gateway',
      run: async request => {
        const result = await evaluate({ model: 'typesafe-ai/jev', state: request.state,
          questions: toGatewayQuestions(request.questions), maxRetries: 0,
          abortSignal: AbortSignal.timeout(20000) });
        return { answers: toPythonAnswers(result.answers), usage: result.usage };
      },
    };
  }
  return null;
}

// A failure is reported as a message the player can act on, never as the raw
// error: the key travels in the request headers.
export function explain(error, routeName) {
  const status = Number.isInteger(error?.statusCode) ? error.statusCode : null;
  if (routeName === 'direct') {
    if (status === 401) return { status, message: 'TypeSafe rejected the API key. Check TYPESAFE_API_KEY in .env.' };
    if (status === 422) return { status, message: 'TypeSafe rejected the request shape. The question map is malformed.' };
    if (status === 429) return { status, message: 'TypeSafe rate limit reached. Try again shortly.' };
    if (status === 529) return { status, message: 'TypeSafe is overloaded. Try again shortly.' };
    return { status, message: 'TypeSafe System One request failed.' };
  }
  if (status === 403 && /credit card/i.test(String(error?.message)))
    return { status, message: 'Vercel requires a valid credit card on file, including to unlock free credits. Add it in the Vercel AI Gateway dashboard.' };
  if (status === 401) return { status, message: 'Vercel rejected the API key. Check AI_GATEWAY_API_KEY in .env.' };
  if (status === 402) return { status, message: 'Vercel credits are unavailable. Check the AI Gateway dashboard.' };
  if (status === 429) return { status, message: 'Vercel rate limit reached. Try again later.' };
  return { status, message: 'Vercel AI Gateway request failed.' };
}

async function main() {
  const preference = process.argv.includes('--direct') ? 'direct' : 'auto';
  const route = chooseRoute(process.env, preference);
  // stdout is a JSON Lines protocol. Never print credentials or raw SDK errors.
  const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
  for await (const line of lines) {
    if (!route) { console.log(JSON.stringify({ error: { status: 401, message: preference === 'direct' ? 'Direct connection requires TYPESAFE_API_KEY in .env.' : 'No API key: set TYPESAFE_API_KEY or AI_GATEWAY_API_KEY in .env.' } })); continue; }
    try {
      const request = JSON.parse(line);
      const { answers, usage } = await route.run(request);
      console.log(JSON.stringify({ answers, usage, route: route.name }));
    } catch (error) {
      console.log(JSON.stringify({ error: explain(error, route.name) }));
    }
  }
}

if (process.argv[1] && import.meta.url.endsWith(process.argv[1].split('/').pop())) main();
