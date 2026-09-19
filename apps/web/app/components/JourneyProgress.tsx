import type { FieldSpec } from "@/lib/api";

export default function JourneyProgress({ fields, collected }: { fields: FieldSpec[]; collected: Record<string, unknown> }) {
  const isActive = (field: FieldSpec) => !field.branch || collected[field.branch.field] === field.branch.equals;
  const required = fields.filter((field) => field.required && isActive(field));
  const completed = required.filter((field) => Object.hasOwn(collected, field.name)).length;
  return (
    <section>
      <h2>Journey Progress</h2>
      <p className="mb-2 text-sm">{completed} / {required.length} required fields captured</p>
      <progress className="w-full" max={required.length || 1} value={completed} aria-label="Journey progress" />
      <ul className="mt-3 space-y-1 text-sm">
        {fields.map((field) => <li key={field.name}>
          {!isActive(field) ? "Skipped / conditional" : Object.hasOwn(collected, field.name) ? "Captured" : "Pending"}: {field.name} ({field.step})
          {!field.required && " - optional"}
        </li>)}
      </ul>
    </section>
  );
}
