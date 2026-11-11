// Thin fetch wrapper. The selected demo user travels in X-User-Id; the server enforces roles.
export const session = {
  get userId() { try { return localStorage.getItem("inkloom.user") || "u-creator"; } catch { return "u-creator"; } },
  set userId(v) { try { localStorage.setItem("inkloom.user", v); } catch { /* private mode */ } },
};

export async function api(path, { method = "GET", body } = {}) {
  let res;
  try {
    res = await fetch(path, {
      method,
      headers: { "Content-Type": "application/json", "X-User-Id": session.userId },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new Error("Cannot reach the Inkloom server. Is `python run.py` running?");
  }
  let data = null;
  const text = await res.text();
  try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text }; }
  if (!res.ok) {
    const d = data && data.detail;
    const err = new Error(typeof d === "string" ? d : Array.isArray(d) ? d.map(x => x.msg).join("; ") : `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
}

export function fileToB64(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",")[1]);
    r.onerror = () => reject(new Error("Could not read " + file.name));
    r.readAsDataURL(file);
  });
}

export function guessMime(file) {
  if (file.type) return file.type;
  const n = file.name.toLowerCase();
  if (n.endsWith(".md")) return "text/markdown";
  if (n.endsWith(".txt")) return "text/plain";
  if (n.endsWith(".pdf")) return "application/pdf";
  return "application/octet-stream";
}
