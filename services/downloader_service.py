import logging
import time
from typing import Callable

from utils import run_subprocess

logger = logging.getLogger("media_manager")

class DownloaderService:

    def __init__(self, yt_dlp_path: str):
        self.yt_dlp_path = yt_dlp_path

    def download_trailer(self, youtube_key: str, out_template: str, title: str, failure_callback: Callable) -> bool:
        url = f"https://www.youtube.com/watch?v={youtube_key}"
        for attempt in range(1, 4):
            cmd = [
                self.yt_dlp_path,

                # "--downloader", "aria2c" <--- User may use aria2c to maximize speed, just make sure to have it installed with yt-dlp

                "--sponsorblock-remove", "interaction,outro",
                "--quiet",
                "-f", "bestvideo[height<=1080]+bestaudio/best",
                "--merge-output-format", "mp4",
                "-o", out_template, url
            ]
            ok, _, stderr = run_subprocess(cmd)

            if ok:
                logger.info(f"💾 Downloaded successfully: [cyan]{title}[/cyan] [dim]{url}[/]")
                return True

            if attempt < 3:
                wait_time = attempt * 2
                logger.warning(f"[yellow]Warning:[/] Download failed (attempt {attempt}/3) for [cyan]{title}[/cyan]. Retrying in {wait_time}s...")
                if stderr:
                    logger.info(f"[dim yellow]Reason: {stderr.strip().splitlines()[-1]}[/dim yellow]")
                time.sleep(wait_time)

        logger.info(f"🔴[bold red] Failed to download trailer after 3 attempts: {title}[/bold red]")
        failure_callback()
        return False