'use client';

import {
    api,
    ApiError,
    previewFields,
    previewLead,
    type Call,
    type FieldSpec,
    type Health,
    type Lead,
    type Scenario,
} from '@/lib/api';
import { useCallback, useEffect, useMemo, useState } from 'react';
import BrowserVoiceControls from './components/BrowserVoiceControls';
import CallTranscript from './components/CallTranscript';
import HandoffPanel from './components/HandoffPanel';
import JourneyProgress from './components/JourneyProgress';
import LeadPanel from './components/LeadPanel';

const terminal = new Set(['COMPLETED', 'HANDOFF', 'ENDED', 'BLOCKED_DNC']);

export default function Home() {
    const [leadId, setLeadId] = useState('syn-happy-01');
    const [lead, setLead] = useState<Lead | null>(null);
    const [call, setCall] = useState<Call | null>(null);
    const [fields, setFields] = useState<FieldSpec[]>([]);
    const [health, setHealth] = useState<Health | null>(null);
    const [message, setMessage] = useState('');
    const [busy, setBusy] = useState(false);
    const [offline, setOffline] = useState(false);
    const [error, setError] = useState('');
    const [confirmed, setConfirmed] = useState(false);
    const [demoOnly, setDemoOnly] = useState(true);
    const [leads, setLeads] = useState<Lead[]>([]);
    const [scenarios, setScenarios] = useState<Scenario[]>([]);
    const [scenario, setScenario] = useState('happy_path');
    const [scenarioResult, setScenarioResult] = useState('');

    const statusTone = useMemo(() => {
        if (!call) return 'neutral';
        if (['COMPLETED', 'HANDOFF'].includes(call.status)) return 'success';
        if (['ENDED', 'BLOCKED_DNC'].includes(call.status)) return 'danger';
        if (call.status === 'CONFIRMING') return 'warning';
        return 'info';
    }, [call]);

    const connect = useCallback(async (id: string) => {
        setBusy(true);
        setError('');
        setCall(null);
        setLead(null);
        setConfirmed(false);
        try {
            const [nextHealth, schema, nextLead, leadList, scenarioList] = await Promise.all([
                api.health(),
                api.fields(),
                api.lead(id),
                api.leads(),
                api.scenarios(),
            ]);
            setHealth(nextHealth);
            setFields(schema.fields);
            setDemoOnly(schema.demo_only);
            setLead(nextLead);
            setLeads(leadList);
            setScenarios(scenarioList);
            setLeadId(id);
            setOffline(false);
            const savedId = sessionStorage.getItem(`call:${id}`);
            if (savedId) {
                try {
                    setCall(await api.call(savedId));
                } catch {
                    sessionStorage.removeItem(`call:${id}`);
                }
            }
        } catch (err) {
            if (err instanceof ApiError && err.status === 0) {
                setOffline(true);
                setLead(previewLead);
                setFields(previewFields);
                setHealth(null);
                setDemoOnly(true);
            } else {
                setOffline(false);
            }
            setError(err instanceof Error ? err.message : 'Could not load lead');
        } finally {
            setBusy(false);
        }
    }, []);

    useEffect(() => {
        void connect('syn-happy-01');
    }, [connect]);

    useEffect(() => {
        if (!call || terminal.has(call.status) || busy || offline) return;
        let cancelled = false;
        const interval = setInterval(() => {
            void api
                .call(call.call_id)
                .then((next) => {
                    if (!cancelled) setCall(next);
                })
                .catch(() => {});
        }, 2000);
        return () => {
            cancelled = true;
            clearInterval(interval);
        };
    }, [call?.call_id, call?.status, busy, offline]);

    function acceptCall(next: Call) {
        setCall(next);
        sessionStorage.setItem(`call:${next.lead_id}`, next.call_id);
        setLead((existing) =>
            existing
                ? {
                      ...existing,
                      fields: next.collected_fields,
                      last_completed_step: next.last_completed_step,
                      dnc_blocked:
                          existing.dnc_blocked ||
                          next.status === 'BLOCKED_DNC' ||
                          next.end_reason === 'CUSTOMER_DECLINED',
                      status: next.status === 'COMPLETED' ? 'completed' : existing.status,
                  }
                : existing,
        );
        setConfirmed(false);
    }

    async function perform(action: () => Promise<Call>) {
        setBusy(true);
        setError('');
        try {
            const next = await action();
            acceptCall(next);
            return next;
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Action failed');
        } finally {
            setBusy(false);
        }
    }

    async function freshLead() {
        setBusy(true);
        setError('');
        try {
            const id = `demo-energy-${Date.now()}`;
            const next = await api.createLead(id);
            setLeadId(id);
            setLead(next);
            setCall(null);
            setConfirmed(false);
            setMessage('');
            setScenarioResult('');
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Could not create lead');
        } finally {
            setBusy(false);
        }
    }

    async function runDemo() {
        setBusy(true);
        setError('');
        setScenarioResult('');
        try {
            const result = await api.runScenario(scenario);
            setCall(result.call);
            setLeadId(result.call.lead_id);
            setLead(await api.lead(result.call.lead_id));
            sessionStorage.setItem(`call:${result.call.lead_id}`, result.call.call_id);
            setConfirmed(false);
            setScenarioResult(
                `${result.passed ? 'PASS' : 'FAIL'}: ${scenario} / ${result.call.status}`,
            );
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Scenario failed');
        } finally {
            setBusy(false);
        }
    }

    const active = !!call && !terminal.has(call.status);
    const disabled = busy || offline;

    return (
        <main className="shell">
            <div className="dashboard">
                <header className="hero">
                    <div>
                        <p className="eyebrow">Synthetic Energy Recovery</p>
                        <h1>Voice demo assistant</h1>
                    </div>
                    <div className={`status-pill ${statusTone}`}>{call ? call.status : 'IDLE'}</div>
                </header>

                {offline && (
                    <div className="banner banner-warning" role="status">
                        Offline preview: local mock data only.
                    </div>
                )}
                {error && (
                    <div className="banner banner-error" role="alert">
                        {error}
                    </div>
                )}

                <section className="panel panel-hero">
                    <div className="panel-header">
                        <div>
                            <p className="mini-label">Lead</p>
                            <h2>{lead?.lead_id || 'No lead selected'}</h2>
                        </div>
                        <div className="meta-stack">
                            <span>{lead?.customer_name || 'Demo customer'}</span>
                            <span>
                                {call?.consent_given ? 'Consent granted' : 'Consent required'}
                            </span>
                        </div>
                    </div>

                    <div className="controls-grid">
                        <label className="field">
                            <span>Demo scenario</span>
                            <select
                                value={scenario}
                                onChange={(event) => setScenario(event.target.value)}
                                disabled={disabled}
                            >
                                {scenarios.map((item) => (
                                    <option key={item.scenario} value={item.scenario}>
                                        {item.title}
                                    </option>
                                ))}
                            </select>
                        </label>

                        <label className="field">
                            <span>Lead ID</span>
                            <input
                                value={leadId}
                                onChange={(event) => setLeadId(event.target.value)}
                                required
                                disabled={busy}
                            />
                        </label>
                    </div>

                    <div className="button-row">
                        <button
                            className="primary"
                            disabled={disabled || scenarios.length === 0}
                            onClick={() => void runDemo()}
                        >
                            Start demo
                        </button>
                        <button type="button" disabled={busy} onClick={() => void connect(leadId)}>
                            Load lead
                        </button>
                        <button type="button" disabled={disabled} onClick={() => void freshLead()}>
                            New demo lead
                        </button>
                    </div>

                    <div className="inline-note">
                        <span>{demoOnly ? 'Synthetic data only' : 'Live config mode'}</span>
                        {health ? (
                            <span>
                                {Object.entries(health.providers)
                                    .map(([key, value]) => `${key}: ${value}`)
                                    .join(' • ')}
                            </span>
                        ) : (
                            <span>Connecting to backend…</span>
                        )}
                    </div>

                    {scenarioResult && <div className="scenario-result">{scenarioResult}</div>}
                </section>

                <BrowserVoiceControls
                    call={call}
                    disabled={disabled || !lead || lead?.status === 'completed'}
                    onStart={async () => {
                        if (lead) return perform(() => api.start(lead.lead_id));
                    }}
                    onCall={acceptCall}
                    onStop={async () => {
                        if (call) await perform(() => api.end(call.call_id));
                    }}
                />

                <section className="panel panel-action">
                    <div className="button-row wrap">
                        <button
                            disabled={disabled || !lead || active || lead.status === 'completed'}
                            onClick={() => lead && void perform(() => api.start(lead.lead_id))}
                        >
                            Start text recovery
                        </button>
                        <button
                            disabled={disabled || !active}
                            onClick={() => call && void perform(() => api.handoff(call.call_id))}
                        >
                            Handoff
                        </button>
                        <button
                            disabled={
                                disabled ||
                                !call ||
                                !!call.pending_field ||
                                !['CONFIRMING', 'COMPLETING'].includes(call.status) ||
                                !confirmed
                            }
                            onClick={() =>
                                call && void perform(() => api.complete(call.call_id, confirmed))
                            }
                        >
                            Complete journey
                        </button>
                    </div>

                    {call &&
                        !call.pending_field &&
                        ['CONFIRMING', 'COMPLETING'].includes(call.status) && (
                            <label className="check-row">
                                <input
                                    type="checkbox"
                                    checked={confirmed}
                                    onChange={(event) => setConfirmed(event.target.checked)}
                                />
                                <span>
                                    I confirm the captured data and authorize the mock submission.
                                </span>
                            </label>
                        )}

                    <form
                        className="message-form"
                        onSubmit={(event) => {
                            event.preventDefault();
                            if (call && message.trim()) {
                                const text = message.trim();
                                setMessage('');
                                void perform(() =>
                                    api.message(call.call_id, text, crypto.randomUUID()),
                                );
                            }
                        }}
                    >
                        <label className="field field-grow">
                            <span>Customer message</span>
                            <input
                                value={message}
                                onChange={(event) => setMessage(event.target.value)}
                                placeholder="Try: yes, wait, or change my postcode to 3001"
                                disabled={disabled || !active}
                                maxLength={2000}
                            />
                        </label>
                        <button
                            className="primary"
                            disabled={disabled || !active || !message.trim()}
                            type="submit"
                        >
                            Send
                        </button>
                    </form>

                    <p className="helper-text">
                        Try “wait”, “can you repeat that?”, or “change my postcode to 3001”. For
                        escalation: “I want a person”, “I want to pay by card”, or “I’m not
                        interested”.
                    </p>
                </section>

                <div className="content-grid">
                    <div className="stacked-panels">
                        <LeadPanel lead={lead} call={call} fields={fields} />
                        <JourneyProgress
                            fields={fields}
                            collected={call?.collected_fields || lead?.fields || {}}
                        />
                        <HandoffPanel context={call?.escalation || null} />
                    </div>

                    <div className="stacked-panels">
                        <CallTranscript transcript={call?.transcript || []} />
                        {call && (
                            <section className="panel">
                                <h2>Agent trace</h2>
                                <p className="small-meta">
                                    Extraction confidence: {call.confidence.toFixed(2)}
                                </p>
                                <pre>
                                    {JSON.stringify(
                                        {
                                            extracted: call.last_extraction,
                                            validation: call.last_validation,
                                        },
                                        null,
                                        2,
                                    )}
                                </pre>
                                <details>
                                    <summary>Structured events ({call.events.length})</summary>
                                    <pre className="detail-pre">
                                        {JSON.stringify(call.events, null, 2)}
                                    </pre>
                                </details>
                            </section>
                        )}
                    </div>
                </div>
            </div>
        </main>
    );
}
