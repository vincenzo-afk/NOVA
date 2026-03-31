"""Voice activity detection with silero-vad and energy fallback."""

from __future__ import annotations

from io import BytesIO
import time
import wave


class VADRecorder:
    def __init__(
        self,
        silence_ms: int = 800,
        sample_rate: int = 16_000,
        frame_ms: int = 30,
        energy_threshold: float = 0.015,
        max_capture_seconds: float = 30.0,
        use_silero: bool = True,
    ):
        self.silence_ms = silence_ms
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.energy_threshold = energy_threshold
        self.max_capture_seconds = max_capture_seconds
        self.use_silero = use_silero

    def capture_until_silence(self) -> bytes:
        if self.use_silero:
            try:
                return self._capture_with_silero()
            except Exception:
                # fall back to energy-based VAD if silero isn't available or fails
                pass
        try:
            import sounddevice as sd
            import numpy as np
        except Exception:
            time.sleep(self.silence_ms / 1000.0)
            return b""

        frame_samples = max(1, int(self.sample_rate * self.frame_ms / 1000))
        silence_frames = max(1, int(self.silence_ms / self.frame_ms))
        max_frames = int((self.max_capture_seconds * 1000) / self.frame_ms)
        pre_roll_frames = max(1, int(250 / self.frame_ms))

        captured: list[np.ndarray] = []
        pre_roll: list[np.ndarray] = []
        speaking = False
        silent_count = 0

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=frame_samples,
        ) as stream:
            for _ in range(max_frames):
                chunk, overflow = stream.read(frame_samples)
                if overflow:
                    continue

                frame = np.asarray(chunk, dtype=np.int16).flatten()
                if frame.size == 0:
                    continue
                energy = float(np.mean(np.abs(frame))) / 32768.0

                if not speaking:
                    pre_roll.append(frame.copy())
                    if len(pre_roll) > pre_roll_frames:
                        pre_roll.pop(0)

                if energy >= self.energy_threshold:
                    if not speaking:
                        speaking = True
                        captured.extend(pre_roll)
                        pre_roll = []
                    captured.append(frame.copy())
                    silent_count = 0
                elif speaking:
                    captured.append(frame.copy())
                    silent_count += 1
                    if silent_count >= silence_frames:
                        break

        if not captured:
            return b""

        pcm = np.concatenate(captured).astype(np.int16)
        wav_buf = BytesIO()
        with wave.open(wav_buf, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(pcm.tobytes())
        return wav_buf.getvalue()

    def _capture_with_silero(self) -> bytes:
        try:
            import sounddevice as sd
            import numpy as np
            import torch
        except Exception:
            raise RuntimeError("silero-vad dependencies are missing")

        try:
            from silero_vad import VADIterator, load_silero_vad
        except Exception:
            raise RuntimeError("silero-vad package not available")

        model = load_silero_vad()
        vad = VADIterator(model, sampling_rate=self.sample_rate)
        if hasattr(vad, "reset_states"):
            vad.reset_states()

        frame_samples = max(1, int(self.sample_rate * self.frame_ms / 1000))
        max_frames = int((self.max_capture_seconds * 1000) / self.frame_ms)
        pre_roll_frames = max(1, int(250 / self.frame_ms))
        silence_frames = max(1, int(self.silence_ms / self.frame_ms))

        captured: list[np.ndarray] = []
        pre_roll: list[np.ndarray] = []
        speaking = False
        end_detected = False
        silent_count = 0

        def _frame_to_tensor(frame: np.ndarray) -> torch.Tensor:
            audio = frame.astype("float32") / 32768.0
            return torch.from_numpy(audio)

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=frame_samples,
        ) as stream:
            for _ in range(max_frames):
                chunk, overflow = stream.read(frame_samples)
                if overflow:
                    continue
                frame = np.asarray(chunk, dtype=np.int16).flatten()
                if frame.size == 0:
                    continue

                if not speaking:
                    pre_roll.append(frame.copy())
                    if len(pre_roll) > pre_roll_frames:
                        pre_roll.pop(0)

                speech_dict = vad(_frame_to_tensor(frame), return_seconds=False)
                if speech_dict and "start" in speech_dict and not speaking:
                    speaking = True
                    captured.extend(pre_roll)
                    pre_roll = []
                if speaking:
                    captured.append(frame.copy())
                    if speech_dict:
                        silent_count = 0
                    else:
                        silent_count += 1
                if speech_dict and "end" in speech_dict and speaking:
                    end_detected = True
                    break
                if speaking and silent_count >= silence_frames:
                    end_detected = True
                    break

        if not captured or not end_detected:
            return b""

        pcm = np.concatenate(captured).astype(np.int16)
        wav_buf = BytesIO()
        with wave.open(wav_buf, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(pcm.tobytes())
        return wav_buf.getvalue()
