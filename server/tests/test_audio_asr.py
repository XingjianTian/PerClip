from __future__ import annotations

import json
from urllib.request import Request

import pytest

from perclip_ingest.audio_asr import (
    AudioAsrSettings,
    BaiduAsrError,
    BaiduShortAudioRecognizer,
    infer_baidu_audio_format,
    is_audio_payload,
    render_asr_text_note,
)


def test_identifies_audio_payloads():
    assert is_audio_payload("audio/mp4", "recording.m4a")
    assert is_audio_payload("", "recording.wav")
    assert not is_audio_payload("image/jpeg", "photo.jpg")


def test_infers_baidu_audio_format_from_filename_and_mime_type():
    assert infer_baidu_audio_format("recording.m4a", "audio/mp4") == "m4a"
    assert infer_baidu_audio_format("", "audio/x-wav") == "wav"
    assert infer_baidu_audio_format("", "audio/aac") == "m4a"


def test_render_asr_text_note_includes_transcription_and_audio_metadata():
    text = render_asr_text_note(
        transcription="今天要记录一个想法。",
        filename="recording.m4a",
        mime_type="audio/mp4",
        size_bytes=123,
        engine="baidu_short_asr",
        audio_format="m4a",
        captured_at="2026-07-02T00:00:00Z",
    )

    assert "语音转写" in text
    assert "recording.m4a" in text
    assert "今天要记录一个想法。" in text


def test_baidu_recognizer_posts_json_and_returns_transcript(monkeypatch):
    calls: list[Request] = []

    def fake_request_json(request, timeout):
        calls.append(request)
        if "oauth/2.0/token" in request.full_url:
            return {"access_token": "token"}
        body = json.loads(request.data.decode("utf-8"))
        assert body["format"] == "m4a"
        assert body["rate"] == 16000
        assert body["channel"] == 1
        assert body["dev_pid"] == 1537
        assert body["len"] == 5
        assert body["token"] == "token"
        return {"err_no": 0, "err_msg": "success.", "result": ["转写成功。"]}

    monkeypatch.setattr("perclip_ingest.audio_asr.request_json", fake_request_json)
    recognizer = BaiduShortAudioRecognizer(
        AudioAsrSettings(
            enabled=True,
            baidu_api_key="api",
            baidu_secret_key="secret",
        ),
    )

    result = recognizer.recognize(
        audio=b"audio",
        filename="recording.m4a",
        mime_type="audio/mp4",
        cuid="device",
    )

    assert result.ok is True
    assert result.text == "转写成功。"
    assert len(calls) == 2


def test_baidu_recognizer_reports_api_errors(monkeypatch):
    def fake_request_json(request, timeout):
        if "oauth/2.0/token" in request.full_url:
            return {"access_token": "token"}
        return {"err_no": 3301, "err_msg": "speech quality error"}

    monkeypatch.setattr("perclip_ingest.audio_asr.request_json", fake_request_json)
    recognizer = BaiduShortAudioRecognizer(
        AudioAsrSettings(
            enabled=True,
            baidu_api_key="api",
            baidu_secret_key="secret",
        ),
    )

    result = recognizer.recognize(
        audio=b"audio",
        filename="recording.m4a",
        mime_type="audio/mp4",
        cuid="device",
    )

    assert result.ok is False
    assert result.status == "baidu_error:3301"
    assert result.message == "speech quality error"


def test_baidu_recognizer_splits_audio_when_baidu_reports_too_long():
    recognizer = BaiduShortAudioRecognizer(
        AudioAsrSettings(
            enabled=True,
            baidu_api_key="api",
            baidu_secret_key="secret",
        ),
    )
    recognizer._access_token = "token"
    recognizer._split_audio = lambda audio, filename: [b"one", b"two"]
    calls = []

    def fake_post_asr(audio, audio_format, cuid, token):
        calls.append((audio, audio_format, cuid, token))
        if audio == b"long-audio":
            return {"err_no": 3308, "err_msg": "speech too long."}
        return {"err_no": 0, "err_msg": "success.", "result": [audio.decode()]}

    recognizer._post_asr = fake_post_asr

    result = recognizer.recognize(
        audio=b"long-audio",
        filename="recording.m4a",
        mime_type="audio/mp4",
        cuid="device",
    )

    assert result.ok is True
    assert result.text == "one\ntwo"
    assert result.status == "success"
    assert [call[0] for call in calls] == [b"long-audio", b"one", b"two"]
    assert all(call[1] == "m4a" for call in calls)


def test_baidu_recognizer_raises_network_errors(monkeypatch):
    def fake_request_json(request, timeout):
        raise BaiduAsrError("network failed")

    monkeypatch.setattr("perclip_ingest.audio_asr.request_json", fake_request_json)
    recognizer = BaiduShortAudioRecognizer(
        AudioAsrSettings(
            enabled=True,
            baidu_api_key="api",
            baidu_secret_key="secret",
        ),
    )

    with pytest.raises(BaiduAsrError, match="network failed"):
        recognizer.recognize(
            audio=b"audio",
            filename="recording.m4a",
            mime_type="audio/mp4",
            cuid="device",
        )
