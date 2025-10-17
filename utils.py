import logging
import subprocess
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