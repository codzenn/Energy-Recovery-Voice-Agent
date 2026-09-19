# Decisions, Tradeoffs, and Accuracy

This document records the main engineering decisions in the Energy recovery voice-agent prototype.

## 1. Project Boundary

### Decision

Build a local synthetic demo instead of connecting to production systems.

### Why

The prototype can demonstrate the complete recovery flow without using real customer records, real phone calls, or production credentials.

### Tradeoff

The demo proves the conversation and safety workflow, but it does not prove production integration, scale, or business results.

### Accuracy

- Leads are synthetic.
- The Energy journey is synthetic.
- Transcripts are synthetic.
- Journey completion is local and synthetic.
- The repository is not connected to production CIMET systems.

## 2. Browser Voice Instead Of Live Telephony

### Decision

Use the browser for microphone capture and speech playback.

### Why

It makes the voice-first demo easy to run locally. No phone number, telephony account, or live call provider is required.

### Implementation

- `getUserMedia` captures microphone audio.
- `AudioWorklet` processes audio frames.
- The browser creates mono PCM16 WAV turns.
- The WAV is sent to FastAPI.
- Browser `speechSynthesis` plays the agent response.
- The backend uses a browser voice adapter to stay independent of browser details.

### Tradeoff

This is useful for a local demo, but browser audio is not the same as a production phone connection. Browser permissions, devices, noise, interruptions, and speech playback can vary.

### Accuracy

The current implementation does not place a real phone call and does not transfer to a live human destination.

## 3. Local Whisper For Speech-To-Text

### Decision

Use local `faster-whisper` for audio transcription.

### Why

It keeps the demo self-contained and avoids sending demo audio to an external speech provider.

### Implementation

The API validates the uploaded WAV before transcription. The default model is `base.en`. Audio is handled in memory by the speech service.

### Tradeoff

Local transcription is simple for the prototype, but it may be slower or less accurate than a production speech service for difficult accents, background noise, poor microphones, or very short answers.

### Accuracy

The code calculates an ASR confidence value from word probabilities. This is a useful signal, not a guaranteed probability of correctness.

## 4. Mock LLM By Default

### Decision

Use a deterministic mock extractor by default, with an optional OpenAI adapter.

### Why

The demo remains repeatable and can run without an API key. The adapter design allows a different model provider later.

### Implementation

The mock provider extracts configured field values using deterministic rules. The OpenAI adapter requests structured JSON containing a value, confidence, evidence, intent, and handoff signal.

### Tradeoff

The mock provider is predictable, but it does not represent the full language ability of a production LLM. The optional OpenAI path introduces an external dependency, network latency, cost, and provider configuration requirements.

### Accuracy

The default runtime configuration uses the mock LLM. It is not accurate to describe the current default path as an OpenAI-powered agent unless the environment is explicitly configured that way.

## 5. Deterministic Backend Control

### Decision

Keep consent, state transitions, validation, persistence, completion, DNC checks, and escalation in backend code.

### Why

These are safety and business decisions. They should be testable and predictable.

### Tradeoff

The conversation may be less flexible than an agent that controls everything through a model. In return, the system has clearer safety boundaries and easier debugging.

### Accuracy

The LLM or mock extractor does not directly write to the database or complete the journey. The `RecoveryAgent`, state layer, tools, and services control those actions.

## 6. Explicit Conversation States

### Decision

Represent the call with explicit states such as:

- `CONSENT_REQUIRED`
- `COLLECTING`
- `CONFIRMING`
- `COMPLETING`
- `COMPLETED`
- `HANDOFF`
- `ENDED`
- `BLOCKED_DNC`

### Why

The system needs to know what actions are allowed at each stage.

### Example

A field cannot be saved before consent. The journey cannot be completed before required fields are valid and explicitly confirmed.

### Tradeoff

More states create more transitions to test. That is preferable to hiding important rules in loosely structured prompts.

## 7. Configuration-Driven Journey

### Decision

Store the synthetic Energy fields, questions, choices, validation rules, confirmations, and branches in `data/journeys/energy_demo.json`.

### Why

The agent can use one general conversation engine while the journey controls the field order and requirements.

### Tradeoff

A configuration file is less expressive than a full journey platform. It is easier to inspect and change for a hackathon prototype.

### Accuracy

The current journey includes fields such as customer name, postcode, property address, dwelling type, provider, connection type, gas, solar, move-in date, and email. Some fields are conditional.

## 8. Backend Chooses The Next Question

### Decision

The backend finds the first active required field that has not been collected.

