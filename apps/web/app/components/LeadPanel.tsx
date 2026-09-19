import type { Call, Lead, FieldSpec } from "@/lib/api";

export default function LeadPanel({ lead, call, fields }: { lead: Lead | null; call: Call | null; fields: FieldSpec[] }) {
  const currentStep = fields.find((field) => field.name === call?.current_field)?.step;
  return (
    <section>
      <h2>Lead & Call</h2>
      <dl className="grid grid-cols-2 gap-2 text-sm">
        <dt>Lead ID</dt><dd className="break-all">{lead?.lead_id || "None loaded"}</dd>
        <dt>Customer</dt><dd>{String(call?.collected_fields.customer_name || lead?.customer_name || "-")}</dd>
        <dt>Call Status</dt><dd>{call?.status || "IDLE"}</dd>
        <dt>DNC Status</dt><dd>{lead?.dnc_blocked || call?.status === "BLOCKED_DNC" || call?.end_reason === "CUSTOMER_DECLINED" ? "Blocked" : "Allowed (synthetic gate)"}</dd>
        <dt>Consent</dt><dd>{call?.consent_given ? "Given" : "Required before collection"}</dd>
        <dt>Current Step</dt><dd>{currentStep || call?.status || lead?.last_completed_step || "-"}</dd>
        <dt>Current Field</dt><dd>{call?.current_field || "-"}</dd>
        <dt>Last Completed</dt><dd>{call?.last_completed_step || lead?.last_completed_step || "-"}</dd>
      </dl>
      <h2 className="mt-5">Collected Fields</h2>
      <pre>{JSON.stringify(call?.collected_fields || lead?.fields || {}, null, 2)}</pre>
      {call?.pending_field && <p className="mt-3 text-sm">
        Awaiting confirmation: {call.pending_field} = {String(call.pending_value)}. Not saved as final.
      </p>}
      {call?.completion_reference && <p className="mt-3 break-all text-sm">Receipt: {call.completion_reference}</p>}
      {call?.completion_result && <><h2 className="mt-3">Completion Result</h2>
        <pre>{JSON.stringify(call.completion_result, null, 2)}</pre></>}
      {call?.provider_error && <p role="alert" className="mt-3 text-red-700">{call.provider_error}</p>}
    </section>
  );
}
