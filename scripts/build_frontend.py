"""Package the existing playground as Vercel static output."""
from pathlib import Path
import shutil
import sys

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
from app.frontend import render_page

output = root / "public"
if output.exists():
    shutil.rmtree(output)
output.mkdir(exist_ok=True)
shutil.copytree(root / "app/static", output / "static", dirs_exist_ok=True)
(output / "index.html").write_text(render_page("landing"))
(output / "playground.html").write_text(render_page("workspace"))

(output / "404.html").write_text(render_page("not-found"))
