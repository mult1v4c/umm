import logging
import sys
import time
import json
from pathlib import Path

from rich import box
from rich.console import Console, Group
from rich.logging import RichHandler
from rich.panel import Panel
from rich.text import Text
from rich.rule import Rule
from rich.align import Align

from config import load_config, STATUS_FILENAME
from media_manager import MediaManager

console = Console()
logger = logging.getLogger("media_manager")
DRY_RUN = True # Default ON for safety

def _update_last_run_time(status_path: Path):
    # Saves the current timestamp to the status file
    try:
        status_path.parent.mkdir(parents=True, exist_ok=True)
        with status_path.open("w", encoding="utf-8") as f:
            json.dump({"last_run": time.time()}, f)
    except IOError as e:
        logger.warning(f"Could not update last run time: {e}")

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

def print_menu():
    console.clear()
    ascii_art = r"""
 █████ ████ █████████████   █████████████
  ███  ███   ███  ███  ███   ███  ███  ███
  ███  ███   ███  ███  ███   ███  ███  ███
  ███  ███   ███  ███  ███   ███  ███  ███
   ████████ █████ ███ █████ █████ ███ █████ ██ ██ ██
"""
    console.print(Align.left(f"[bold cyan]{ascii_art}[/bold cyan]"))
    console.print(Align.left("[dim]Unified (Unreasonable) Media Manager[/dim]\n"))

    dry_run_status = "[bold green]ON[/]" if DRY_RUN else "[bold red]OFF[/]"

    # Option list
    options_text = Text.from_markup(
        "[bold green][1][/bold green] Sanitize & Catalog Movie Library\n"
        "[bold green][2][/bold green] Fetch Trailers for Existing Movies\n"
        "[bold green][3][/bold green] Fetch Upcoming Movie Trailers\n"
        "[bold green][4][/bold green] Sync Trailers with Movie Library\n"
        "[bold green][5][/bold green] Library Status\n"
        "[bold green][6][/bold green] Settings and Utilities\n"
        "[bold red][0][/bold red] Exit"
    )

    # Toggle section
    toggle_text = Text.from_markup(
        f"[bold yellow][D][/bold yellow] Toggle Dry-Run Mode (Currently: {dry_run_status})"
    )

    # Combine everything with a separator rule
    menu_group = Group(
        options_text,
        Rule(style="cyan dim"),
        toggle_text
    )

    # Main bordered panel
    menu_panel = Panel(
        menu_group,
        title="[bold cyan]Options[/bold cyan]",
        title_align="left",
        box=box.SQUARE,
        border_style="cyan",
        padding=(1, 3)
    )

    # left the whole panel for symmetry
    console.print(Align.left(menu_panel))


def main():
    global DRY_RUN
    start_time = time.monotonic()

    setup_logging("INFO")
    config = load_config()

    try:
        cache_folder = Path(config["CACHE_FOLDER"]).expanduser()
        status_path = cache_folder / STATUS_FILENAME
    except Exception as e:
        logger.error(f"Failed to initialize cache path from config: {e}")
        sys.exit(1)

    if "YOUR_API_KEY" in config["TMDB_API_KEY"]:
        logging.getLogger("media_manager").error(
            "[red]Please set your TMDB_API_KEY in config.json"
            )
        sys.exit(1)

    manager = MediaManager(config, console, lambda: DRY_RUN)

    while True:
            _update_last_run_time(status_path)
            print_menu()
            choice = console.input("Choose an option: ").strip().lower()

            if choice == "1":
                manager.sanitize_and_catalog_library()
            elif choice == "2":
                manager.fetch_trailers_for_existing_movies()
            elif choice == "3":
                manager.fetch_upcoming_movie_trailers()
            elif choice == "4":
                manager.sync_trailers_with_library()
            elif choice == "5":
                manager.show_library_status()
            elif choice == "6":
                manager.show_settings_and_utilities()
            elif choice == "d":
                DRY_RUN = not DRY_RUN
            elif choice == "0":
                break
            else:
                console.print("[bold red]Invalid option, please try again.[/bold red]")
                time.sleep(1)

            if choice in "12345":
                console.input("\nPress Enter to return to the menu...")


    end_time = time.monotonic()
    duration_s = end_time - start_time
    minutes, seconds = divmod(int(duration_s), 60)
    duration_str = f"{minutes:02d}m {seconds:02d}s"
    logging.getLogger("media_manager").info(
        f"[green]✅ UMM session complete![/green] Total duration: {duration_str}"
    )

if __name__ == "__main__":
    main()