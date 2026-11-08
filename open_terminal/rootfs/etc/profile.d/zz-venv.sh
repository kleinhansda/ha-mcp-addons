# Python-Umgebung der App (Pakete aus den Optionen, per uv in ~/.venv) vor das System-Python
if [ -d "$HOME/.venv/bin" ]; then
  case ":$PATH:" in *":$HOME/.venv/bin:"*) ;; *) PATH="$HOME/.venv/bin:$PATH" ;; esac
  VIRTUAL_ENV="$HOME/.venv"
  export PATH VIRTUAL_ENV
fi
