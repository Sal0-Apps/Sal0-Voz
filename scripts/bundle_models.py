"""Bake the required models outside /data, so a host volume cannot hide them."""
import os
import shutil
import subprocess
import sys
from app.catalog import DEFAULT_MODELS
from app import storage as s

def main():
    models = os.getenv("SAL0_BUNDLE_MODELS", ",".join(DEFAULT_MODELS))
    for ident in filter(None, (x.strip() for x in models.split(","))):
        for action in (["plan", ident], ["install", ident, "--accept-license"], ["verify", ident]):
            subprocess.run([sys.executable, "-m", "scripts.models", *action], check=True)
        shutil.rmtree(s.DATA / "models" / ident / ".cache", ignore_errors=True)

if __name__ == "__main__":
    main()
