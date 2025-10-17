import logging
from pathlib import Path

from utils import run_subprocess

logger = logging.getLogger("media_manager")

class AssetGeneratorService:

    def __init__(self, ffmpeg_path: str):
        self.ffmpeg_path = ffmpeg_path

    def create_black_video(self, out_path: Path, duration: int, resolution: str, overwrite: bool) -> bool:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            self.ffmpeg_path,
            "-y" if overwrite else "-n",
            "-f", "lavfi", "-i", f"color=c=black:s={resolution}:r=30",
            "-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-loglevel", "error", str(out_path)
        ]
        ok, _, _ = run_subprocess(cmd)
        return ok

    def create_backdrop_image(self, out_path: Path, resolution: str, overwrite: bool) -> bool:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            self.ffmpeg_path,
            "-y" if overwrite else "-n",
            "-f", "lavfi", "-i", f"color=c=black:s={resolution}",
            "-vframes", "1", "-q:v", "2", "-loglevel", "error", str(out_path)
        ]
        ok, _, _ = run_subprocess(cmd)
        return ok