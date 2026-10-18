// THE-MANAGER resident prefill (SPEC 4.12): only the prefill_id and mobile live in the browser, for this tab only.
const KEY = "showcase.prefill";

export type PrefillRef = { prefill_id: string; mobile: string };
export type PrefillData = {
  name: string | null; society_name: string | null; address_line: string | null; city: string | null;
  state: string | null; pincode: string | null; flat_number: string | null; floor: string | null;
};

export function savePrefill(p: PrefillRef) {
  try { sessionStorage.setItem(KEY, JSON.stringify(p)); } catch { /* private mode: prefill just won't apply */ }
}

export function readPrefill(): PrefillRef | null {
  try { const v = sessionStorage.getItem(KEY); return v ? (JSON.parse(v) as PrefillRef) : null; } catch { return null; }
}

export function clearPrefill() {
  try { sessionStorage.removeItem(KEY); } catch { /* ignore */ }
}
