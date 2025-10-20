import logging
import sys
import time

from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.text import Text

from config import load_config
from media_manager import MediaManager

console = Console()
DRY_RUN = True # Default ON for safety

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
    console.print(
        Panel(
            Text(
                "UMM - Unified (Unreasonable) Media Manager",
                justify="center",
                style="bold cyan",
            )
        )
    )
    console.print("-----------------------------------", justify="center")
    console.print("[bold green][1][/] Sanitize & Catalog Movie Library")
    console.print("[bold green][2][/] Fetch Trailers for Existing Movies")
    console.print("[bold green][3][/] Fetch Upcoming Movie Trailers")
    console.print("[bold green][4][/] Sync Trailers with Movie Library")
    console.print("[bold green][5][/] Library Status")
    console.print("[bold green][6][/] Settings and Utilities")
    console.print("[bold red][0][/] Exit")
    console.print("-----------------------------------", justify="center")

    dry_run_status = "[bold green]ON[/]" if DRY_RUN else "[bold red]OFF[/]"
    console.print(f"[bold yellow][D][/] Toggle Dry-Run Mode (Currently: {dry_run_status})")
    console.print("-----------------------------------", justify="center")

def main():
    global DRY_RUN
    start_time = time.monotonic()

    setup_logging("INFO")
    config = load_config()

    if "YOUR_API_KEY" in config["TMDB_API_KEY"]:
        logging.getLogger("media_manager").error(
            "[red]Please set your TMDB_API_KEY in config.json or via the --tmdb-api-key flag.[/red]"
            )
        sys.exit(1)

    manager = MediaManager(config, console, lambda: DRY_RUN)

    while True:
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

            if choice in "123456":
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