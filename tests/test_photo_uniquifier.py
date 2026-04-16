"""Tests for app/services/photo_uniquifier.py — subtle image uniquification."""

import os
import tempfile
from io import BytesIO

import pytest
from PIL import Image

from app.services.photo_uniquifier import (
    uniquify_image,
    uniquify_image_bytes,
    _random_crop_resize,
    _random_brightness,
    _random_noise,
)


# ---------------------------------------------------------------------------
# Helpers — generate test images programmatically
# ---------------------------------------------------------------------------

def _make_jpeg_bytes(width=200, height=150, color=(128, 64, 200)) -> bytes:
    """Create a solid-color JPEG image as bytes."""
    img = Image.new("RGB", (width, height), color)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def _make_jpeg_file(tmpdir, name="test.jpg", **kw) -> str:
    path = os.path.join(tmpdir, name)
    with open(path, "wb") as f:
        f.write(_make_jpeg_bytes(**kw))
    return path


def _make_png_bytes(width=200, height=150, color=(50, 100, 200, 255)) -> bytes:
    img = Image.new("RGBA", (width, height), color)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_gradient_bytes(width=200, height=150) -> bytes:
    """Gradient image — produces real per-pixel variation, unlike solid color."""
    img = Image.new("RGB", (width, height))
    for x in range(width):
        for y in range(height):
            img.putpixel((x, y), (x % 256, y % 256, (x + y) % 256))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# uniquify_image (file path API)
# ---------------------------------------------------------------------------

class TestUniquifyImage:
    def test_returns_jpeg_bytes(self, tmp_path):
        path = _make_jpeg_file(str(tmp_path))
        out = uniquify_image(path)
        assert isinstance(out, bytes)
        assert len(out) > 0
        # JPEG magic bytes
        assert out[:2] == b"\xff\xd8"

    def test_preserves_original_dimensions(self, tmp_path):
        path = _make_jpeg_file(str(tmp_path), width=300, height=200)
        out = uniquify_image(path)
        result = Image.open(BytesIO(out))
        assert result.size == (300, 200)

    def test_quality_parameter_affects_size(self, tmp_path):
        path = _make_jpeg_file(str(tmp_path), width=400, height=300)
        # Use gradient — solid colour compresses to ~same size at any quality
        with open(path, "wb") as f:
            f.write(_make_gradient_bytes(400, 300))

        low_q = uniquify_image(path, quality=20)
        high_q = uniquify_image(path, quality=95)
        assert len(low_q) < len(high_q)

    def test_handles_png_input(self, tmp_path):
        """PNG input should be converted to RGB and saved as JPEG."""
        path = os.path.join(str(tmp_path), "in.png")
        with open(path, "wb") as f:
            f.write(_make_png_bytes())
        out = uniquify_image(path)
        # Output is JPEG regardless of input format
        assert out[:2] == b"\xff\xd8"

    def test_broken_file_raises(self, tmp_path):
        """Garbage data → PIL UnidentifiedImageError or similar."""
        bad = os.path.join(str(tmp_path), "bad.jpg")
        with open(bad, "wb") as f:
            f.write(b"not a real image, just text")
        with pytest.raises(Exception):
            uniquify_image(bad)

    def test_nonexistent_file_raises(self):
        with pytest.raises(FileNotFoundError):
            uniquify_image("/tmp/does-not-exist-xyzzy-9999.jpg")

    def test_default_quality_works(self, tmp_path):
        """Calling without quality kwarg should produce a valid JPEG."""
        path = _make_jpeg_file(str(tmp_path), width=300, height=200)
        out = uniquify_image(path)
        assert out[:2] == b"\xff\xd8"
        # Output is a real JPEG that can be decoded
        result = Image.open(BytesIO(out))
        assert result.size == (300, 200)
        assert result.format == "JPEG"


# ---------------------------------------------------------------------------
# uniquify_image_bytes (bytes API)
# ---------------------------------------------------------------------------

