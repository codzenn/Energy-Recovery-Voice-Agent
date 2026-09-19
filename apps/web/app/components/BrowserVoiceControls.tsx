'use client';

import { api, type Call } from '@/lib/api';
import { VoiceSession } from '@/lib/voice-session';
import { useEffect, useRef, useState } from 'react';

type Props = {
    call: Call | null;
    disabled: boolean;
    onStart: () => Promise<Call | undefined>;
    onCall: (call: Call) => void;
    onStop: () => Promise<void>;
};

export default function BrowserVoiceControls({ call, disabled, onStart, onCall, onStop }: Props) {
    const [running, setRunning] = useState(false);
    const [status, setStatus] = useState('Waiting');
    const [error, setError] = useState('');
    const [level, setLevel] = useState(0);
    const [recordingUrl, setRecordingUrl] = useState('');
    const [muted, setMuted] = useState(false);
    const session = useRef<VoiceSession | null>(null);
    const url = useRef('');
    const onCallRef = useRef(onCall);
    onCallRef.current = onCall;

    useEffect(() => {
        if (call) session.current?.update(call);
        else if (session.current && status !== 'Starting') {
            session.current.close(false);
            session.current = null;
        }
    }, [call]);

    useEffect(
        () => () => {
            session.current?.close(false);
            if (url.current) URL.revokeObjectURL(url.current);
        },
        [],
    );

    function setRecording(blob: Blob | null) {
        if (url.current) URL.revokeObjectURL(url.current);
        url.current = blob ? URL.createObjectURL(blob) : '';
        setRecordingUrl(url.current);
    }

    async function start() {
        if (session.current) return;
        setRunning(true);
        setError('');
        setStatus('Starting');
        setRecording(null);
        const voice = new VoiceSession({
            status: setStatus,
            level: setLevel,
            error: setError,
            recording: setRecording,
            closed: () => {
                setRunning(false);
                session.current = null;
            },
            send: async (id, audio, signal) => {
                const result = await api.audio(id, audio, signal);
                if (!signal.aborted) onCallRef.current(result.call);
                return result;
            },
        });
        voice.muted = muted;
        session.current = voice;
        try {
            await voice.open();
            await api.speechReady();
            if (session.current !== voice) return;
            const next = await onStart();
            if (!next) throw new Error('Call could not start. Check the backend message above.');
            voice.update(next);
        } catch (cause) {
            const name = cause instanceof DOMException ? cause.name : '';
            setError(
                name === 'NotAllowedError'
                    ? 'Microphone blocked. Allow this site in browser permissions and enable your browser in macOS System Settings > Privacy & Security > Microphone.'
                    : name === 'NotFoundError'
                      ? 'No microphone found. Connect a microphone and try again.'
                      : name === 'NotReadableError'
                        ? 'Microphone is busy or unavailable. Check other apps and the selected input device.'
                        : cause instanceof Error
                          ? cause.message
                          : 'Could not start audio capture.',
            );
            voice.close(false);
        }
    }

    async function stop() {
        session.current?.close(false);
        await onStop();
    }

    return (
        <section className="panel" aria-label="Live browser voice controls">
            <div className="panel-header">
                <div>
                    <p className="mini-label">Voice</p>
                    <h2>Live voice recovery</h2>
                </div>
                <div className="status-pill info" role="status" aria-live="polite">
                    Agent status: {status}
                </div>
            </div>

            <p className="helper-text">
                Start once, then speak after each prompt. This is a synthetic local flow and no
                phone call is placed.
            </p>

            <div className="button-row" style={{ marginTop: '1rem' }}>
                <button
                    className="voice-start"
                    aria-label="START VOICE RECOVERY"
                    disabled={
                        disabled ||
                        running ||
                        call?.status === 'BLOCKED_DNC' ||
                        call?.status === 'COMPLETED'
                    }
                    onClick={() => void start()}
                >
                    START VOICE RECOVERY
                </button>
                <button disabled={!running} onClick={() => void stop()}>
                    Stop call
                </button>
                <button
                    disabled={!running}
                    onClick={() => {
                        const next = !muted;
                        setMuted(next);
                        if (session.current) session.current.muted = next;
                    }}
                >
                    {muted ? 'Unmute agent' : 'Mute agent'}
                </button>
            </div>

            <div className="message-form" style={{ marginTop: '1rem' }}>
                <label className="field field-grow">
                    <span>Microphone level</span>
                    <meter
                        aria-label="Microphone level"
                        min={0}
                        max={1}
                        value={level}
                        style={{ width: '100%' }}
                    />
                </label>
            </div>

            <p className="small-meta" style={{ marginTop: '0.7rem' }}>
                Recording:{' '}
                {running
                    ? call?.consent_given
                        ? 'Capturing microphone audio in-browser'
                        : 'Waiting for consent'
                    : recordingUrl
                      ? 'Ready for playback'
                      : 'Not retained'}
            </p>

            {error && (
                <div
                    className="banner banner-warning"
                    role="alert"
                    aria-live="assertive"
                    style={{ marginTop: '0.9rem' }}
                >
                    {error}
                </div>
            )}

            {recordingUrl && (
                <div style={{ marginTop: '1rem' }}>
                    <audio
                        aria-label="Consented microphone recording"
                        controls
                        src={recordingUrl}
                        style={{ width: '100%' }}
                    />
                    <div style={{ marginTop: '0.5rem' }}>
                        <a
                            href={recordingUrl}
                            download={`synthetic-call-${call?.call_id || 'demo'}.wav`}
                            aria-label="Download synthetic microphone recording"
                        >
                            Download synthetic microphone recording
                        </a>
                    </div>
                </div>
            )}
        </section>
    );
}
