import pytest

from app.media.errors import MediaError
from app.media.ffmpeg import FFmpeg, build_filter_graph
from tests.conftest import make_png, needs_ffmpeg


def test_vertical_conversion_never_crops_the_original_frame():
    for fill in ("black", "blur"):
        graph, w, h = build_filter_graph(src_w=1920, src_h=1080, aspect="9:16", fill_mode=fill, has_watermark=False,
                                         watermark_size_pct=15, watermark_opacity=0.8, watermark_margin_pct=3)
        assert (w, h) == (1080, 1920)
        fg = graph.split("[fg0]")[-1] if fill == "blur" else graph
        assert "force_original_aspect_ratio=decrease" in fg
        assert "crop" not in fg  # only the blurred background is cropped, never the video itself


def test_watermark_graph_bottom_right_with_opacity():
    graph, w, h = build_filter_graph(src_w=640, src_h=360, aspect="original", fill_mode="blur", has_watermark=True,
                                     watermark_size_pct=20, watermark_opacity=0.5, watermark_margin_pct=5)
    assert (w, h) == (640, 360)
    assert "colorchannelmixer=aa=0.500" in graph
    assert "overlay=W-w-32:H-h-32" in graph
    assert "scale=128:" in graph  # 20% of 640


def test_invalid_aspect_rejected():
    with pytest.raises(MediaError):
        build_filter_graph(src_w=10, src_h=10, aspect="4:3", fill_mode="blur", has_watermark=False,
                           watermark_size_pct=1, watermark_opacity=1, watermark_margin_pct=1)


@needs_ffmpeg
def test_ensure_mp4_copy_and_transcode(settings, sample_media, tmp_path):
    ff = FFmpeg(settings)
    out = ff.ensure_mp4(sample_media["mp4"], tmp_path / "a.mp4", timeout=60)
    assert "mp4" in out.format_name and out.acodec == "aac"
    out2 = ff.ensure_mp4(sample_media["mkv"], tmp_path / "b.mp4", timeout=60)  # MJPEG can't go in MP4
    assert out2.vcodec != "mjpeg" and out2.acodec == "aac"


@needs_ffmpeg
def test_process_watermark_vertical_preserves_audio(settings, sample_media, tmp_path):
    wm = tmp_path / "wm.png"
    wm.write_bytes(make_png(200, 80))
    out = FFmpeg(settings).process(sample_media["mp4"], tmp_path / "out.mp4", aspect="9:16", fill_mode="blur",
                                   watermark=wm, watermark_size_pct=20, watermark_opacity=0.6,
                                   watermark_margin_pct=3, timeout=120)
    assert (out.width, out.height) == (720, 1280)
    assert out.acodec == "aac"
    assert out.duration and out.duration > 1.5


@needs_ffmpeg
def test_process_video_without_audio(settings, sample_media, tmp_path):
    out = FFmpeg(settings).process(sample_media["silent"], tmp_path / "s.mp4", aspect="original", fill_mode="black",
                                   watermark=None, watermark_size_pct=15, watermark_opacity=1,
                                   watermark_margin_pct=3, timeout=60)
    assert out.acodec is None and (out.width, out.height) == (360, 640)


@needs_ffmpeg
def test_thumbnails(settings, sample_media, tmp_path):
    thumbs = FFmpeg(settings).thumbnails(sample_media["mp4"], tmp_path / "t", duration=2.0, count=3)
    assert len(thumbs) == 3 and all(t.read_bytes()[:2] == b"\xff\xd8" for t in thumbs)


@needs_ffmpeg
def test_corrupt_input_gives_clear_error(settings, tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"this is not a video" * 100)
    with pytest.raises(MediaError) as exc:
        FFmpeg(settings).probe(bad)
    assert exc.value.code in ("ffmpeg_failed", "invalid_media")
    assert "failed" in exc.value.message or "not a readable" in exc.value.message


def test_missing_ffmpeg_binary(settings, tmp_path):
    settings.ffprobe_path = "/nonexistent/ffprobe"
    f = tmp_path / "x.mp4"
    f.write_bytes(b"x")
    with pytest.raises(MediaError) as exc:
        FFmpeg(settings).probe(f)
    assert exc.value.code == "ffmpeg_missing"


# ----------------------------------------------------------------- API level
def _make_video_file(admin, settings, sample_media):
    import shutil

    from app.db import session_scope
    from app.models import FileKind, MediaFile

    d = settings.media_dir / "job1"
    d.mkdir(parents=True)
    shutil.copy(sample_media["mp4"], d / "video.mp4")
    with session_scope() as db:
        mf = MediaFile(user_id=admin, kind=FileKind.VIDEO, path="job1/video.mp4", filename="sample.mp4",
                       mime_type="video/mp4", size_bytes=(d / "video.mp4").stat().st_size, acodec="aac")
        db.add(mf)
        db.flush()
        return mf.id


def test_watermark_upload_validation(client):
    r = client.post("/api/watermarks", files={"file": ("x.png", b"GIF89a....", "image/png")})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "invalid_png"
    r = client.post("/api/watermarks", files={"file": ("logo.png", make_png(), "image/png")})
    assert r.status_code == 201 and r.json()["width"] == 120 and r.json()["expires_at"] is None
    assert len(client.get("/api/watermarks").json()["items"]) == 1


def test_watermark_size_limit(client, settings):
    settings.max_watermark_mb = 0
    r = client.post("/api/watermarks", files={"file": ("logo.png", make_png(), "image/png")})
    assert r.status_code == 413


def test_process_requires_some_change(client, admin, settings, sample_media):
    fid = _make_video_file(admin, settings, sample_media)
    r = client.post(f"/api/media/{fid}/process", json={})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "nothing_to_do"
    r = client.post(f"/api/media/{fid}/process", json={"watermark_file_id": "doesnotexist"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "invalid_watermark"
    r = client.post(f"/api/media/{fid}/process", json={"watermark_opacity": 5, "thumbnails": True})
    assert r.status_code == 422


@needs_ffmpeg
def test_process_job_end_to_end(client, queue, admin, settings, sample_media):
    fid = _make_video_file(admin, settings, sample_media)
    wm = client.post("/api/watermarks", files={"file": ("logo.png", make_png(), "image/png")}).json()
    preset = client.post("/api/presets", json={"name": "Reels", "aspect": "9:16", "watermark_file_id": wm["id"],
                                               "watermark_size_pct": 25, "thumbnails": True}).json()
    queue.run = True
    r = client.post(f"/api/media/{fid}/process", json={"preset_id": preset["id"]})
    assert r.status_code == 202, r.text
    job = client.get(f"/api/jobs/{r.json()['id']}").json()
    assert job["status"] == "completed", job
    out = client.get(f"/api/media/{job['result']['media_file_id']}").json()
    assert out["kind"] == "processed" and (out["width"], out["height"]) == (720, 1280) and out["has_audio"]
    assert len(job["result"]["thumbnail_file_ids"]) == 3
    assert len(out["children"]) == 3


@needs_ffmpeg
def test_process_job_with_corrupt_source_fails_cleanly(client, queue, admin, settings, sample_media):
    fid = _make_video_file(admin, settings, sample_media)
    (settings.media_dir / "job1" / "video.mp4").write_bytes(b"corrupted")
    queue.run = True
    r = client.post(f"/api/media/{fid}/process", json={"aspect": "9:16"})
    job = client.get(f"/api/jobs/{r.json()['id']}").json()
    assert job["status"] == "failed" and job["error"]["code"] in ("ffmpeg_failed", "invalid_media")
