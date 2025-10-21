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
        # Checks if a filename matches the 'Title (Year)' format.
        return bool(re.search(r'^.+\s\(\d{4}\)$', filename_stem))

    def _parse_normalized_filename(self, filename_stem: str) -> Optional[Tuple[str, int]]:
        # Extracts title and year from a *clean* 'Title (Year)' string.
        match = re.search(r'^(.*?)\s\((\d{4})\)$', filename_stem)
        if match:
            title = match.group(1)
            year = int(match.group(2))
            return title, year
        return None

    def _parse_filename(self, filename: str, junk_words: Set[str]) -> Optional[Tuple[str, Optional[int]]]:
        # Cleans and extracts a title and year from a *messy* filename.
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
        # Recursively scans the entire movie directory for video files.
        root_path = self.fs_manager.download_folder
        logger.info(f"Recursively scanning for videos in [cyan]{root_path}[/cyan]...")

        video_files = [
            p for p in root_path.rglob("*")
            if p.is_file() and p.suffix.lower() in self.video_extensions
            and "-trailer" not in p.stem and p.name != "library.json"
        ]
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

        unparseable_files = []
        unmatched_files = []
        operations = []
        cache_updated_with_clean_files = False
        collection_files_found = []

        video_files = self._scan_for_videos()
        if not video_files:
            logger.info("No new video files found to process.")
            return

        with Progress(console=self.console) as progress:
            task = progress.add_task("Processing files...", total=len(video_files))
            for file_path in video_files:
                try:
                    relative_path = file_path.relative_to(self.fs_manager.download_folder)
                except ValueError:
                    relative_path = file_path

                # Collection detection logic
                depth = len(relative_path.parts)
                if depth > 2:
                    collection_files_found.append(str(relative_path))
                    progress.advance(task)
                    continue

                if str(file_path) in [e.get('file_path') for e in library_cache.values()]:
                    progress.advance(task)
                    continue

                # Check if file is *already* perfectly named AND in the right folder
                if self._is_normalized_filename(file_path.stem) and file_path.stem == file_path.parent.name:
                    parsed_data = self._parse_normalized_filename(file_path.stem)
                    if parsed_data:
                        title, year = parsed_data
                        movie_data = self.tmdb_service.search_movie(title, year)
                        if movie_data:
                            movie_id = str(movie_data['id'])
                            library_cache[movie_id] = {
                                "title": movie_data['title'],
                                "year": movie_data['release_date'][:4],
                                "file_path": str(file_path)
                            }
                            cache_updated_with_clean_files = True
                        else:
                            unmatched_files.append(str(relative_path))
                    else:
                        unparseable_files.append(str(relative_path))

                    progress.advance(task)
                    continue

                # File is messy, in the wrong folder, or a junk file.
                parsed_data = self._parse_filename(file_path.name, junk_words)
                if not parsed_data:
                    unparseable_files.append(str(relative_path))
                    progress.advance(task)
                    continue

                title, year = parsed_data
                movie_data = self.tmdb_service.search_movie(title, year)
                if not movie_data:
                    unmatched_files.append(str(relative_path))
                    progress.advance(task)
                    continue

                new_folder_name = self.fs_manager.prepare_movie_folder_name(
                    movie_data["title"], movie_data["release_date"]
                )
                new_file_name = f"{new_folder_name}{file_path.suffix}"

                source_folder = file_path.parent
                dest_folder = self.fs_manager.download_folder / new_folder_name
                dest_file = dest_folder / new_file_name

                if file_path == dest_file:
                    progress.advance(task)
                    continue

                # --- THIS IS THE FIX ---
                op_type = ""
                if source_folder == self.fs_manager.download_folder:
                    # File is in the root, needs to be moved into a folder
                    op_type = "move_file"
                elif source_folder == dest_folder:
                    # File is in the correct folder, but file itself needs renaming
                    op_type = "rename_file_in_place"
                else:
                    # File is in the wrong folder, and folder needs renaming
                    op_type = "rename_folder"
                # --- END OF FIX ---

                operations.append({
                    "op_type": op_type,
                    "source_file": file_path,
                    "source_folder": source_folder,
                    "dest_folder": dest_folder,
                    "dest_file": dest_file,
                    "movie_data": movie_data
                })
                progress.advance(task)

        if operations:
            self._execute_operations(operations, library_cache)
        elif cache_updated_with_clean_files:
            logger.info("No files to move. Updating library cache with clean files...")
            self._save_library_cache(library_cache)
        else:
            logger.info("Library is already up-to-date.")

        logger.info("\nSanitization Complete!")
        logger.info(f"  - Files processed: {len(video_files)}")
        logger.info(f"  - Successful moves/renames: {len(operations)}")

        if unparseable_files:
            logger.warning(f"  - [yellow]Unparseable files (could not get title/year): {len(unparseable_files)}[/yellow]")
            for f in unparseable_files:
                logger.warning(f"    - {f}")

        if unmatched_files:
            logger.warning(f"  - [yellow]Unmatched files (no TMDB result): {len(unmatched_files)}[/yellow]")
            for f in unmatched_files:
                logger.warning(f"    - {f}")

        if collection_files_found:
            logger.warning(f"  - [cyan]Skipped collection files (2+ folders deep): {len(collection_files_found)}[/cyan]")
            logger.warning("    (These files are in collection folders and should be organized manually)")
            for f in collection_files_found:
                logger.warning(f"    - {f}")

    def _execute_operations(self, operations: List[Dict], cache: Dict):
        if self.is_dry_run():
            logger.info("[bold yellow]DRY RUN MODE: The following changes are planned:[/bold yellow]")
            for op in operations:
                if op["op_type"] == "move_file":
                    logger.info(f"  [cyan]MOVE FILE:[/]   '{op['source_file']}' -> '{op['dest_file']}'")
                elif op["op_type"] == "rename_folder":
                    logger.info(f"  [green]RENAME FOLDER:[/] '{op['source_folder']}' -> '{op['dest_folder']}'")
                    logger.info(f"  [green]RENAME FILE:[/]   '{op['source_file'].name}' -> '{op['dest_file'].name}'")
                elif op["op_type"] == "rename_file_in_place":
                    logger.info(f"  [blue]RENAME FILE IN PLACE:[/] '{op['source_file']}' -> '{op['dest_file']}'")

            prompt_text = "\n[bold]Proceed with changes? (y/n): [/bold]"
            width = self.console.width
            padding = (width - len(prompt_text.strip().replace("[bold]", "").replace("[/bold]", ""))) // 2

            if self.console.input(" " * padding + prompt_text).strip().lower() == 'y':
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
                movie_id = str(op['movie_data']['id'])

                try:
                    # --- THIS IS THE FIX ---
                    if op["op_type"] == "move_file":
                        # This is a file from the root
                        op["dest_folder"].mkdir(parents=True, exist_ok=True)
                        shutil.move(op["source_file"], op["dest_file"])
                        logger.info(f"  [green]MOVED:[/] '{op['source_file'].name}' -> '{op['dest_file']}'")

                    elif op["op_type"] == "rename_folder":
                        # This is a file in a subfolder that needs a folder rename
                        if op["dest_folder"].exists():
                            logger.warning(f"  [yellow]SKIPPED:[/] Target folder '{op['dest_folder']}' already exists. Cannot rename.")
                            progress.advance(task)
                            continue

                        shutil.move(op["source_folder"], op["dest_folder"])
                        logger.info(f"  [green]RENAMED FOLDER:[/] '{op['source_folder'].name}' -> '{op['dest_folder'].name}'")

                        old_file_in_new_home = op["dest_folder"] / op["source_file"].name
                        new_file_in_new_home = op["dest_file"]

                        if old_file_in_new_home != new_file_in_new_home:
                            old_file_in_new_home.rename(new_file_in_new_home)
                            logger.info(f"  [green]RENAMED FILE:[/]   '{old_file_in_new_home.name}' -> '{new_file_in_new_home.name}'")

                    elif op["op_type"] == "rename_file_in_place":
                        # This is a file in a correct folder that just needs a file rename
                        shutil.move(op["source_file"], op["dest_file"])
                        logger.info(f"  [blue]RENAMED FILE:[/] '{op['source_file'].name}' -> '{op['dest_file'].name}'")
                    # --- END OF FIX ---

                    # Add to cache on success
                    cache[movie_id] = {
                        "title": op['movie_data']['title'],
                        "year": op['movie_data']['release_date'][:4],
                        "file_path": str(op['dest_file'])
                    }
                except Exception as e:
                    logger.error(f"  [red]FAILED to process {op['source_file'].name}: {e}[/red]")

                progress.advance(task)

        self._save_library_cache(cache)