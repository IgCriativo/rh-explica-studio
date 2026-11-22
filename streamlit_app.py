# Ponto de entrada padrão para Streamlit Cloud
import runpy
from pathlib import Path

app_file = Path(__file__).parent / "app_narrador.py"
runpy.run_path(str(app_file), run_name="__main__")
