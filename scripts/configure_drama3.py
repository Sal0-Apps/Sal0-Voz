"""Add measured frame events to the pinned native decoder; keep sampling intact."""
from pathlib import Path
import sys


def configure(root):
    path = Path(root)/"src/community_models/fish_drama3/generator.cpp"
    source = path.read_text()
    anchor = "        output_frames.push_back(next);"
    if "SAL0_DRAMA_FRAME=" not in source:
        if source.count(anchor) != 1:
            raise ValueError("O contador não corresponde ao motor Drama 3 fixado.")
        source = source.replace(anchor, anchor+'\n        std::cerr << "SAL0_DRAMA_FRAME=" << output_frames.size() << "\\n";', 1)
        path.write_text(source)


if __name__ == "__main__":
    configure(sys.argv[1])
