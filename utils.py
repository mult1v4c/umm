import logging
import subprocess
import time
from typing import List, Optional, Tuple

logger = logging.getLogger("media_manager")

def run_subprocess(cmd: List[str]) -> Tuple[bool, Optional[str], Optional[str]]:
    try:
        proc = subprocess.run(
            cmd, check=True, capture_output=True, text=True, encoding='utf-8', errors='replace'
        )
        return True, proc.stdout, proc.stderr
    except FileNotFoundError:
        logger.error(f"[red]Command not found:[/] {cmd[0]}. Is it in your system's PATH?")
        return False, None, None
    except subprocess.CalledProcessError as e:
        logger.error(f"[red]Subprocess failed for command:[/] {' '.join(cmd)}")
        logger.debug(f"Stderr: {e.stderr.strip()}")
        return False, e.stdout, e.stderr

def format_time_ago(timestamp: float) -> str:
    if timestamp == 0:
        return "never"

    now = time.time()
    diff_seconds = now - timestamp

    if diff_seconds < 60:
        return "just now"
    elif diff_seconds < 3600: # Less than 1 hour
        return f"{int(diff_seconds // 60)}m ago"
    elif diff_seconds < 86400: # Less than 1 day
        return f"{int(diff_seconds // 3600)}h ago"
    else: # More than 1 day
        return f"{int(diff_seconds // 86400)}d ago"