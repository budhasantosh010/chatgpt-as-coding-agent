const TOKEN = window.COCKPIT.token;

async function decode(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

export async function getJSON(url) {
  return decode(await fetch(url, { headers: { Accept: "application/json" } }));
}

export async function postJSON(url, body = {}) {
  return decode(await fetch(url, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-Cockpit-Token": TOKEN,
    },
    body: JSON.stringify(body),
  }));
}
