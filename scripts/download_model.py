"""Explicit setup-only download. Runtime does not contact the Hub."""
import json
from pathlib import Path
from huggingface_hub import snapshot_download

if __name__ == "__main__":
    repo = "IDEA-Research/grounding-dino-tiny"
    revision = "a2bb814dd30d776dcf7e30523b00659f4f141c71"
    out = Path("models/grounding-dino-tiny")
    snapshot_download(repo, revision=revision, local_dir=out,
        allow_patterns=["*.json", "*.txt", "*.safetensors", "README.md", "LICENSE*"])
    (out / "provenance.json").write_text(json.dumps({"repo": repo, "revision": revision,
        "license": "Apache-2.0 (model card)", "source": f"https://huggingface.co/{repo}"}, indent=2), encoding="utf-8")
    print("Local weights ready:", out.resolve())