### Why

The agent should not ask for information that is already present or let the model choose an arbitrary order.

### Tradeoff

The conversation follows a defined script instead of being completely open-ended. This makes completion and validation clearer.

### Accuracy

The model helps understand the customer’s answer to the current field. It does not decide the overall journey order.

## 9. Extraction And Validation Are Separate

### Decision

First extract a possible value, then validate it using the field specification.

### Why

A sentence can be understood while still containing an invalid answer.

### Example

```text
Customer: My postcode is 30.
Extractor: postcode = 30.
Validator: invalid because the demo requires four digits.
System: asks for the postcode again.
```

### Tradeoff

The customer may need another turn. This is safer than saving an invalid value.

### Accuracy

Validation is implemented for types and rules including postcode, email, date, integer, boolean, text length, patterns, and configured choices.

## 10. Grounding And No Guessing

### Decision

Do not accept an extracted value unless it is grounded in the customer’s utterance.

### Why

A model must not fill in missing facts from assumptions.

### Implementation

The agent checks evidence and verifies that the extracted value appears in the customer’s text. Boolean answers use explicit yes/no logic.

### Tradeoff

Some natural answers may be rejected or escalated if the evidence is unclear. That is safer than silently inventing data.

## 11. Consent Before Collection

### Decision

Make consent a separate state before field collection.

### Why

The customer should agree before the recovery flow collects journey information.

### Implementation

The call starts in `CONSENT_REQUIRED`. An affirmative response records consent and advances to the first missing field. A decline ends the call.

### Important correction

Short answers such as “yes” can receive a low ASR confidence score. Explicit affirmative consent is handled before generic low-confidence escalation so a valid consent answer is not incorrectly handed off.

### Tradeoff

Consent needs special handling and testing, but this makes the critical transition safer and easier to explain.

## 12. Payment Safety

### Decision

Payment and card information are outside the normal voice collection flow.

### Why

The prototype should not ask for or store card details.

### Implementation

Payment language is detected before normal field extraction. The agent creates a `PAYMENT` handoff. Sensitive text is redacted in the transcript and is not saved as a journey field.

### Tradeoff

The automated journey cannot handle payment-related requests. The customer must use a safer human or approved payment process.

### Accuracy

The code protects the local demo path. It is not a claim that this prototype satisfies every production payment-security or compliance requirement.

## 13. Escalation Instead Of Forced Automation

### Decision

Stop the automated flow when the conversation is unsafe, unsupported, or unreliable.

### Signals

- explicit human request
- anger or frustration
- repeated complaints
- repeated misunderstanding
- off-script question
- advice request
- sensitive or vulnerable topic
- payment language
- low confidence

### Why

The system should know when it is outside its safe scope.

### Tradeoff

Some conversations that could possibly be completed automatically will be handed off. This is an acceptable tradeoff for trust and safety in the prototype.

### Accuracy

The thresholds and pattern rules are local prototype rules. They are not calibrated production policies.

## 14. Warm Handoff Context

### Decision

Create a structured handoff context instead of only saying that a transfer happened.

### Context includes

- call ID
- lead ID
- current step
- collected fields
- remaining fields
- transcript
- summary
- escalation reason
- confidence

### Why

The human should be able to continue from the current point without making the customer repeat everything.

### Tradeoff

The current prototype prepares and displays the context but does not connect to a live operator platform.

### Accuracy

The `HandoffService` builds the context deterministically. It does not generate new customer facts for the handoff.

## 15. Respecting A Decline

### Decision

Treat “not interested,” “stop,” and similar phrases as a clear end-of-contact signal.

### Why

The system should not pressure the customer.

### Implementation

The local DNC store is updated, the call ends, and the agent gives a short closing response.

### Tradeoff

A genuine decline means the system gives up the opportunity to continue that recovery attempt. This is the correct customer choice.

## 16. DNC Check Before Starting

### Decision

Check the local DNC provider before starting a call.

### Why

A blocked lead should not enter the recovery conversation.

### Tradeoff

The current provider is only a local/mock provider. It demonstrates the control point, not a production DNC integration.

### Accuracy

The health endpoint reports the configured DNC provider. The default local mode uses the mock provider.

## 17. SQLite Persistence

### Decision

Use SQLite for the local database.

### Why

It is easy to run with no separate database service.

### Data stored

- leads
- calls
- call messages
- collected fields
- events
- handoffs
- DNC checks
- synthetic submissions

### Tradeoff

SQLite is suitable for this single-process prototype, but it is not the final choice for a highly concurrent production service.

