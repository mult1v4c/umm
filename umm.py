import argparse
import textwrap
import logging
import sys
import time

from rich.console import Console
from rich.logging import RichHandler

from config import load_config
from media_manager import MediaManager

console = Console()

def setup_logging(level: str = "INFO"):

    logger = logging.getLogger("media_manager")
    logger.setLevel(level.upper())

    if logger.hasHandlers():
        logger.handlers.clear()

    rich_handler = RichHandler(
        console=console,
        show_time=True,
        show_level=False,
        show_path=False,
        markup=True,
        log_time_format="[%X]"
    )

    logger.addHandler(rich_handler)

class SmartFormatter(argparse.ArgumentDefaultsHelpFormatter):
    def _fill_text(self, text, width, indent):
        wrapped_lines = []
        for line in text.splitlines():
            if not line.strip():
                wrapped_lines.append("")
            else:
                wrapped_lines.append(textwrap.fill(
                    line,
                    width,
                    initial_indent=indent,
                    subsequent_indent=indent
                ))
        return "\n".join(wrapped_lines)

def create_arg_parser():
    p = argparse.ArgumentParser(
        prog="UMM",
        description=textwrap.dedent("""
            Unified Media Manager (UMM)
            ---------------------------
            Download trailers, create placeholders, and organize your media library.
            """),
        formatter_class=SmartFormatter,
        epilog="Configuration defaults can be changed in config.json."
    )

    # ----------------------------------------------------------------------
    # Year Selection
    # ----------------------------------------------------------------------
    year_group = p.add_argument_group("Year Selection")
    yg = year_group.add_mutually_exclusive_group()
    yg.add_argument("--year", type=int, help="Process a single year (e.g., 2025).")
    yg.add_argument("--year-start", type=int, help="The first year to process.")
    year_group.add_argument("--year-end", type=int, help="The last year to process (used with --year-start).")

    # ----------------------------------------------------------------------
    # Actions
    # ----------------------------------------------------------------------
    action_group = p.add_argument_group("Actions")
    ag = action_group.add_mutually_exclusive_group()
    ag.add_argument("--all", action="store_true",
                    help="Run all stages (download, process, organize). Default if none specified.")
    ag.add_argument("--download", action="store_true",
                    help="Only download trailers and create assets.")
    ag.add_argument("--placeholders", action="store_true",
                    help="Only create placeholder videos in existing folders.")
    ag.add_argument("--backdrops", action="store_true",
                    help="Only create backdrop images in existing folders.")

    # ----------------------------------------------------------------------
    # General Options
    # ----------------------------------------------------------------------
    general = p.add_argument_group("General Options")
    general.add_argument("--dry-run", action="store_true",
                         help="Simulate all actions without writing files.")
    general.add_argument("--force", action="store_true",
                         help="Force re-downloading even if trailer files already exist.")
    general.add_argument("--overwrite", action="store_true",
                         help="Overwrite existing placeholder or backdrop files.")
    general.add_argument("--skip-placeholders", action="store_true",
                         help="Skip creating placeholder videos.")
    general.add_argument("--count", type=int,
                         help="Limit the number of trailers to download.")

    # ----------------------------------------------------------------------
    # Performance
    # ----------------------------------------------------------------------
    perf = p.add_argument_group("Performance")
    perf.add_argument("--max-download-workers", type=int,
                      help="Override number of concurrent download threads.")
    perf.add_argument("--max-ffmpeg-workers", type=int,
                      help="Override number of concurrent FFmpeg tasks.")

    # ----------------------------------------------------------------------
    # Cache & Failure Handling
    # ----------------------------------------------------------------------
    cache = p.add_argument_group("Cache and Failure Handling")
    cache.add_argument("--clear-cache", action="store_true",
                       help="Clear the TMDB API cache before running.")
    cache.add_argument("--no-cache", action="store_true",
                       help="Do not use the TMDB API cache.")
    cache.add_argument("--ignore-failures", action="store_true",
                       help="Continue execution even after 5 failed downloads.")

    # ----------------------------------------------------------------------
    # Paths & Tool Overrides
    # ----------------------------------------------------------------------
    paths = p.add_argument_group("Paths and Tool Overrides")
    paths.add_argument("--download-folder", type=str,
                       help="Override the base download folder path.")
    paths.add_argument("--cache-folder", type=str,
                       help="Override the cache folder path.")
    paths.add_argument("--ffmpeg", type=str,
                       help="Specify custom path to ffmpeg executable.")
    paths.add_argument("--yt-dlp", type=str,
                       help="Specify custom path to yt-dlp executable.")

    # ----------------------------------------------------------------------
    # Reporting & Organization
    # ----------------------------------------------------------------------
    reports = p.add_argument_group("Reporting and Organization")
    reports.add_argument("--export-list", type=str,
                         help="Export the fetched TMDB movie list to a JSON file.")
    reports.add_argument("--report", type=str,
                         help="Generate a CSV report of processed items.")
    reports.add_argument("--clean-empty", action="store_true",
                         help="Remove empty subfolders after processing.")

    # ----------------------------------------------------------------------
    # Logging & Configuration
    # ----------------------------------------------------------------------
    logcfg = p.add_argument_group("Logging and Configuration")
    logcfg.add_argument("--tmdb-api-key", type=str,
                        help="Override the TMDB API key manually.")
    logcfg.add_argument("--verbose", "-v", action="store_true",
                        help="Enable verbose DEBUG logging output.")
    logcfg.add_argument("--quiet", action="store_true",
                        help="Only show ERROR-level messages.")

    return p


def main():
    start_time = time.monotonic()

    log_level = "DEBUG" if args.verbose else "ERROR" if args.quiet else "INFO"

    setup_logging(log_level)
    config = load_config()

    if args.tmdb_api_key: config["TMDB_API_KEY"] = args.tmdb_api_key
    if args.download_folder: config["DOWNLOAD_FOLDER"] = args.download_folder

    if "YOUR_API_KEY" in config["TMDB_API_KEY"]:
        logging.getLogger("media_manager").error("[red]Please set your TMDB_API_KEY in config.json or via the --tmdb-api-key flag.[/red]")
        sys.exit(1)

    manager = MediaManager(config, args, console)
    try:
        manager.run()
    except Exception as e:
        logging.getLogger("media_manager").error(f"[bold red]An unexpected error occurred: {e}[/bold red]", exc_info=True)
        sys.exit(1)

    end_time = time.monotonic()
    duration_s = end_time - start_time
    minutes, seconds = divmod(int(duration_s), 60)
    duration_str = f"{minutes:02d}m {seconds:02d}s"
    logging.getLogger("media_manager").info(f"[green]✅ All tasks complete![/green] Took {duration_str}")

if __name__ == "__main__":
    parser = create_arg_parser()
    args = parser.parse_args()
    main()