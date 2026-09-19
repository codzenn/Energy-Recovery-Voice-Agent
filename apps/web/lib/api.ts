export type Lead = {
  lead_id: string;
  status: string;
  last_completed_step: string | null;
  fields: Record<string, unknown>;
  customer_name?: string;
  dnc_blocked?: boolean;
  synthetic?: boolean;
};

export type TranscriptEntry = { role: "agent" | "customer" | "system"; text: string; created_at: string };
export type HandoffContext = {
  handoff_id: string;
  call_id: string;
  lead_id: string;
  reason: string;
  summary: string;
  collected_data: Record<string, unknown>;
  current_step: string | null;
  confidence: number;
  transcript: TranscriptEntry[];
  remaining_fields: string[];
};
export type Call = {
  call_id: string;
  lead_id: string;
  status: string;
  current_field: string | null;
  last_completed_step: string | null;
  collected_fields: Record<string, unknown>;
  consent_given: boolean;
  transcript: TranscriptEntry[];
  escalation: HandoffContext | null;
  provider_error: string | null;
  completion_reference: string | null;
  pending_field: string | null;
  pending_value: unknown;
  confidence: number;
  end_reason: string | null;
  completion_result: Record<string, unknown> | null;
  last_extraction: Record<string, unknown> | null;
  last_validation: Record<string, unknown> | null;
  events: {timestamp: string; event_type: string; metadata: Record<string, unknown>}[];
};
export type FieldSpec = {
  name: string; step: string; question: string; required: boolean;
  branch?: { field: string; equals: string | number | boolean } | null;
};
export type Health = { providers: Record<string, string>; warnings: string[] };
export type Scenario = { scenario: string; title: string; lead_id: string; expected_status: string };
export type ScenarioResult = { scenario: string; passed: boolean; call: Call };

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "/backend";

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      method: body === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(25000),
      cache: "no-store",
    });
  } catch {
    throw new ApiError("Backend unavailable. Start FastAPI on port 8000 and reconnect.", 0);
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new ApiError(typeof data.detail === "string" ? data.detail : `Request failed (${response.status})`, response.status);
  }
  return response.json() as Promise<T>;
}

export const api = {
  speechReady: () => request<{ ready: boolean }>("/api/voice/capabilities"),
  audio: async (id: string, audio: Blob, signal: AbortSignal): Promise<{ call: Call; heard: boolean }> => {
    const response = await fetch(`${BASE}/api/voice/${encodeURIComponent(id)}/audio?event_id=${crypto.randomUUID()}`, {
      method: "POST", headers: { "Content-Type": "audio/wav" }, body: audio,
      signal: AbortSignal.any([signal, AbortSignal.timeout(60000)]),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new ApiError(data.detail || "Audio transcription failed", response.status);
    }
    return response.json();
  },
  health: () => request<Health>("/health"),
  fields: () => request<{ demo_only: boolean; fields: FieldSpec[] }>("/api/journey/fields"),
  lead: (id: string) => request<Lead>(`/api/leads/${encodeURIComponent(id)}`),
  leads: () => request<Lead[]>("/api/leads"),
  scenarios: () => request<Scenario[]>("/api/demo/scenarios"),
  runScenario: (scenario: string) => request<ScenarioResult>(`/api/demo/scenarios/${encodeURIComponent(scenario)}/run`, {}),
  createLead: (id: string) => request<Lead>("/api/leads", {
    lead_id: id, fields: {}, test_data: true, synthetic: true,
  }),
  call: (id: string) => request<Call>(`/api/calls/${encodeURIComponent(id)}`),
  start: (id: string) => request<Call>("/api/calls/start", { lead_id: id }),
  message: (id: string, text: string, eventId: string) => request<Call>(`/api/calls/${id}/message`, { text, event_id: eventId }),
  handoff: (id: string) => request<Call>(`/api/calls/${id}/handoff`, { reason: "EXPLICIT_HUMAN_REQUEST" }),
  complete: (id: string, confirmed: boolean) => request<Call>(`/api/calls/${id}/complete`, { confirmed }),
  end: (id: string, reason = "CUSTOMER_STOPPED") => request<Call>(`/api/calls/${id}/end`, { reason }),
};

// The backend journey endpoint is the runtime source of truth. This small local copy
// exists only for the offline preview, so Turbopack does not need to import above the
// apps/web project boundary.
export const previewLead: Lead = {
  lead_id: "syn-happy-01", customer_name: "Alex Demo", synthetic: true,
  status: "dropped_off", last_completed_step: "electricity", fields: {},
};
export const previewFields: FieldSpec[] = [
  { name: "customer_name", step: "identity", required: true, question: "What name should I use for this synthetic comparison?" },
  { name: "postcode", step: "location", required: true, question: "What is the four-digit postcode for the property?" },
  { name: "property_address", step: "address", required: true, question: "What is the synthetic property address?" },
  { name: "dwelling_type", step: "property", required: true, question: "Is the property a house, apartment, or townhouse?" },
  { name: "current_energy_provider", step: "supply", required: true, question: "Which demo provider are you with?" },
  { name: "electricity_connection_type", step: "electricity", required: true, question: "Is this an existing electricity connection or a new connection?" },
  { name: "gas_required", step: "gas", required: true, question: "Would you like gas included in this synthetic comparison?" },
  { name: "gas_connection_type", step: "gas_connection", required: true, question: "For gas, is the connection existing or new?", branch: { field: "gas_required", equals: true } },
  { name: "solar_present", step: "solar", required: true, question: "Does the property have solar panels?" },
  { name: "solar_system_kw", step: "solar_size", required: true, question: "What is the solar system size in whole kilowatts for this demo?", branch: { field: "solar_present", equals: true } },
  { name: "move_in_date", step: "move", required: true, question: "What move-in date should I use?" },
  { name: "email", step: "contact", required: true, question: "What synthetic email address should I use?" },
];