class TestUniquifyImageBytes:
    def test_returns_jpeg_bytes(self):
        data = _make_jpeg_bytes()
        out = uniquify_image_bytes(data)
        assert isinstance(out, bytes)
        assert out[:2] == b"\xff\xd8"

    def test_output_differs_from_input(self):
        """Result must differ byte-for-byte from input (purpose of uniquification)."""
        data = _make_gradient_bytes(150, 100)
        out = uniquify_image_bytes(data)
        assert out != data

    def test_two_calls_produce_different_outputs(self):
        """Each call uses random noise → outputs should differ."""
        data = _make_gradient_bytes(150, 100)
        out1 = uniquify_image_bytes(data)
        out2 = uniquify_image_bytes(data)
        assert out1 != out2

    def test_preserves_dimensions(self):
        data = _make_jpeg_bytes(width=320, height=240)
        out = uniquify_image_bytes(data)
        result = Image.open(BytesIO(out))
        assert result.size == (320, 240)

    def test_handles_png_bytes(self):
        data = _make_png_bytes()
        out = uniquify_image_bytes(data)
        assert out[:2] == b"\xff\xd8"

    def test_broken_bytes_raise(self):
        with pytest.raises(Exception):
            uniquify_image_bytes(b"definitely not an image")

    def test_quality_parameter(self):
        data = _make_gradient_bytes(400, 300)
        low_q = uniquify_image_bytes(data, quality=20)
        high_q = uniquify_image_bytes(data, quality=95)
        assert len(low_q) < len(high_q)


# ---------------------------------------------------------------------------
# Internal helpers — _random_crop_resize, _random_brightness, _random_noise
# ---------------------------------------------------------------------------

class TestRandomCropResize:
    def test_preserves_dimensions(self):
        img = Image.new("RGB", (100, 80), (100, 100, 100))
        out = _random_crop_resize(img)
        assert out.size == (100, 80)

    def test_returns_pil_image(self):
        img = Image.new("RGB", (50, 50), (200, 100, 50))
        out = _random_crop_resize(img)
        assert isinstance(out, Image.Image)


class TestRandomBrightness:
    def test_preserves_dimensions(self):
        img = Image.new("RGB", (60, 40), (128, 128, 128))
        out = _random_brightness(img)
        assert out.size == (60, 40)

    def test_returns_pil_image(self):
        img = Image.new("RGB", (40, 40), (50, 50, 50))
        out = _random_brightness(img)
        assert isinstance(out, Image.Image)


class TestRandomNoise:
    def test_preserves_dimensions(self):
        img = Image.new("RGB", (50, 50), (100, 100, 100))
        out = _random_noise(img)
        assert out.size == (50, 50)

    def test_modifies_pixels(self):
        """Noise should change at least some pixel values."""
        img = Image.new("RGB", (40, 40), (128, 128, 128))
        out = _random_noise(img)
        # Compare raw bytes — solid grey input + noise → some pixels must differ
        assert img.tobytes() != out.tobytes()

    def test_returns_pil_image(self):
        img = Image.new("RGB", (30, 30), (50, 50, 50))
        out = _random_noise(img)
        assert isinstance(out, Image.Image)


# ---------------------------------------------------------------------------
# HEIC support (via pillow-heif)
# ---------------------------------------------------------------------------

class TestHeicSupport:
    def test_heic_can_be_processed_after_register(self):
        """If HEIC bytes are provided after pillow-heif is registered,
        uniquify_image_bytes should handle them. We construct a HEIC by
        first encoding a real image."""
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            pytest.skip("pillow-heif not installed")

        # Encode a JPEG into HEIF format
        img = Image.new("RGB", (100, 80), (200, 100, 50))
        buf = BytesIO()
        try:
            img.save(buf, format="HEIF", quality=80)
        except (KeyError, OSError) as e:
            pytest.skip(f"HEIC encoding not supported in this build: {e}")

        heic_data = buf.getvalue()
        out = uniquify_image_bytes(heic_data)
        # Output is JPEG regardless of input
        assert out[:2] == b"\xff\xd8"
        result = Image.open(BytesIO(out))
        assert result.size == (100, 80)
