const TOKEN = window.COCKPIT.token;

async function decode(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

export async function getJSON(url) {
  return decode(await fetch(url, { headers: { Accept: "application/json" } }));
}

// timeoutMs turns a request that never settles (engine hung, machine asleep)
// into an honest error instead of silence. Left off by default because some
// writes legitimately run long; the workbench polls state, so a timed-out call
// whose server side actually succeeded self-corrects on the next refresh.
export async function postJSON(url, body = {}, { timeoutMs = 0 } = {}) {
  try {
    return decode(await fetch(url, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-Cockpit-Token": TOKEN,
      },
      body: JSON.stringify(body),
      ...(timeoutMs ? { signal: AbortSignal.timeout(timeoutMs) } : {}),
    }));
  } catch (error) {
    if (error.name === "TimeoutError" || error.name === "AbortError") {
      throw new Error("The engine did not answer in time — check it is running, then reload before retrying.");
    }
    throw error;
  }
}
