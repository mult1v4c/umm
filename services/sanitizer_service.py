import json
import logging
import re
import shutil
from pathlib import Path
from typing import Callable, List, Dict, Optional, Tuple, Set

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeRemainingColumn

from services.file_system_manager import FileSystemManager
from services.tmdb_service import TMDbService
from services.junk_service import JunkService

logger = logging.getLogger("media_manager")


class SanitizerService:
    def __init__(
        self,
        tmdb_service: TMDbService,
        fs_manager: FileSystemManager,
        junk_service: JunkService,
        console: Console,
        is_dry_run: Callable[[], bool],
    ):
        self.tmdb_service = tmdb_service
        self.fs_manager = fs_manager
        self.junk_service = junk_service
        self.console = console
        self.is_dry_run = is_dry_run
        self.video_extensions = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv"}
        self.library_cache_path = self.fs_manager.download_folder / "library.json"

        self.junk_titles = {
            "sample", "video sample", "deleted scenes", "featurette",
            "nostalgia", "wanderlust"
        }

    def _is_normalized_filename(self, filename_stem: str) -> bool:
        """Checks if a filename matches the 'Title (Year)' format."""
        return bool(re.search(r'^.+\s\(\d{4}\)$', filename_stem))

    def _parse_filename(self, filename: str, junk_words: Set[str]) -> Optional[Tuple[str, Optional[int]]]:
        """
        Cleans and extracts a title and year using a dynamic junk list.
        """
        clean_name = Path(filename).stem
        year_match = re.search(r"\b(19\d{2}|20\d{2})\b", clean_name)
        year = None
        if year_match:
            year = int(year_match.group(0))
            clean_name = clean_name[:year_match.start()]

        clean_name = re.sub(r"[\._\[\]\(\)-]", " ", clean_name)
        clean_name = re.sub(r"[\(\[].*?[\)\]]", "", clean_name)

        tokens = clean_name.split()
        default_junk = {'4k', '1080p', '720p', 'uhd', 'bluray', 'web-dl', 'webrip', 'x264', 'x265', 'hevc'}
        all_junk = junk_words.union(default_junk)

        title_tokens = []
        for t in tokens:
            is_year_digit = t.isdigit() and len(t) == 4 and (t.startswith('19') or t.startswith('20'))

            if t.lower() not in all_junk and not is_year_digit:
                title_tokens.append(t)

        title = " ".join(title_tokens).strip()

        if not year:
            final_year_match = re.search(r"\b(19\d{2}|20\d{2})\b", filename)
            if final_year_match:
                year = int(final_year_match.group(0))

        if not title:
            return None

        if title.lower() in self.junk_titles:
            logger.info(f"Skipping junk/sample file: [yellow]{filename}[/yellow]")
            return None

        return title, year

    def _scan_for_videos(self) -> List[Path]:
        """
        Scans for videos only in the root and one level deep.
        This stops it from scanning "Featurettes" folders etc.
        """
        video_files = []
        root_path = self.fs_manager.download_folder
        logger.info(f"Scanning for videos in [cyan]{root_path}[/cyan] (max 1 folder deep)...")

        for p in root_path.glob("*"):
            if p.is_file() and p.suffix.lower() in self.video_extensions:
                if "-trailer" not in p.stem and p.name != "library.json":
                    video_files.append(p)
            elif p.is_dir():
                for child_file in p.glob("*"):
                    if child_file.is_file() and child_file.suffix.lower() in self.video_extensions:
                         if "-trailer" not in child_file.stem:
                            video_files.append(child_file)
        return video_files

    def _load_library_cache(self) -> Dict[str, Dict]:
        if self.library_cache_path.exists():
            try:
                with self.library_cache_path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                logger.warning("[yellow]Library cache is corrupt. Starting fresh.[/yellow]")
        return {}

    def _save_library_cache(self, cache: Dict):
        try:
            with self.library_cache_path.open("w", encoding="utf-8") as f:
                json.dump(cache, f, indent=4)
            logger.info(f"💾 Library cache saved to [cyan]{self.library_cache_path}[/cyan]")
        except IOError as e:
            logger.error(f"Failed to save library cache: {e}")

    def run(self):
        junk_words = self.junk_service.build_junk_cache()
        library_cache = self._load_library_cache()

        # --- MODIFICATION: Store strings, not Path objects ---
        unparseable_files = []
        unmatched_files = []
        operations = []

        video_files = self._scan_for_videos()
        if not video_files:
            logger.info("No new video files found to process.")
            return

        with Progress(console=self.console) as progress:
            task = progress.add_task("Processing files...", total=len(video_files))
            for file_path in video_files:
                # Get a clean relative path for logging
                try:
                    relative_path = file_path.relative_to(self.fs_manager.download_folder)
                except ValueError:
                    relative_path = file_path

                if str(file_path) in [e.get('file_path') for e in library_cache.values()]:
                    progress.advance(task)
                    continue

                if self._is_normalized_filename(file_path.stem) and file_path.stem == file_path.parent.name:
                    progress.advance(task)
                    continue

                parsed_data = self._parse_filename(file_path.name, junk_words)
                if not parsed_data:
                    unparseable_files.append(str(relative_path)) # Store string
                    progress.advance(task)
                    continue

                title, year = parsed_data

                movie_data = self.tmdb_service.search_movie(title, year)
                if not movie_data:
                    unmatched_files.append(str(relative_path)) # Store string
                    progress.advance(task)
                    continue

                new_folder_name = self.fs_manager.prepare_movie_folder_name(
                    movie_data["title"], movie_data["release_date"]
                )
                new_path = self.fs_manager.download_folder / new_folder_name
                new_filename = new_path / f"{new_folder_name}{file_path.suffix}"

                if file_path == new_filename:
                    progress.advance(task)
                    continue

                operations.append({
                    "source": file_path, "destination": new_filename, "movie": movie_data
                })
                progress.advance(task)

        if operations:
            self._execute_operations(operations, library_cache)
        else:
            logger.info("Library is already up-to-date.")

        # --- NEW REPORTING SECTION ---
        logger.info("\nSanitization Complete!")
        logger.info(f"  - Files processed: {len(video_files)}")
        logger.info(f"  - Successful matches: {len(operations)}")

        if unparseable_files:
            logger.warning(f"  - [yellow]Unparseable files (could not get title/year): {len(unparseable_files)}[/yellow]")
            for f in unparseable_files:
                logger.warning(f"    - {f}")

        if unmatched_files:
            logger.warning(f"  - [yellow]Unmatched files (no TMDB result): {len(unmatched_files)}[/yellow]")
            for f in unmatched_files:
                logger.warning(f"    - {f}")
        # --- END OF NEW SECTION ---

    def _execute_operations(self, operations: List[Dict], cache: Dict):
        if self.is_dry_run():
            logger.info("[bold yellow]DRY RUN MODE: The following changes are planned:[/bold yellow]")
            for op in operations:
                logger.info(f"  [cyan]MOVE:[/] '{op['source']}' -> '{op['destination']}'")

            if self.console.input("\n[bold]Proceed with changes? (y/n): [/bold]").lower() == 'y':
                self._run_file_operations(operations, cache)
            else:
                logger.info("Aborted by user.")
        else:
            self._run_file_operations(operations, cache)

    def _run_file_operations(self, operations: List[Dict], cache: Dict):
        logger.info("Executing file operations...")
        with Progress(console=self.console) as progress:
            task = progress.add_task("Applying changes...", total=len(operations))
            for op in operations:
                dest_path = op["destination"]
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.move(op["source"], dest_path)
                    movie_id = str(op['movie']['id'])
                    cache[movie_id] = {
                        "title": op['movie']['title'],
                        "year": op['movie']['release_date'][:4],
                        "file_path": str(dest_path)
                    }
                    logger.info(f"  [green]MOVED:[/] '{op['source'].name}' -> '{dest_path}'")
                except Exception as e:
                    logger.error(f"  [red]FAILED to move {op['source'].name}: {e}[/red]")
                progress.advance(task)

        self._save_library_cache(cache)