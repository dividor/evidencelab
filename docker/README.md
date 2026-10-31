# Evidence Lab

![Evidence Lab](https://github.com/dividor/evidencelab/raw/main/docs/images/evidence-lab.png)

Evidence Lab is a free, open source platform for searching and analyzing collections of reports. It parses PDF and Word documents, indexes them for hybrid semantic search, and adds an AI research assistant, briefs and maps. MCP and A2A servers connect it to AI platforms.

This image runs the API, the MCP server and the document pipeline. One image runs all three, each with a different start command. The web interface is built on your machine from the repository, because it carries your API key or sign-in setting, data sources and branding.

- **Source and issues:** https://github.com/dividor/evidencelab
- **Setup guide:** https://github.com/dividor/evidencelab/blob/main/docs/admin/docker-images.md
- **Demo:** https://evidencelab.ai
- **Mirror without Docker Hub pull limits:** `ghcr.io/dividor/evidencelab`

## Tags

| Tag | Meaning |
|---|---|
| `1.6.5` | An exact release. Use this in production. |
| `1.6` | The newest patch of a minor release. |
| `latest` | The newest release. |
| `rc-v1.6.6` | The release candidate in progress, for testing only. It changes as work is merged. |

Every tag covers `linux/amd64` and `linux/arm64`.

## Quick start

You need Docker with Compose, Python 3 and git, plus an API key for one model provider (Azure Foundry, Hugging Face or Google Vertex).

```bash
git clone https://github.com/dividor/evidencelab.git
cd evidencelab
python3 scripts/demo/run_demo.py --mode hub
```

The script asks for your provider and its key, generates every password and secret, loads three World Bank reports as demo data, and starts Evidence Lab. Then open http://localhost:8080. Add `--version 1.6.5` to run a specific release instead of `latest`. The setup guide covers manual setup, your own documents and upgrades.

Each image carries build provenance and a software bill of materials:

```bash
docker buildx imagetools inspect astrobagel/evidencelab:<version> --format '{{ json .SBOM }}'
```

Evidence Lab is released under the MIT License.
