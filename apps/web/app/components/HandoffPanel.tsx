import type { HandoffContext } from "@/lib/api";

export default function HandoffPanel({ context }: { context: HandoffContext | null }) {
  return (
    <section>
      <h2>Human Handoff</h2>
      <p className="text-sm">Escalation Status: {context ? "Context prepared" : "None"}</p>
      <p className="mt-2 text-sm">Handoff Reason: {context?.reason || "-"}</p>
      {context && <>
        <p className="my-3 text-sm">{context.summary}</p>
        <p className="text-sm">Resume at: {context.current_step || "consent"}</p>
        <p className="my-2 text-sm">Remaining fields: {context.remaining_fields.join(", ") || "none"}</p>
        <p className="text-sm">Confidence: {context.confidence.toFixed(2)}</p>
        <details className="mt-3">
          <summary className="cursor-pointer text-sm">Full handoff context</summary>
          <pre className="mt-2">{JSON.stringify(context, null, 2)}</pre>
        </details>
      </>}
      <p className="mt-3 text-xs text-gray-600">No need for the customer to repeat previously collected information. This local demo prepares a human-ready context; a live transfer destination is not configured.</p>
    </section>
  );
}
