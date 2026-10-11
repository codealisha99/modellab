"""Package the existing playground as Vercel static output."""
from pathlib import Path
import shutil

root = Path(__file__).resolve().parent.parent
output = root / "public"
output.mkdir(exist_ok=True)
shutil.copytree(root / "app/static", output / "static", dirs_exist_ok=True)
shutil.copyfile(root / "app/static/index.html", output / "index.html")
landing = (root / "app/static/index.html").read_text()
playground = landing.replace('class="landing"', 'class="workspace"').replace(
    "ModelLab · Explore models and streaming", "ModelLab · Streaming playground"
)
(output / "playground.html").write_text(playground)
