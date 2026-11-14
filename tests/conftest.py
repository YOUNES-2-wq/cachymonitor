import os
import sys

# Les tests tournent sans ecran : Qt n'est de toute facon pas necessaire ici.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
