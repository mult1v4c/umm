import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config import BACKDROP_FILENAME, TRAILER_SUFFIX

logger = logging.getLogger("media_manager")


@dataclass
class MoviePaths:
    root: Path
    placeholder: Path
    backdrop: Path

    def get_trailer_path(self) -> Optional[Path]:
        try:
            return next(self.root.glob(f"*{TRAILER_SUFFIX}.*"))
        except StopIteration:
            return None


class FileSystemManager:

    def __init__(self, download_folder: str):
        self.download_folder = Path(download_folder).expanduser()

    def get_movie_paths(self, movie_folder_name: str) -> MoviePaths:
        movie_folder = self.download_folder / movie_folder_name
        placeholder_filename = f"{movie_folder_name}.mp4"
        return MoviePaths(
            root=movie_folder,
            placeholder=movie_folder / placeholder_filename,
            backdrop=movie_folder / BACKDROP_FILENAME
        )

    def prepare_movie_folder_name(self, title: str, release_date: str) -> str:
        year_str = release_date[:4] if release_date and len(release_date) >= 4 else "N/A"
        folder_name = f"{title} ({year_str})"
        return re.sub(r'[<>:"/\\|?*]+', ' ', folder_name).strip()

    def clean_empty_folders(self, dry_run: bool):
        removed_count = 0
        if not self.download_folder.is_dir():
            return

        logger.info(f"Scanning for empty folders in '[cyan]{self.download_folder}[/cyan]'...")
        for dirpath, dirnames, filenames in os.walk(self.download_folder, topdown=False):
            if not dirnames and not filenames:
                try:
                    if dry_run:
                        logger.info(f"[yellow]Dry Run:[/] Would remove empty folder: [cyan]{dirpath}[/cyan]")
                    else:
                        os.rmdir(dirpath)
                    removed_count += 1
                except OSError as e:
                    logger.warning(f"[yellow]Warning:[/] Could not remove folder '[cyan]{dirpath}[/cyan]': {e}")

        logger.info(f"Removed [bold blue]{removed_count}[/bold blue] empty folders.")