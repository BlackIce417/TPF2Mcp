export class HttpError extends Error {
  constructor(message, {status = 0, payload = null} = {}) {
    super(message);
    this.name = 'HttpError';
    this.status = status;
    this.payload = payload;
  }
}

export async function getJson(url, {attempts = 1, timeoutMs = 7000} = {}) {
  let lastError;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      const response = await fetch(url, {
        cache: 'no-store',
        headers: {Accept: 'application/json'},
        signal: AbortSignal.timeout(timeoutMs),
      });
      const contentType = response.headers.get('content-type') || '';
      const payload = contentType.includes('application/json') ? await response.json() : null;
      if (!response.ok) {
        throw new HttpError(payload?.reason || payload?.error || `HTTP ${response.status}`, {
          status: response.status,
          payload,
        });
      }
      if (payload === null) throw new HttpError('响应不是 JSON', {status: response.status});
      return payload;
    } catch (error) {
      lastError = error;
      const retryableHttp = error instanceof HttpError
        && (error.status >= 500 || error.status === 408 || error.status === 429);
      if ((error instanceof HttpError && !retryableHttp) || attempt === attempts - 1) break;
      await new Promise(resolve => window.setTimeout(resolve, 200 * (attempt + 1)));
    }
  }
  throw lastError;
}
