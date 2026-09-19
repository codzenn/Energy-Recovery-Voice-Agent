"use client";

import { useEffect, useRef } from "react";
import type { TranscriptEntry } from "@/lib/api";

export default function CallTranscript({ transcript }: { transcript: TranscriptEntry[] }) {
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => { bottom.current?.scrollIntoView({ block: "nearest" }); }, [transcript.length]);
  return (
    <section>
      <h2>Call Transcript</h2>
      <div role="log" aria-live="polite" aria-label="Call transcript" className="max-h-96 space-y-3 overflow-y-auto">
        {transcript.length === 0 && <p className="text-sm text-gray-600">Start Voice Recovery to hear the recording disclosure and begin speaking.</p>}
        {transcript.map((entry, index) => (
          <div key={index} className="border-l-2 border-gray-300 pl-3 text-sm">
            <strong className="capitalize">{entry.role}</strong>
            <p className="whitespace-pre-wrap break-words">{entry.text}</p>
          </div>
        ))}
        <div ref={bottom} />
      </div>
    </section>
  );
}
