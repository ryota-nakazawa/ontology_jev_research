// Direct System One client. The gateway route reaches the same model through
// Vercel; this one talks to TypeSafe itself, which drops a hop and returns the
// per-answer confidence the gateway route does not carry.
//
// Question types are sent as written: this codebase already speaks `noul`,
// which is the API's own name, so nothing is translated on the way out.
const ENDPOINT = 'https://api.typesafe.ai/v1/systemone';
const TYPES = ['noul', 'choice', 'score'];
// 429 and 529 are the documented back-pressure codes; 5xx is a transient fault.
const retriable = status => status === 429 || status === 529 || (status >= 500 && status < 600);
const backoff = attempt => Math.min(8000, 500 * 2 ** attempt);

export class SystemOneError extends Error {
  constructor(message, {statusCode = null, cause = null} = {}) {
    super(message);
    this.name = 'SystemOneError';
    this.statusCode = statusCode;
    this.cause = cause;
  }
}

export function checkQuestions(questions) {
  const entries = Object.entries(questions ?? {});
  if (!entries.length) throw new SystemOneError('No questions to evaluate');
  for (const [id, q] of entries) {
    if (!TYPES.includes(q?.type)) throw new SystemOneError(`Unsupported question type for "${id}"`);
    if (q.type === 'choice' && Object.keys(q.criteria ?? {}).length < 2)
      throw new SystemOneError(`Choice question "${id}" needs at least two options`);
    if (q.type === 'score' && !Array.isArray(q.criteria))
      throw new SystemOneError(`Score question "${id}" needs an ordered list of levels`);
  }
  return questions;
}

// An answer the caller can act on, or nothing. A malformed choice is rejected
// rather than passed through, because a drop is made from it.
export function checkAnswers(answers, questions) {
  if (!answers || typeof answers !== 'object') throw new SystemOneError('Response carried no answers');
  for (const [id, q] of Object.entries(questions)) {
    const a = answers[id];
    if (!a || a.type !== q.type) throw new SystemOneError(`Missing or mistyped answer for "${id}"`);
    if (q.type === 'choice' && !Object.hasOwn(q.criteria, a.choice))
      throw new SystemOneError(`Answer for "${id}" is not one of the offered options`);
    if (q.type === 'noul' && !(a.noul >= 0 && a.noul <= 1))
      throw new SystemOneError(`Answer for "${id}" is not a probability`);
    if (q.type === 'score' && !Number.isFinite(a.score))
      throw new SystemOneError(`Answer for "${id}" is not a score`);
  }
  return answers;
}

export function createSystemOne({apiKey, model = 'jev-latest', endpoint = ENDPOINT,
  fetchImpl = globalThis.fetch, maxRetries = 2, wait = ms => new Promise(r => setTimeout(r, ms))} = {}) {
  if (!apiKey) throw new SystemOneError('TYPESAFE_API_KEY is not set');
  return async function evaluate({state, questions, abortSignal, timeoutMs = 25000}) {
    checkQuestions(questions);
    const body = JSON.stringify({state, model, questions});
    let last = null;
    for (let attempt = 0; attempt <= maxRetries; attempt++) {
      if (attempt) await wait(backoff(attempt - 1));
      const signals = [AbortSignal.timeout(timeoutMs)];
      if (abortSignal) signals.push(abortSignal);
      let response;
      try {
        response = await fetchImpl(endpoint, {method: 'POST', body,
          headers: {Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json'},
          signal: AbortSignal.any(signals)});
      } catch (error) {
        if (abortSignal?.aborted) throw new SystemOneError('Cancelled', {cause: error});
        // The key rides in the headers, so the raw error is never re-thrown.
        last = new SystemOneError(`Cannot reach the System One API: ${error.name}`, {cause: error});
        continue;
      }
      if (response.ok) {
        let payload;
        try { payload = await response.json(); }
        catch (error) { last = new SystemOneError('Response was not JSON', {cause: error}); continue; }
        checkAnswers(payload?.answers, questions);
        return {answers: payload.answers, usage: payload.usage ?? null, model: payload.model ?? model};
      }
      const detail = await response.text().then(t => t.slice(0, 200)).catch(() => '');
      const error = new SystemOneError(`System One returned ${response.status}`, {statusCode: response.status});
      error.detail = detail;
      if (!retriable(response.status)) throw error;
      last = error;
    }
    throw last ?? new SystemOneError('System One did not answer');
  };
}
