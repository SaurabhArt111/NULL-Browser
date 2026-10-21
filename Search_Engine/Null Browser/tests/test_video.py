"""ffmpeg helpers of the H.264 bridge (no Qt needed). The conversion tests are skipped when ffmpeg cannot make H.264 test clips."""
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from null_browser.video import ffmpeg

EXE = ffmpeg.find()
CAPS = ffmpeg.inspect(EXE) if EXE else {}


class FindTests(unittest.TestCase):
    def test_explicit_path_wins(self):
        self.assertEqual(ffmpeg.find(sys.executable), sys.executable)

    def test_unusable_caps(self):
        self.assertFalse(ffmpeg.usable({}))
        self.assertFalse(ffmpeg.usable({"vp9": True, "opus": False}))
        self.assertTrue(ffmpeg.usable({"vp8": True, "opus": True}))


class AdaptTests(unittest.TestCase):
    def tc(self):
        return ffmpeg.Transcoder("ffmpeg", {"vp9": True, "opus": True})

    def test_slow_machine_steps_the_height_down(self):
        t = self.tc()
        self.assertIsNone(t.max_height)
        for _ in range(4):
            t._adapt(2.0, 3.0)                      # takes 1.5x real time
        self.assertIsNotNone(t.max_height)
        self.assertLessEqual(t.max_height, 720)

    def test_fast_machine_recovers(self):
        t = self.tc()
        t._step = 3
        for _ in range(30):
            t._adapt(2.0, 0.2)
        self.assertLess(t._step, 3)

    def test_tiny_pieces_are_ignored(self):
        t = self.tc()
        t._adapt(0.05, 5.0)
        self.assertEqual(t.stats["pieces"], 0)


@unittest.skipUnless(EXE and ffmpeg.usable(CAPS), "no usable ffmpeg")
class ConvertTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="null-vtest-")
        enc = subprocess.run([EXE, "-hide_banner", "-encoders"], capture_output=True).stdout.decode("utf-8", "replace")
        cls.can = "libx264" in enc
        if cls.can:
            cls.mp4 = os.path.join(cls.tmp, "clip.mp4")
            subprocess.run([EXE, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=25:duration=2",
                            "-f", "lavfi", "-i", "sine=duration=2", "-c:v", "libx264", "-g", "25", "-pix_fmt", "yuv420p", "-c:a", "aac",
                            "-movflags", "+frag_keyframe+empty_moov+default_base_moof", "-frag_duration", "1000000", "-f", "mp4", cls.mp4], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def split(self):
        data = open(self.mp4, "rb").read()
        i, init, frags, cur = 0, b"", [], b""
        while i + 8 <= len(data):
            size, typ = struct.unpack(">I4s", data[i:i + 8])
            seg = data[i:i + size]
            i += size
            if typ in (b"ftyp", b"moov"):
                init += seg
            elif typ == b"moof":
                cur = seg
            elif typ == b"mdat":
                frags.append(cur + seg)
        return init, frags

    def setUp(self):
        if not self.can:
            self.skipTest("ffmpeg has no H.264 encoder for the test clip")

    def test_fragment_becomes_webm(self):
        init, frags = self.split()
        tc = ffmpeg.Transcoder(EXE, CAPS)
        out = tc.mse(init, frags[0], True, False, 1.0)
        self.assertEqual(out[:4], b"\x1a\x45\xdf\xa3")              # EBML header
        out = tc.mse(init, frags[0], False, True, 1.0)
        self.assertEqual(out[:4], b"\x1a\x45\xdf\xa3")

    def test_garbage_raises(self):
        tc = ffmpeg.Transcoder(EXE, CAPS)
        with self.assertRaises(Exception):
            tc.mse(b"not a movie", b"at all", True, False, 1.0)

    def test_probe_and_stream_file(self):
        info = ffmpeg.probe_file(EXE, self.mp4)
        self.assertTrue(info["video"] and info["audio"])
        self.assertAlmostEqual(info["duration"], 2.0, delta=0.3)
        tc = ffmpeg.Transcoder(EXE, CAPS)
        got = []
        self.assertTrue(ffmpeg.stream_file(tc, self.mp4, "video", got.append, lambda: False))
        self.assertEqual(b"".join(got)[:4], b"\x1a\x45\xdf\xa3")


class ShimTests(unittest.TestCase):
    def test_shim_parses(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        path = os.path.join(os.path.dirname(ffmpeg.__file__), "shim.js")
        self.assertEqual(subprocess.run([node, "--check", path], capture_output=True).returncode, 0)


if __name__ == "__main__":
    unittest.main()
