# De tool heet tegenwoordig Reelstudio; dit laagje houdt oude aanroepen
# werkend — zowel `python3 tutorial.py …` als `import tutorial`.
import os
import sys

if __name__ == "__main__":
    import runpy
    sys.argv[0] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reelstudio.py")
    runpy.run_path(sys.argv[0], run_name="__main__")
else:
    import reelstudio
    sys.modules[__name__] = reelstudio