### Accuracy

The database layer explicitly supports `sqlite:///` URLs only.

## 18. Idempotent Audio Events

### Decision

Give audio submissions an event ID and remember processed event IDs.

### Why

A retry should not transcribe or apply the same customer turn twice.

### Tradeoff

The call stores extra event IDs, but this makes retry behavior safer and easier to reason about.

## 19. Browser Recording Retention

### Decision

Keep the consented demo recording in browser memory for optional playback after a safe completed call.

### Why

It allows the evaluator to verify that the browser actually captured audio.

### Implementation

The recording is offered only after a safe end when consent was given. It is discarded on handoff or error.

### Tradeoff

The recording is temporary and browser-local. It is not a production recording archive.

### Accuracy

The README says the project is not connected to live recordings. The browser flow is a local demo capture path.

## 20. Testing Strategy

### Decision

Test the backend rules and the browser voice flow separately and together where possible.

### Backend coverage includes

- state transitions
- consent
- validation
- payment redaction
- escalation
- handoff context
- DNC behavior
- SQLite projections
- audio validation
- synthetic journey completion

### Browser coverage includes

- microphone permission errors
- synthetic microphone capture
- WAV upload
- consent flow
- completion
- handoff
- payment behavior
- recording retention

### Tradeoff

Synthetic browser audio and local tests cannot cover every real microphone, accent, network, phone, or customer behavior.

## 21. Accuracy Rules For Evaluation

Use these claims:

- “This is a working local prototype.”
- “The demo uses synthetic leads, journeys, transcripts, and completion results.”
- “The browser voice path, local transcription path, state handling, validation, and dashboard are implemented.”
- “The default LLM is a deterministic mock; an OpenAI adapter is optional when configured.”
- “The handoff context is prepared and displayed locally.”
- “The system is designed to escalate when it is unsure or outside its scope.”

Avoid these claims:

- “This uses real CIMET customer data.”
- “This places production phone calls.”
- “This connects to a live human transfer system.”
- “This is production-ready.”
- “The AI is 100% accurate.”
- “The system replaces human agents.”
- “The prototype has proven ROI or conversion improvement.”
- “The prototype guarantees production compliance.”

## 22. Real Versus Synthetic Summary

| Area                     | Current status                               |
| ------------------------ | -------------------------------------------- |
| Leads                    | Synthetic                                    |
| Energy journey           | Synthetic configuration                      |
| Customer transcripts     | Synthetic scripted/demo data                 |
| Speech capture           | Implemented browser demo path                |
| Speech-to-text           | Local `faster-whisper`, `base.en` by default |
| Speech playback          | Browser `speechSynthesis`                    |
| Default LLM              | Deterministic mock                           |
| Optional LLM             | OpenAI adapter if configured                 |
| DNC                      | Local/mock provider                          |
| Completion               | Local synthetic journey service              |
| Database                 | Local SQLite                                 |
| Handoff                  | Context prepared and shown locally           |
| Telephony                | Not connected                                |
| Production CIMET systems | Not connected                                |

## 23. Main Tradeoff Summary

| Decision                     | Benefit                              | Cost or limitation                         |
| ---------------------------- | ------------------------------------ | ------------------------------------------ |
| Synthetic data               | Safe, repeatable demo                | No production outcome evidence             |
| Browser voice                | Easy local voice demo                | Not production telephony                   |
| Local Whisper                | Self-contained transcription         | Device speed and recognition limits        |
| Mock LLM default             | Repeatable and offline-friendly      | Less natural than a full model             |
| Optional OpenAI adapter      | More flexible language understanding | External API, cost, latency, configuration |
| Deterministic backend rules  | Safer and testable                   | Less open-ended behavior                   |
| Configuration-driven journey | Easy to inspect and change           | Not a full production journey platform     |
| SQLite                       | Simple local persistence             | Limited scaling and concurrency            |
| Warm handoff context         | Better human continuity              | No live transfer integration               |
| Conservative escalation      | Reduces unsafe guessing              | Some safe calls may be handed off early    |

## 24. Final Explanation

“We chose a simple, controlled architecture because this is a recovery workflow with sensitive decisions. The model helps understand language, but the backend controls consent, field order, validation, payment safety, DNC, completion, and handoff. We use synthetic data and local providers so the demo is safe and repeatable. The tradeoff is that this is not a production telephony or CIMET integration yet. Its value is that it demonstrates the end-to-end decision flow, including the point where the system should stop and involve a human.”
