import os

import setproctitle
from infinity_emb.cli import cli

if __name__ == "__main__":
    # Set process name similar to orchestrator
    # Orchestrator uses: EvLab-Pipeline-{pid}
    setproctitle.setproctitle(f"EvLab-EmbedServer-{os.getpid()}")

    # Run the Infinity CLI
    # This will parse sys.argv and start the server
    cli()
