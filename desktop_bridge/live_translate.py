"""Explicit microphone-to-translation-to-virtual-cable orchestration."""

from __future__ import annotations

from getpass import getpass
from queue import Empty, Full, Queue
from threading import Event, Thread
import os
import sys
import time
from typing import Callable

from desktop_bridge.audio_devices import AudioDevice, DeviceError, list_devices, select_input_device, select_output_device
from desktop_bridge.config import BridgeConfig
from desktop_bridge.live_client import LiveClientError, TranslationConnection, language_code, login, logout, server_origin
from desktop_bridge.microphone import CapturedPhrase, CaptureError, CaptureSummary, capture_microphone
from desktop_bridge.wav_player import PlaybackError, WavError, play_wav_bytes


def select_live_devices(mic_index: str, output_index: str,
                        devices: list[AudioDevice]) -> tuple[AudioDevice, AudioDevice]:
    if not mic_index.isdigit() or not output_index.isdigit():
        raise DeviceError("Choose current numeric indices from 'devices' for --mic and --output.")
    microphone = select_input_device(devices, mic_index)
    if microphone.cable_output:
        raise DeviceError("CABLE Output cannot be used as the live microphone; select a physical microphone.")
    output = select_output_device(devices, output_index)
    if not output.cable_input:
        raise DeviceError("Live output must be CABLE Input, the playback side of VB-CABLE.")
    return microphone, output


def _keyboard_action() -> str | None:
    if not sys.stdin.isatty() or os.name != "nt":
        return None
    import msvcrt
    if not msvcrt.kbhit():
        return None
    return msvcrt.getwch().lower()


def run_live(mic: AudioDevice, output: AudioDevice, source: str, target: str, server: str,
             *, diagnostics: bool = False, save_history: bool = False,
             session_id: str | None = None, duration: float | None = None,
             report: Callable[[str], None] = print) -> int:
    """Do not open a microphone until explicit CLI invocation and authenticated socket readiness."""
    origin = server_origin(server)
    language_code(source, allow_auto=True)
    language_code(target)
    if mic.cable_output or mic.input_channels < 1 or not output.cable_input:
        raise DeviceError("Select a physical microphone and CABLE Input playback device.")
    if save_history != (session_id is not None):
        raise LiveClientError("History requires both --save-history and --session-id.")
    email = input("TalkBuddy email: ").strip()
    password = getpass("TalkBuddy password: ")
    client = login(origin, email, password)
    del password
    stop_event = Event()
    pause_event = Event()
    capture_done = Event()
    pending: Queue[CapturedPhrase] = Queue(maxsize=3)
    capture_errors: list[Exception] = []
    capture_summaries: list[CaptureSummary] = []
    dropped_phrases = 0

    def on_phrase(phrase: CapturedPhrase) -> None:
        nonlocal dropped_phrases
        try:
            pending.put_nowait(phrase)
        except Full:
            dropped_phrases += 1
            report("Translation backlog full; a phrase was discarded.")

    def record() -> None:
        try:
            capture_summaries.append(capture_microphone(
                mic, on_phrase, duration=duration, diagnostics=diagnostics,
                stop_event=stop_event, pause_event=pause_event, report=report,
            ))
        except Exception as exc:
            capture_errors.append(exc)
        finally:
            capture_done.set()

    thread: Thread | None = None
    try:
        cookie = client.cookies.get("talkbuddy_session")
        if not cookie:
            raise LiveClientError("Login did not create a session.")
        with TranslationConnection(origin, cookie, source, target,
                                   save_history=save_history, session_id=session_id) as connection:
            report("Authenticated translation ready. Press P to pause, R to resume, Q or Ctrl+C to stop.")
            last_exchange = time.perf_counter()
            thread = Thread(target=record, name="TalkBuddyMicrophone", daemon=False)
            thread.start()
            while True:
                action = _keyboard_action()
                if action == "q":
                    stop_event.set()
                    break
                if action == "p":
                    pause_event.set()
                    report("Capture paused; audio frames are discarded locally.")
                elif action == "r":
                    connection.close()
                    connection.__enter__()  # new socket; no phrase is in flight on this thread
                    last_exchange = time.perf_counter()
                    pause_event.clear()
                    report("Capture resumed.")
                if capture_done.is_set() and pending.empty():
                    break
                try:
                    phrase = pending.get(timeout=0.1)
                except Empty:
                    continue
                try:
                    if time.perf_counter() - last_exchange >= 45:
                        connection.close()
                        connection.__enter__()  # reconnect only before submitting a new phrase
                    response = connection.translate(phrase)
                    last_exchange = time.perf_counter()
                    if response.wav_bytes is None:
                        report(f"Phrase {response.chunk_id}: translated text received; speech unavailable ({response.speech_error}).")
                        continue
                    playback_started_ms = time.perf_counter() * 1000
                    play_wav_bytes(response.wav_bytes, output)
                    if diagnostics:
                        report(
                            f"Phrase {response.chunk_id} timing: capture={phrase.capture_duration_ms:.0f}ms; "
                            f"speech-end-to-submit={max(0, response.submitted_at_ms - phrase.speech_end_at_ms):.0f}ms; "
                            f"WS-result={response.websocket_roundtrip_ms:.0f}ms; "
                            f"STT={response.stt_ms if response.stt_ms is not None else 'unavailable'}ms; "
                            f"translation={response.translation_ms if response.translation_ms is not None else 'unavailable'}ms; "
                            f"TTS={response.tts_ms if response.tts_ms is not None else 'unavailable'}ms; "
                            f"playback-queue-wait={max(0, playback_started_ms - response.audio_received_at_ms):.0f}ms; "
                            f"speech-end-to-playback-call={max(0, playback_started_ms - phrase.speech_end_at_ms):.0f}ms"
                        )
                finally:
                    pending.task_done()
            if capture_errors:
                raise CaptureError("Microphone capture stopped due to a device error.") from capture_errors[0]
            if capture_summaries:
                summary = capture_summaries[0]
                report(f"Stopped: {summary.phrases} captured phrases; {dropped_phrases} backlog drops; "
                       f"{summary.dropped_frames} dropped input frames. No raw audio saved.")
            return 0
    except KeyboardInterrupt:
        report("Stopping live translation.")
        return 0
    finally:
        stop_event.set()
        pause_event.set()
        if thread is not None and thread.ident is not None:
            thread.join(timeout=5)
        while True:
            try:
                pending.get_nowait()
                pending.task_done()
            except Empty:
                break
        logout(origin, client)
        client.close()
