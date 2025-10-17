import argparse
import csv
import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Any, List

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn

from config import KNOWN_FAILURES_FILENAME, TRAILER_SUFFIX
from services.tmdb_service import TMDbService
from services.downloader_service import DownloaderService
from services.asset_generator_service import AssetGeneratorService
from services.file_system_manager import FileSystemManager, MoviePaths

logger = logging.getLogger("media_manager")

class MediaManager:

    def __init__(self, config: Dict, args: argparse.Namespace, console: Console):
        self.cfg = config
        self.args = args
        self.console = console
        self.failures = 0
        self.failure_lock = threading.Lock()
        self.stats = {"downloads": [], "placeholders": 0, "backdrops": 0}
        self.known_failures: set[int] = set()

        self.tmdb_service = TMDbService(
            api_key=config["TMDB_API_KEY"],
            cache_folder=config["CACHE_FOLDER"],
            pages_per_year=config["PAGES_PER_YEAR"],
            tmdb_filters=config["TMDB_FILTERS"]
        )
        self.downloader_service = DownloaderService(
            yt_dlp_path=args.yt_dlp or config["YT_DLP_PATH"]
        )
        self.asset_generator_service = AssetGeneratorService(
            ffmpeg_path=args.ffmpeg or config["FFMPEG_PATH"]
        )
        self.fs_manager = FileSystemManager(
            download_folder=config["DOWNLOAD_FOLDER"]
        )

    def _increment_failures(self):
        with self.failure_lock:
            self.failures += 1
            if self.failures >= 5 and not self.args.ignore_failures:
                raise RuntimeError("Too many download failures. Check network or YouTube availability.")

    def _get_failures_cache_path(self) -> Path:
        cache_folder = Path(self.cfg["CACHE_FOLDER"]).expanduser()
        cache_folder.mkdir(parents=True, exist_ok=True)
        return cache_folder / KNOWN_FAILURES_FILENAME

    def _load_known_failures(self):
        cache_path = self._get_failures_cache_path()
        if cache_path.exists():
            try:
                with cache_path.open("r", encoding="utf-8") as f:
                    self.known_failures = set(json.load(f))
                logger.info(f"Loaded [bold yellow]{len(self.known_failures)}[/bold yellow] known failing movie IDs.")
            except (json.JSONDecodeError, IOError):
                logger.warning("[yellow]Warning:[/] Known failures cache file is corrupt or unreadable.")

    def _save_known_failures(self):
        if not self.known_failures:
            return
        cache_path = self._get_failures_cache_path()
        try:
            with cache_path.open("w", encoding="utf-8") as f:
                json.dump(list(self.known_failures), f, indent=2)
            logger.info(f"🟡 [yellow]Updated known failures cache with {len(self.known_failures)} movie IDs.[/yellow]")
        except IOError as e:
            logger.error(f"Failed to write known failures cache: {e}")

    def run(self):
        logger.info("Starting media manager...")
        year_start = self.args.year or self.args.year_start or self.cfg["START_YEAR"]
        year_end = self.args.year or self.args.year_end or self.cfg["END_YEAR"]

        self._load_known_failures()

        movies = self.tmdb_service.fetch_movies(
            year_start=year_start,
            year_end=year_end,
            no_cache=self.args.no_cache,
            clear_cache=self.args.clear_cache
        )
        if not movies:
            logger.warning("No movies found from TMDB. Exiting.")
            return

        movies_to_process = self._filter_existing_movies(movies, year_start, year_end)

        if self.args.count and self.args.count > 0:
            original_needed_count = len(movies_to_process)
            movies_to_process = movies_to_process[:self.args.count]
            logger.info(f"Limiting to {len(movies_to_process)} of {original_needed_count} needed downloads based on --count.")

        if self.args.export_list:
            self._export_movie_list(movies, self.args.export_list)

        if self.args.dry_run:
            logger.info("[bold yellow]DRY RUN MODE: No files will be written![/]\nTrailers below ready for download:")

        if not any([self.args.download, self.args.placeholders, self.args.backdrops]):
            self.args.all = True

        if self.args.all or self.args.download:
            self._process_movies_pipeline(movies_to_process)
            self._save_known_failures()

        if self.args.placeholders or self.args.backdrops:
            self._generate_standalone_assets()

        if self.args.clean_empty:
            self.fs_manager.clean_empty_folders(self.args.dry_run)

        if self.args.report:
            self._write_report()

    def _filter_existing_movies(self, movies: List[Dict], year_start: int, year_end: int) -> List[Dict]:
        year_str = str(year_start) if year_start == year_end else f"{year_start}-{year_end}"
        total_count = len(movies)

        if self.args.force:
            logger.info(f"Found {total_count} movies for {year_str}. [yellow]--force is enabled, processing all.[/yellow]")
            return movies

        movies_to_download = []
        for movie in movies:
            title = movie.get("title", "Unknown Title")
            release_date = movie.get("release_date", "")

            folder_name = self.fs_manager.prepare_movie_folder_name(title, release_date)
            paths = self.fs_manager.get_movie_paths(folder_name)

            if not paths.get_trailer_path():
                movies_to_download.append(movie)

        skipped_count = total_count - len(movies_to_download)
        log_message = f"Found {total_count} movies for {year_str}."
        if skipped_count > 0:
            log_message += f" Skipping [bold green]{skipped_count}[/bold green] existing trailers."
        logger.info(log_message)
        return movies_to_download

    def _process_movies_pipeline(self, movies: list):
        if not movies:
            logger.info("No new movies to process.")
            return

        download_workers = self.args.max_download_workers or self.cfg.get("MAX_DOWNLOAD_WORKERS", 4)
        ffmpeg_workers = self.args.max_ffmpeg_workers or self.cfg.get("MAX_FFMPEG_WORKERS", 4)

        if not self.args.dry_run:
            logger.info(f"Processing movies in parallel (Downloads: {download_workers}, Video Tasks: {ffmpeg_workers})")

        with ThreadPoolExecutor(max_workers=download_workers, thread_name_prefix="Download") as dl_pool, \
             ThreadPoolExecutor(max_workers=ffmpeg_workers, thread_name_prefix="FFmpeg") as ff_pool, \
             Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]{task.description}"),
                BarColumn(bar_width=None),
                "[progress.percentage]{task.percentage:>3.0f}%",
                TimeRemainingColumn(),
                transient=True,
                console=self.console,
            ) as progress:

            task_id = progress.add_task("Downloading trailers", total=len(movies))
            download_futures = {dl_pool.submit(self._download_task, movie, ff_pool): movie for movie in movies}

            for future in as_completed(download_futures):
                try:
                    result = future.result()
                    if result: self.stats["downloads"].append(result)
                except RuntimeError as e:
                    logger.info(f"⛔ [bold red]CRITICAL:[/] {e}")
                    for f in download_futures: f.cancel()
                    break
                except Exception as e:
                    movie = download_futures[future]
                    logger.info(f"[bold red]Error processing '{movie.get('title')}':[/] {e}")
                finally:
                    progress.advance(task_id)

            ff_pool.shutdown(wait=True)

    def _download_task(self, movie: Dict, ffmpeg_pool: ThreadPoolExecutor) -> Dict:
        movie_id = movie.get("id", 0)
        title = movie.get("title", "Unknown Title")
        release_date = movie.get("release_date", "")
        result = {"folder": title, "downloaded": False, "reason": ""}

        if movie_id in self.known_failures and not self.args.force:
            result["reason"] = "known failure"
            return result

        folder_name = self.fs_manager.prepare_movie_folder_name(title, release_date)
        paths = self.fs_manager.get_movie_paths(folder_name)
        result["folder"] = folder_name

        if self.args.dry_run:
            logger.info(f"- [cyan]{title}[/cyan]")
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
            failure_callback=self._increment_failures
        )

        if not download_ok:
            self.known_failures.add(movie_id)
            result["reason"] = "download failed"
            return result

        result["downloaded"] = True

        if not self.args.skip_placeholders:
            ffmpeg_pool.submit(self._ffmpeg_task, "placeholder", paths, title)
        if self.cfg["CREATE_BACKDROP"]:
            ffmpeg_pool.submit(self._ffmpeg_task, "backdrop", paths, title)

        return result

    def _ffmpeg_task(self, task_type: str, paths: MoviePaths, title: str):
        if self.args.dry_run:
            logger.info(f"[yellow]Dry Run:[/] Would create {task_type} for '[cyan]{title}[/cyan]'")
            return

        if task_type == "placeholder":
            ok = self.asset_generator_service.create_black_video(
                paths.placeholder,
                duration=self.cfg["PLACEHOLDER_DURATION"],
                resolution=self.cfg["PLACEHOLDER_RESOLUTION"],
                overwrite=self.args.overwrite
            )
            if ok:
                logger.info(f"   Created placeholder for {title}")
                self.stats["placeholders"] += 1

        elif task_type == "backdrop":
            ok = self.asset_generator_service.create_backdrop_image(
                paths.backdrop,
                resolution=self.cfg["PLACEHOLDER_RESOLUTION"],
                overwrite=self.args.overwrite
            )
            if ok:
                logger.info(f"   Created backdrop for {title}")
                self.stats["backdrops"] += 1

    def _generate_standalone_assets(self):
        root = self.fs_manager.download_folder
        logger.info(f"Scanning for folders to generate assets in '[cyan]{root}[/cyan]'")

        movie_folders = [d for d in root.iterdir() if d.is_dir()]
        if not movie_folders:
            logger.info("No existing movie folders found to generate assets for.")
            return

        for movie_folder in movie_folders:
            paths = self.fs_manager.get_movie_paths(movie_folder.name)
            if self.args.placeholders and (self.args.overwrite or not paths.placeholder.exists()):
                self._ffmpeg_task("placeholder", paths, movie_folder.name)

            if self.args.backdrops and (self.args.overwrite or not paths.backdrop.exists()):
                self._ffmpeg_task("backdrop", paths, movie_folder.name)

    def _write_report(self):
        report_path = self.args.report
        try:
            with open(report_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["folder", "downloaded", "reason"])
                writer.writeheader()
                writer.writerows(self.stats["downloads"])
            logger.info(f"Wrote report to [cyan]{report_path}[/cyan]")
        except IOError as e:
            logger.error(f"Failed to write report: {e}")

    def _export_movie_list(self, movies: List[Dict], path: str):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(movies, f, indent=2)
            logger.info(f"Exported TMDB movie list to [cyan]{path}[/cyan]")
        except IOError as e:
            logger.error(f"[bold red]Error:[/] Failed to export movie list: {e}")