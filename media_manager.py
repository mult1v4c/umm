import csv
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Any, List, Callable, Set, Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn
from rich.table import Table

from config import KNOWN_FAILURES_FILENAME, TRAILER_SUFFIX, load_config, save_config
from services.tmdb_service import TMDbService
from services.downloader_service import DownloaderService
from services.asset_generator_service import AssetGeneratorService
from services.file_system_manager import FileSystemManager, MoviePaths
from services.sanitizer_service import SanitizerService
from services.junk_service import JunkService

logger = logging.getLogger("media_manager")


class MediaManager:
    def __init__(self, config: Dict, console: Console, is_dry_run: Callable[[], bool]):
        self.cfg = config
        self.console = console
        self.is_dry_run = is_dry_run
        self.failures = 0
        self.failure_lock = threading.Lock()
        self.stats = {"downloads": [], "placeholders": 0, "backdrops": 0}
        self.known_failures: set[int] = set()
        self.library_path = Path(config["MOVIE_LIBRARY"]).expanduser()
        self.download_path = Path(config["DOWNLOAD_FOLDER"]).expanduser()
        self.library_cache_path = self.library_path / "library.json" # library.json lives IN the movie library
        self.video_extensions: Set[str] = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv"}

        # --- Cache Paths ---
        self.cache_folder = Path(self.cfg["CACHE_FOLDER"]).expanduser()
        self.junk_cache_path = self.cache_folder / "junk_cache.json"
        self.tmdb_cache_path = self.cache_folder / "movies_cache.json"
        self.failures_cache_path = self._get_failures_cache_path()


        # --- Services ---
        self.tmdb_service = TMDbService(
            api_key=config["TMDB_API_KEY"],
            cache_folder=config["CACHE_FOLDER"],
            pages_per_year=config["PAGES_PER_YEAR"],
            tmdb_filters=config["TMDB_FILTERS"],
        )
        self.downloader_service = DownloaderService(
            yt_dlp_path=config["YT_DLP_PATH"]
        )
        self.asset_generator_service = AssetGeneratorService(
            ffmpeg_path=config["FFMPEG_PATH"]
        )

        # --- TWO FILE SYSTEM MANAGERS ---
        # One for the permanent, organized movie library
        self.library_fs_manager = FileSystemManager(
            download_folder=config["MOVIE_LIBRARY"]
        )
        # One for the "inbox" where new upcoming trailers are downloaded
        self.download_fs_manager = FileSystemManager(
            download_folder=config["DOWNLOAD_FOLDER"]
        )

        # --- INITIALIZE SERVICES WITH CORRECT PATHS ---
        self.junk_service = JunkService(
            cache_folder=config["CACHE_FOLDER"],
            video_extensions=self.video_extensions,
            library_folder=self.library_path # Pass the library path
        )
        self.sanitizer_service = SanitizerService(
            tmdb_service=self.tmdb_service,
            fs_manager=self.library_fs_manager, # Sanitizer ONLY works on the library
            junk_service=self.junk_service,
            console=self.console,
            is_dry_run=self.is_dry_run
        )

    # --- Main Menu Options ---

    def sanitize_and_catalog_library(self):
        logger.info("Starting Library Scan & Cataloging...")
        # This service is already correctly pointed at the MOVIE_LIBRARY
        self.sanitizer_service.run()

    def fetch_trailers_for_existing_movies(self):
        logger.info("Fetching trailers for existing movies in the library...")
        library = self._load_library_cache()
        if library is None:
            return

        movies_to_download = []
        for movie_id, data in library.items():
            movie_path = Path(data['file_path'])
            # Use the library_fs_manager to check for trailers
            paths = self.library_fs_manager.get_movie_paths(movie_path.parent.name)

            if not paths.get_trailer_path():
                movies_to_download.append({
                    "id": int(movie_id),
                    "title": data['title'],
                    "release_date": f"{data['year']}-01-01"
                })

        if not movies_to_download:
            logger.info("[green]Your library is fully up-to-date with trailers![/green]")
            return

        logger.info(f"Found [bold blue]{len(movies_to_download)}[/bold blue] movies missing trailers.")
        self._load_known_failures()
        # Process these downloads using the LIBRARY file system manager
        self._process_movies_pipeline(movies_to_download, self.library_fs_manager)
        self._save_known_failures()


    def fetch_upcoming_movie_trailers(self):
        logger.info("Starting to fetch upcoming movie trailers...")
        year_start = self.cfg["START_YEAR"]
        year_end = self.cfg["END_YEAR"]

        self._load_known_failures()
        movies = self.tmdb_service.fetch_movies(
            year_start=year_start,
            year_end=year_end,
            no_cache=False,
            clear_cache=False,
        )
        if not movies:
            logger.warning("No upcoming movies found from TMDB. Exiting.")
            return

        # Filter movies based on what's already in the DOWNLOAD folder
        movies_to_process = self._filter_existing_movies(
            movies, year_start, year_end, self.download_fs_manager
        )

        if self.is_dry_run():
            logger.info("[bold yellow]DRY RUN MODE: No files will be written![/]\nTrailers below ready for download:")

        # Process these downloads using the DOWNLOAD file system manager
        self._process_movies_pipeline(movies_to_process, self.download_fs_manager)
        self._save_known_failures()

    def sync_trailers_with_library(self):
        logger.info("Syncing library cache with file system...")
        library = self._load_library_cache()
        if library is None:
            return
        if not library:
            logger.info("Library is empty. Nothing to sync.")
            return

        cache_deletions = []
        trailer_deletions = []

        logger.info("Checking for missing movie files...")
        for movie_id, data in library.items():
            movie_path = Path(data.get('file_path', ''))
            if not movie_path.exists():
                logger.warning(f"  [yellow]Missing file for '{data['title']}'. Marking cache entry for removal.[/yellow]")
                cache_deletions.append(movie_id)

        logger.info("Checking for orphaned trailer files...")
        # Scan ONLY the movie library for trailers
        all_trailers = list(self.library_fs_manager.download_folder.rglob(f"*{TRAILER_SUFFIX}.mp4"))
        valid_movie_dirs = {Path(data['file_path']).parent for data in library.values() if 'file_path' in data}

        for trailer_path in all_trailers:
            if trailer_path.parent not in valid_movie_dirs:
                logger.warning(f"  [yellow]Found orphaned trailer: '{trailer_path.name}'. Marking for deletion.[/yellow]")
                trailer_deletions.append(trailer_path)

        if not cache_deletions and not trailer_deletions:
            logger.info("[green]Library is already perfectly in sync![/green]")
            return

        self._execute_sync_operations(cache_deletions, trailer_deletions, library)

    def show_library_status(self):
        library = self._load_library_cache()
        if library is None:
            return
        if not library:
            logger.info("Your library is empty.")
            return

        table = Table(title="Library Status")
        table.add_column("Total Movies", justify="right", style="cyan", no_wrap=True)
        table.add_column("Movies Missing Trailers", justify="right", style="magenta", no_wrap=True)

        missing_trailers = 0
        for movie_id, data in library.items():
            movie_path = Path(data['file_path'])
            # Use the library_fs_manager to check paths
            paths = self.library_fs_manager.get_movie_paths(movie_path.parent.name)
            if not paths.get_trailer_path():
                missing_trailers += 1

        table.add_row(str(len(library)), str(missing_trailers))
        self.console.print(table)


    def show_settings_and_utilities(self):
        # Displays the settings and utilities sub-menu
        while True:
            self._print_settings_menu()
            choice = self.console.input("Choose an option: ").strip().lower()

            if choice == "1":
                self._edit_paths_setting()
            elif choice == "2":
                self._edit_api_key()
            elif choice == "3":
                self._edit_performance_settings()
            elif choice == "c":
                self._clear_caches()
            elif choice == "0":
                break
            else:
                self.console.print("[bold red]Invalid option, please try again.[/bold red]")
                time.sleep(1)

    # --- Settings Sub-Menu Helpers ---

    def _print_settings_menu(self):
        self.console.clear()
        self.console.print("[bold cyan]Settings & Utilities[/bold cyan]")
        self.console.print("-----------------------------------", justify="center")
        self.console.print("[bold green][1][/] Edit File Paths")
        self.console.print("[bold green][2][/] Edit TMDB API Key")
        self.console.print("[bold green][3][/] Edit Performance")
        self.console.print("[bold yellow][C][/] Clear Caches")
        self.console.print("[bold red][0][/] Back to Main Menu")
        self.console.print("-----------------------------------", justify="center")

    def _edit_api_key(self):
        config = load_config()
        current_key = config.get("TMDB_API_KEY", "NOT SET")
        self.console.print(f"Current TMDB API Key: [cyan]{current_key}[/cyan]")
        new_key = self.console.input("Enter new TMDB API Key (or press Enter to cancel): ").strip()
        if new_key:
            config["TMDB_API_KEY"] = new_key
            save_config(config)
            self.tmdb_service.api_key = new_key # Update live service
            self.console.print("[green]API Key updated.[/green]")
        time.sleep(1)

    def _edit_paths_setting(self):
        config = load_config()
        # --- UPDATED TO INCLUDE MOVIE_LIBRARY ---
        current_library_path = config.get("MOVIE_LIBRARY")
        current_download_path = config.get("DOWNLOAD_FOLDER")
        current_cache_path = config.get("CACHE_FOLDER")

        self.console.print(f"Current Movie Library Path: [cyan]{current_library_path}[/cyan]")
        new_library_path = self.console.input("Enter new Movie Library Path (or press Enter to keep): ").strip()

        self.console.print(f"Current New Trailer Download Path: [cyan]{current_download_path}[/cyan]")
        new_download_path = self.console.input("Enter new Download Path (or press Enter to keep): ").strip()

        self.console.print(f"Current Cache Path: [cyan]{current_cache_path}[/cyan]")
        new_cache_path = self.console.input("Enter new Cache Path (or press Enter to keep): ").strip()

        if new_library_path:
            config["MOVIE_LIBRARY"] = new_library_path
        if new_download_path:
            config["DOWNLOAD_FOLDER"] = new_download_path
        if new_cache_path:
            config["CACHE_FOLDER"] = new_cache_path

        if new_library_path or new_download_path or new_cache_path:
            save_config(config)
            self.console.print("[green]Paths updated. Restart UMM for all changes to take effect.[/green]")
        time.sleep(2)

    def _edit_performance_settings(self):
        config = load_config()
        current_dl = config.get("MAX_DOWNLOAD_WORKERS")
        current_ff = config.get("MAX_FFMPEG_WORKERS")

        self.console.print(f"Current Download Workers: [cyan]{current_dl}[/cyan]")
        new_dl = self.console.input("Enter new Download Workers (or press Enter to keep): ").strip()

        self.console.print(f"Current FFmpeg Workers: [cyan]{current_ff}[/cyan]")
        new_ff = self.console.input("Enter new FFmpeg Workers (or press Enter to keep): ").strip()

        try:
            if new_dl:
                config["MAX_DOWNLOAD_WORKERS"] = int(new_dl)
            if new_ff:
                config["MAX_FFMPEG_WORKERS"] = int(new_ff)

            if new_dl or new_ff:
                save_config(config)
                self.console.print("[green]Performance settings updated.[/green]")
        except ValueError:
            self.console.print("[red]Invalid input. Workers must be a number.[/red]")
        time.sleep(1)


    def _clear_caches(self):
        while True:
            self.console.clear()
            self.console.print("[bold yellow]Clear Caches[/bold yellow]")
            self.console.print("-----------------------------------", justify="center")
            self.console.print(f"[1] Clear Upcoming Movie Cache ([cyan]{self.tmdb_cache_path.name}[/cyan])")
            self.console.print(f"[2] Clear Junk Word Cache ([cyan]{self.junk_cache_path.name}[/cyan])")
            self.console.print(f"[3] Clear Known Failures Cache ([cyan]{self.failures_cache_path.name}[/cyan])")
            self.console.print(f"[bold red][4] Clear Movie Library Cache ([/bold red][cyan]{self.library_cache_path.name}[/cyan][bold red])[/bold red]")
            self.console.print("-----------------------------------", justify="center")
            self.console.print("[bold red][A] CLEAR ALL CACHES[/bold red]")
            self.console.print("[0] Back to Settings")
            choice = self.console.input("Choose an option: ").strip().lower()

            if choice == "1":
                self._safe_delete_cache(self.tmdb_cache_path, "Upcoming Movie Cache")
            elif choice == "2":
                self._safe_delete_cache(self.junk_cache_path, "Junk Word Cache")
            elif choice == "3":
                self._safe_delete_cache(self.failures_cache_path, "Known Failures Cache")
            elif choice == "4":
                self.console.print(f"[bold red]WARNING: This will delete your main {self.library_cache_path.name}.[/bold red]")
                self.console.print("You will need to re-run the Sanitizer to rebuild it.")
                if self.console.input("Are you sure? (y/n): ").lower() == 'y':
                    self._safe_delete_cache(self.library_cache_path, "Movie Library Cache")
            elif choice == "a":
                self.console.print("[bold red]WARNING: This will clear ALL cache files.[/bold red]")
                if self.console.input("Are you sure? (y/n): ").lower() == 'y':
                    self._safe_delete_cache(self.tmdb_cache_path, "Upcoming Movie Cache")
                    self._safe_delete_cache(self.junk_cache_path, "Junk Word Cache")
                    self._safe_delete_cache(self.failures_cache_path, "Known Failures Cache")
                    self._safe_delete_cache(self.library_cache_path, "Movie Library Cache", warn=False)
            elif choice == "0":
                break
            time.sleep(1)

    def _safe_delete_cache(self, file_path: Path, file_name: str, warn: bool = True):
        if not file_path.exists():
            self.console.print(f"[yellow]{file_name} not found. Already clear.[/yellow]")
            return
        try:
            file_path.unlink()
            self.console.print(f"[green]{file_name} has been cleared.[/green]")
        except OSError as e:
            self.console.print(f"[red]Failed to delete {file_name}: {e}[/red]")


    # --- Library Cache Helpers ---

    def _load_library_cache(self) -> Optional[Dict[str, Dict]]:
        if not self.library_cache_path.exists():
            logger.warning("[yellow]Library cache ('library.json') not found. Run the sanitizer [1] first.[/yellow]")
            return None
        try:
            with self.library_cache_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.error("[red]Could not parse library.json. It may be corrupt.[/red]")
            return None

    def _save_library_cache(self, cache: Dict):
        try:
            with self.library_cache_path.open("w", encoding="utf-8") as f:
                json.dump(cache, f, indent=4)
            logger.info(f"💾 Library cache saved to [cyan]{self.library_cache_path}[/cyan]")
        except IOError as e:
            logger.error(f"Failed to save library cache: {e}")

    # --- Sync Helpers ---

    def _execute_sync_operations(self, cache_deletions, trailer_deletions, library):
        if self.is_dry_run():
            logger.info("[bold yellow]DRY RUN MODE: The following sync operations are planned:[/bold yellow]")
            for movie_id in cache_deletions:
                title = library.get(movie_id, {}).get('title', 'Unknown')
                logger.info(f"  [cyan]REMOVE CACHE:[/] Entry for '{title}' (ID: {movie_id})")
            for trailer_path in trailer_deletions:
                logger.info(f"  [red]DELETE FILE:[/] Orphaned trailer '{trailer_path}'")

            if self.console.input("\n[bold]Proceed with changes? (y/n): [/bold]").lower() == 'y':
                logger.info("Executing sync operations...")
                self._run_sync_operations(cache_deletions, trailer_deletions, library)
            else:
                logger.info("Sync aborted by user.")
        else:
            self._run_sync_operations(cache_deletions, trailer_deletions, library)

    def _run_sync_operations(self, cache_deletions, trailer_deletions, library):
        for trailer_path in trailer_deletions:
            try:
                trailer_path.unlink()
                logger.info(f"  [green]DELETED:[/] '{trailer_path}'")
            except OSError as e:
                logger.error(f"  [red]FAILED to delete '{trailer_path}': {e}[/red]")

        if cache_deletions:
            cleaned_library = {mid: data for mid, data in library.items() if mid not in cache_deletions}
            self._save_library_cache(cleaned_library)
            logger.info(f"  [green]CLEANED:[/] Removed {len(cache_deletions)} invalid entries from library.json.")

    # --- Other Helpers ---

    def _increment_failures(self):
        with self.failure_lock:
            self.failures += 1
            if self.failures >= 5:
                raise RuntimeError(
                    "Too many download failures. Check network or YouTube availability."
                )

    def _get_failures_cache_path(self) -> Path:
        cache_folder = Path(self.cfg["CACHE_FOLDER"]).expanduser()
        cache_folder.mkdir(parents=True, exist_ok=True)
        return cache_folder / KNOWN_FAILURES_FILENAME

    def _load_known_failures(self):
        cache_path = self.failures_cache_path
        if cache_path.exists():
            try:
                with cache_path.open("r", encoding="utf-8") as f:
                    self.known_failures = set(json.load(f))
                logger.info(
                    f"Loaded [bold yellow]{len(self.known_failures)}[/bold yellow] known failing movie IDs."
                )
            except (json.JSONDecodeError, IOError):
                logger.warning(
                    "[yellow]Warning:[/] Known failures cache file is corrupt or unreadable."
                )

    def _save_known_failures(self):
        if not self.known_failures:
            return
        cache_path = self.failures_cache_path
        try:
            with cache_path.open("w", encoding="utf-8") as f:
                json.dump(list(self.known_failures), f, indent=2)
            logger.info(
                f"🟡 [yellow]Updated known failures cache with {len(self.known_failures)} movie IDs.[/yellow]"
            )
        except IOError as e:
            logger.error(f"Failed to write known failures cache: {e}")

    # --- UPDATED HELPER: Takes an fs_manager ---
    def _filter_existing_movies(
        self, movies: List[Dict], year_start: int, year_end: int, fs_manager: FileSystemManager
    ) -> List[Dict]:
        year_str = (
            str(year_start) if year_start == year_end else f"{year_start}-{year_end}"
        )
        total_count = len(movies)
        movies_to_download = []
        for movie in movies:
            title = movie.get("title", "Unknown Title")
            release_date = movie.get("release_date", "")

            folder_name = fs_manager.prepare_movie_folder_name(title, release_date)
            paths = fs_manager.get_movie_paths(folder_name)
            if not paths.get_trailer_path():
                movies_to_download.append(movie)

        skipped_count = total_count - len(movies_to_download)
        log_message = f"Found {total_count} movies for {year_str}."
        if skipped_count > 0:
            log_message += (
                f" Skipping [bold green]{skipped_count}[/bold green] existing trailers."
            )
        logger.info(log_message)
        return movies_to_download

    # --- UPDATED HELPER: Takes an fs_manager ---
    def _process_movies_pipeline(self, movies: list, fs_manager: FileSystemManager):
        if not movies:
            logger.info("No new movies to process.")
            return

        download_workers = self.cfg.get("MAX_DOWNLOAD_WORKERS", 4)
        ffmpeg_workers = self.cfg.get("MAX_FFMPEG_WORKERS", 4)
        if not self.is_dry_run():
            logger.info(
                f"Processing movies in parallel (Downloads: {download_workers}, Video Tasks: {ffmpeg_workers})"
            )

        with ThreadPoolExecutor(
            max_workers=download_workers, thread_name_prefix="Download"
        ) as dl_pool, ThreadPoolExecutor(
            max_workers=ffmpeg_workers, thread_name_prefix="FFmpeg"
        ) as ff_pool, Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=None),
            "[progress.percentage]{task.percentage:>3.0f}%",
            TimeRemainingColumn(),
            transient=True,
            console=self.console,
        ) as progress:
            task_id = progress.add_task("Downloading trailers", total=len(movies))
            download_futures = {
                # Pass the fs_manager to the download task
                dl_pool.submit(self._download_task, movie, ff_pool, fs_manager): movie
                for movie in movies
            }

            for future in as_completed(download_futures):
                try:
                    result = future.result()
                    if result:
                        self.stats["downloads"].append(result)
                except RuntimeError as e:
                    logger.info(f"⛔ [bold red]CRITICAL:[/] {e}")
                    for f in download_futures:
                        f.cancel()
                    break
                except Exception as e:
                    movie = download_futures[future]
                    logger.info(f"[bold red]Error processing '{movie.get('title')}':[/] {e}")
                finally:
                    progress.advance(task_id)

            ff_pool.shutdown(wait=True)

    # --- UPDATED HELPER: Takes an fs_manager ---
    def _download_task(self, movie: Dict, ffmpeg_pool: ThreadPoolExecutor, fs_manager: FileSystemManager) -> Dict:
        movie_id = movie.get("id", 0)
        title = movie.get("title", "Unknown Title")
        release_date = movie.get("release_date", "")
        result = {"folder": title, "downloaded": False, "reason": ""}

        if movie_id in self.known_failures:
            result["reason"] = "known failure"
            return result

        # Use the provided fs_manager
        folder_name = fs_manager.prepare_movie_folder_name(title, release_date)
        paths = fs_manager.get_movie_paths(folder_name)
        result["folder"] = folder_name

        if self.is_dry_run():
            logger.info(f"- [cyan]{title}[/cyan] -> {paths.root.relative_to(Path.cwd())}")
            result["reason"] = "dry-run"
            return result

        trailer_key = self.tmdb_service.get_trailer_key(movie_id)
        if not trailer_key:
            self.known_failures.add(movie_id)
            result["reason"] = "no trailer key found"
            return result

        paths.root.mkdir(parents=True, exist_ok=True)
        out_template = str(paths.root / f"{folder_name}{TRAILER_SUFFIX}.%(ext)s")
        download_ok = self.downloader_service.download_trailer(
            youtube_key=trailer_key,
            out_template=out_template,
            title=title,
            failure_callback=self._increment_failures,
        )

        if not download_ok:
            self.known_failures.add(movie_id)
            result["reason"] = "download failed"
            return result

        result["downloaded"] = True
        ffmpeg_pool.submit(self._ffmpeg_task, "placeholder", paths, title)
        if self.cfg["CREATE_BACKDROP"]:
            ffmpeg_pool.submit(self._ffmpeg_task, "backdrop", paths, title)
        return result

    def _ffmpeg_task(self, task_type: str, paths: MoviePaths, title: str):
        if self.is_dry_run():
            logger.info(
                f"[yellow]Dry Run:[/] Would create {task_type} for '[cyan]{title}[/cyan]'"
            )
            return

        if task_type == "placeholder":
            ok = self.asset_generator_service.create_black_video(
                paths.placeholder,
                duration=self.cfg["PLACEHOLDER_DURATION"],
                resolution=self.cfg["PLACEHOLDER_RESOLUTION"],
                overwrite=True,
            )
            if ok:
                logger.info(f"   Created placeholder for {title}")
                self.stats["placeholders"] += 1
        elif task_type == "backdrop":
            ok = self.asset_generator_service.create_backdrop_image(
                paths.backdrop,
                resolution=self.cfg["PLACEHOLDER_RESOLUTION"],
                overwrite=True,
            )
            if ok:
                logger.info(f"   Created backdrop for {title}")
                self.stats["backdrops"] += 1