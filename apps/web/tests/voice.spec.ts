import { expect, test, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { wavBlob } from '../lib/voice-session';

// Synthetic audio, real browser AudioWorklet + WAV capture, real local Whisper/API.
// These are NOT physical microphone, mobile hardware, or native TTS tests.
const directory = mkdtempSync(join(tmpdir(), 'energy-voice-test-'));
const utterances = {
    consent: 'Yes.',
    house: 'It is a house.',
    human: 'I want to speak to a person.',
    payment: 'Can I give you my card number?',
};
const audio = Object.fromEntries(
    Object.entries(utterances).map(([name, text]) => {
        const file = join(directory, `${name}.wav`);
        execFileSync('say', [
            '-v',
            'Samantha',
            '-r',
            '150',
            '-o',
            file,
            '--file-format=WAVE',
            '--data-format=LEI16@16000',
            text,
        ]);
        return [name, readFileSync(file).toString('base64')];
    }),
);

async function setup(page: Page) {
    const id = `voice-test-${crypto.randomUUID()}`;
    const response = await page.request.post('http://127.0.0.1:8000/api/leads', {
        data: {
            lead_id: id,
            synthetic: true,
            test_data: true,
            fields: {
                customer_name: 'Alex Demo',
                postcode: '3000',
                property_address: '10 Fiction Lane',
                current_energy_provider: 'Demo North',
                electricity_connection_type: 'existing',
                gas_required: false,
                solar_present: false,
                move_in_date: '2026-10-01',
                email: 'alex@example.test',
            },
        },
    });
    expect(response.ok()).toBeTruthy();
    const lead = await response.json();
    await page.route('**/api/leads/syn-happy-01', (route) => route.fulfill({ json: lead }));
    await page.addInitScript(() => {
        const runtime = window as unknown as {
            feedAudio: (data: string) => Promise<void>;
            testStream: MediaStream;
            ttsSpoken: string[];
        };
        runtime.ttsSpoken = [];
        Object.defineProperty(window, 'speechSynthesis', {
            configurable: true,
            value: {
                cancel() {},
                speak(utterance: SpeechSynthesisUtterance) {
                    runtime.ttsSpoken.push(utterance.text);
                    setTimeout(
                        () => utterance.onend?.(new Event('end') as SpeechSynthesisEvent),
                        50,
                    );
                },
            },
        });
        Object.defineProperty(navigator.mediaDevices, 'getUserMedia', {
            configurable: true,
            value: async () => {
                const context = new AudioContext();
                await context.resume();
                const destination = context.createMediaStreamDestination();
                const oscillator = context.createOscillator();
                const silent = context.createGain();
                silent.gain.value = 0;
                oscillator.connect(silent).connect(destination);
                oscillator.start();
                runtime.testStream = destination.stream;
                runtime.feedAudio = async (data) => {
                    const buffer = Uint8Array.from(atob(data), (c) => c.charCodeAt(0));
                    const decoded = await context.decodeAudioData(buffer.buffer);
                    const source = context.createBufferSource();
                    source.buffer = decoded;
                    source.connect(destination);
                    await new Promise<void>((resolve) => {
                        source.onended = () => resolve();
                        source.start();
                    });
                };
                return destination.stream;
            },
        });
    });
    await page.goto('/');
    await page.getByRole('button', { name: 'START VOICE RECOVERY', exact: true }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Agent status:' })).toHaveText(
        'Agent status: Listening',
        { timeout: 30000 },
    );
}

async function speak(page: Page, name: keyof typeof utterances) {
    await expect(page.getByRole('status').filter({ hasText: 'Agent status:' })).toHaveText(
        'Agent status: Listening',
        { timeout: 30000 },
    );
    // Allow the production echo-tail guard to expire before feeding the virtual mic.
    await page.waitForTimeout(400);
    const request = page.waitForResponse(
        (res) => res.url().includes('/audio?') && res.request().method() === 'POST',
        { timeout: 30000 },
    );
    await page.evaluate(
        (data) =>
            (window as unknown as { feedAudio: (data: string) => Promise<void> }).feedAudio(data),
        audio[name],
    );
    const result = await request;
    expect(result.status()).toBe(200);
    return (await result.json()).call;
}

test('hands-free real audio completes and retains consented WAV', async ({ page }) => {
    await setup(page);
    const consent = await speak(page, 'consent');
    expect(consent.consent_given).toBe(true);
    const field = await speak(page, 'house');
    expect(field.collected_fields.dwelling_type).toBe('house');
    expect(field.status).toBe('CONFIRMING');
    const completed = await speak(page, 'consent');
    expect(completed.status).toBe('COMPLETED');
    await expect(
        page.getByRole('link', { name: 'Download synthetic microphone recording' }),
    ).toBeVisible();
    const recording = await page.locator('audio').evaluate(async (element: HTMLAudioElement) => {
        const buffer = await (await fetch(element.src)).arrayBuffer();
        const view = new DataView(buffer);
        return {
            bytes: buffer.byteLength,
            rate: view.getUint32(24, true),
            pcmBytes: view.getUint32(40, true),
        };
    });
    expect(recording.bytes).toBe(recording.pcmBytes + 44);
    expect(recording.pcmBytes / (recording.rate * 2)).toBeGreaterThan(2);
    const trackStates = await page.evaluate(() =>
        (window as unknown as { testStream: MediaStream }).testStream
            .getTracks()
            .map((t) => t.readyState),
    );
    expect(trackStates).toEqual(['ended']);
});

test('spoken human request preserves handoff context and discards recording', async ({ page }) => {
    await setup(page);
    await speak(page, 'consent');
    const call = await speak(page, 'human');
    expect(call.status).toBe('HANDOFF');
    expect(call.escalation.reason).toBe('EXPLICIT_HUMAN_REQUEST');
    expect(call.escalation.collected_fields.customer_name).toBe('Alex Demo');
    await expect(page.getByText('Handoff Reason: EXPLICIT_HUMAN_REQUEST')).toBeVisible();
    await expect(page.locator('audio')).toHaveCount(0);
});

test('spoken payment causes redacted handoff without downloadable audio', async ({ page }) => {
    await setup(page);
    await speak(page, 'consent');
    const call = await speak(page, 'payment');
    expect(call.escalation.reason).toBe('PAYMENT');
    expect(
        call.transcript.some((t: { text: string }) => t.text === '[Sensitive content omitted]'),
    ).toBeTruthy();
    await expect(page.locator('audio')).toHaveCount(0);
});

test('permission denial gives actionable error and no call', async ({ page }) => {
    await page.addInitScript(() => {
        Object.defineProperty(navigator.mediaDevices, 'getUserMedia', {
            value: async () => {
                throw new DOMException('denied', 'NotAllowedError');
            },
        });
    });
    let starts = 0;
    page.on('request', (request) => {
        if (request.url().endsWith('/calls/start')) starts++;
    });
    await page.goto('/');
    await page.getByRole('button', { name: 'START VOICE RECOVERY', exact: true }).click();
    await expect(page.getByRole('alert').filter({ hasText: 'Microphone blocked' })).toBeVisible();
    expect(starts).toBe(0);
});

test('WAV encoder preserves samples and headers', async () => {
    const bytes = await wavBlob([new Float32Array([-1, 0, 1])], 16000).arrayBuffer();
    const view = new DataView(bytes);
    expect(bytes.byteLength).toBe(50);
    expect(view.getInt16(44, true)).toBe(-32768);
    expect(view.getInt16(46, true)).toBe(0);
    expect(view.getInt16(48, true)).toBe(32767);
});
